"""
Phase 2: GEval 评分 + 结构化断言
=================================
读取 collect 阶段保存的原始响应 (raw_*.jsonl)，
对 intent 类用 GEval 打分，对 struct 类用 JSON 确定性断言。

输出: 同目录下 run_{timestamp}.jsonl（与 analyze.py 兼容）

用法:
    python eval/judge.py results/deepseek-chat/raw_20260411_120000.jsonl
    MAX_WORKERS=4 python eval/judge.py results/deepseek-chat/raw_20260411_120000.jsonl
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT.parent))

from provider import get_judge_gpt_model

INTENT_THRESHOLD = 0.7
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))


def _make_intent_metric():
    """每个线程创建独立的 GEval 实例（measure() 存状态到 self，不线程安全）。"""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="Schedule Intent Understanding",
        criteria=(
            "判断 actual_output 是否正确理解了用户的定时任务意图。重点检查：\n"
            "1. action 是否正确（创建/取消/追问/拒绝）\n"
            "2. 时间或延迟是否正确识别\n"
            "3. 如果信息不足，是否说明会追问\n"
            "4. 没有凭空捏造不存在的时间信息"
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=get_judge_gpt_model(),
        threshold=INTENT_THRESHOLD,
    )


# ── 评分逻辑 ──────────────────────────────────────


def _judge_intent(record: dict) -> dict:
    """对 bloom_intent 记录执行 GEval 评分。"""
    from deepeval.test_case import LLMTestCase

    result = dict(record)  # 复制原始字段

    if record.get("error") or not record.get("actual_output"):
        result["score"] = None
        result["passed"] = False
        result["reason"] = record.get("error", "no output")
        return result

    metric = _make_intent_metric()
    test_case = LLMTestCase(
        input=record["input"],
        actual_output=record["actual_output"],
        expected_output=record.get("expected_desc", ""),
        context=["用户正在使用一个智能提醒 Agent"],
    )

    score = None
    reason = ""
    try:
        metric.measure(test_case)
        score = metric.score
        reason = metric.reason or ""
    except Exception as e:
        reason = f"judge error: {e}"

    passed = (score or 0) >= INTENT_THRESHOLD

    result["score"] = score
    result["passed"] = passed
    result["reason"] = reason
    # rename expected_desc → expected (兼容 analyze.py)
    result["expected"] = result.pop("expected_desc", "")
    return result


def _judge_struct(record: dict) -> dict:
    """对 structured_output 记录执行 JSON 确定性断言。"""
    result = dict(record)

    if record.get("error") or not record.get("actual_output"):
        result["passed"] = False
        result["errors"] = [record.get("error", "no output")]
        return result

    raw = record["actual_output"]
    errors = []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        errors.append("invalid JSON")
        result["passed"] = False
        result["errors"] = errors
        return result

    expected_action = record.get("expected_action", "create_schedule")
    if parsed.get("action", "") != expected_action:
        errors.append(f"action: expected {expected_action!r}, got {parsed.get('action')!r}")

    if record.get("expected_delay_minutes") is not None:
        if parsed.get("delay_minutes") != record["expected_delay_minutes"]:
            errors.append(
                f"delay_minutes: expected {record['expected_delay_minutes']}, "
                f"got {parsed.get('delay_minutes')}"
            )

    if record.get("expected_time") is not None:
        if parsed.get("time", "") != record["expected_time"]:
            errors.append(
                f"time: expected {record['expected_time']!r}, "
                f"got {parsed.get('time')!r}"
            )

    result["passed"] = len(errors) == 0
    result["errors"] = errors
    # 将 expected 字段统一为字符串（兼容 analyze.py）
    result["expected"] = str({
        k: record[k] for k in ("expected_action", "expected_delay_minutes", "expected_time")
        if k in record and record[k] is not None
    })
    return result


# ── 主流程 ────────────────────────────────────────


def judge_all(raw_file: Path) -> Path:
    """读取 raw JSONL，评分，写出 run JSONL。返回输出文件路径。"""
    raw_records: list[dict] = []
    with open(raw_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_records.append(json.loads(line))

    intent_records = [r for r in raw_records if r.get("test") == "bloom_intent"]
    struct_records = [r for r in raw_records if r.get("test") == "structured_output"]

    print(f"  评分: {len(intent_records)} intent (GEval) + {len(struct_records)} struct (断言)")
    print(f"  Judge 并发线程数: {MAX_WORKERS}")

    scored: list[dict] = []

    # struct 不需要 API，直接同步处理
    for rec in struct_records:
        scored.append(_judge_struct(rec))

    # intent 需要调 GEval API，多线程并发
    if intent_records:
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_judge_intent, r): r["input"] for r in intent_records}
            done = 0
            for f in as_completed(futures):
                scored.append(f.result())
                done += 1
                if done % 10 == 0 or done == len(intent_records):
                    print(f"    intent: {done}/{len(intent_records)}")
        elapsed = time.monotonic() - t0
        print(f"  GEval 评分耗时: {elapsed:.0f}s")

    # 写出 run_{ts}.jsonl（同目录，时间戳对齐 raw 文件）
    ts = raw_file.stem.replace("raw_", "")
    out_file = raw_file.parent / f"run_{ts}.jsonl"
    with open(out_file, "w", encoding="utf-8") as fp:
        for rec in scored:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    passed = sum(1 for r in scored if r.get("passed"))
    total = len(scored)
    print(f"  → {out_file.name} ({passed}/{total} passed)")
    return out_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python eval/judge.py <raw_file.jsonl>")
        sys.exit(1)
    raw_path = Path(sys.argv[1])
    if not raw_path.is_absolute():
        raw_path = _PROJECT / raw_path
    judge_all(raw_path)
