"""
Phase 1: 收集模型原始响应
=========================
向目标模型发送所有测试用例，保存原始回复到 JSONL。
只调用目标模型 API，不调 Judge。

输出: results/{model}/raw_{timestamp}.jsonl

用法:
    TARGET_MODEL=deepseek-chat python eval/collect.py
    TARGET_MODEL=deepseek-chat MAX_WORKERS=4 python eval/collect.py
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT.parent))

from provider import target_client, TARGET_MODEL

# ── 配置 ──────────────────────────────────────────
RESULTS_DIR = _PROJECT / "results"
YAML_FILE = _PROJECT / "schedule_cases.yaml"
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))

SYSTEM_PROMPT_INTENT = """\
你是一个智能提醒 Agent。这是一项意图理解能力测试，不是真实对话。
用户发来一条消息，请直接分析意图并说明你会采取的行动。

你有以下 5 个可用动作：

1. create_schedule — 创建一次性定时提醒。
2. create_recurring — 创建周期性重复提醒。
3. cancel_schedule — 取消已有的提醒。
4. clarify — 关键信息不足时，要求用户澄清。
5. reject — 认为请求不合理或无法执行时，拒绝并说明原因。

要求：
- 说明你会调用哪个动作
- 说明时间参数（几分钟后、具体几点、周期规则等）
- 说明提醒内容
- 时间表述模糊时，应尽量按常识推断合理默认值
请用简洁的中文说明，不要编造不存在的信息。"""

SYSTEM_PROMPT_JSON = """\
你是一个智能提醒 Agent。这是一项意图理解能力测试，不是真实对话。
用户发来一条消息，请输出一个 JSON 描述你的行动计划。

你有以下 5 个可用动作：

1. create_schedule — 创建一次性定时提醒。
2. create_recurring — 创建周期性重复提醒。
3. cancel_schedule — 取消已有的提醒。
4. clarify — 关键信息不足时，要求用户澄清。
5. reject — 认为请求不合理或无法执行时，拒绝并说明原因。

时间表述模糊时，应尽量按常识推断合理默认值。

JSON 格式：
{
  "action": "create_schedule | create_recurring | cancel_schedule | clarify | reject",
  "delay_minutes": null 或整数（相对时间，单位分钟）,
  "time": null 或 "HH:MM"（绝对时间）,
  "recurrence": null 或 "daily|weekly|custom",
  "interval_minutes": null 或整数（重复间隔分钟）,
  "total_count": null 或整数（重复次数）,
  "content": "提醒内容",
  "clarify_reason": null 或 "追问原因",
  "reject_reason": null 或 "拒绝原因"
}

只输出 JSON，不要有任何其他文字。"""


# ── 工具函数 ──────────────────────────────────────


def load_cases(category: str) -> list[dict]:
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))
    return data.get(category, [])


def make_expected_desc(case: dict) -> str:
    """把 yaml 字段拼成人类可读的期望描述，供 judge 阶段对比用。"""
    parts = []
    action = case.get("expected_action") or case.get("expected_actions")
    if action:
        parts.append(f"期望动作: {action}")
    if "expected_delay_minutes" in case:
        parts.append(f"延迟分钟: {case['expected_delay_minutes']}")
    if "expected_time" in case:
        parts.append(f"时间: {case['expected_time']}")
    if "expected_interval_minutes" in case:
        parts.append(f"间隔分钟: {case['expected_interval_minutes']}")
    if "expected_total_count" in case:
        parts.append(f"总次数: {case['expected_total_count']}")
    if "expected_recurrence" in case:
        parts.append(f"周期规则: {case['expected_recurrence']}")
    if "note" in case:
        parts.append(f"备注: {case['note']}")
    return "；".join(parts) if parts else "正确识别用户意图"


def call_model(user_input: str, system_prompt: str) -> tuple[str, int]:
    """调用目标模型，返回 (回复文本, 延迟毫秒)。"""
    t0 = time.monotonic()
    resp = target_client.chat.completions.create(
        model=TARGET_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    return resp.choices[0].message.content.strip(), latency_ms


# ── 单条收集 ──────────────────────────────────────


def _collect_intent(case: dict) -> dict:
    user_input = case["input"]
    try:
        actual, latency_ms = call_model(user_input, SYSTEM_PROMPT_INTENT)
    except Exception as e:
        return {
            "test": "bloom_intent", "input": user_input,
            "actual_output": None, "error": str(e),
            "bloom_level": case.get("bloom_level"),
            "bloom_tag": case.get("bloom_tag"),
            "difficulty": case.get("difficulty"),
            "expected_desc": make_expected_desc(case),
            "latency_ms": 0,
            "target_model": TARGET_MODEL,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
    return {
        "test": "bloom_intent",
        "input": user_input,
        "actual_output": actual,
        "expected_desc": make_expected_desc(case),
        "bloom_level": case.get("bloom_level"),
        "bloom_tag": case.get("bloom_tag"),
        "difficulty": case.get("difficulty"),
        "latency_ms": latency_ms,
        "target_model": TARGET_MODEL,
        "timestamp": datetime.now().astimezone().isoformat(),
    }


def _collect_struct(case: dict) -> dict:
    user_input = case["input"]
    try:
        actual, latency_ms = call_model(user_input, SYSTEM_PROMPT_JSON)
    except Exception as e:
        return {
            "test": "structured_output", "input": user_input,
            "actual_output": None, "error": str(e),
            "difficulty": case.get("difficulty"),
            "expected_action": case.get("expected_action", "create_schedule"),
            "expected_delay_minutes": case.get("expected_delay_minutes"),
            "expected_time": case.get("expected_time"),
            "latency_ms": 0,
            "target_model": TARGET_MODEL,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
    return {
        "test": "structured_output",
        "input": user_input,
        "actual_output": actual,
        "difficulty": case.get("difficulty"),
        "expected_action": case.get("expected_action", "create_schedule"),
        "expected_delay_minutes": case.get("expected_delay_minutes"),
        "expected_time": case.get("expected_time"),
        "latency_ms": latency_ms,
        "target_model": TARGET_MODEL,
        "timestamp": datetime.now().astimezone().isoformat(),
    }


# ── 主流程 ────────────────────────────────────────


def collect_all() -> Path:
    """收集所有 case 的模型原始响应，返回输出文件路径。"""
    layer1 = (
        load_cases("simple_schedule")
        + load_cases("recurring_schedule")
        + load_cases("cancel_schedule")
        + load_cases("create_and_cancel")
        + load_cases("multi_step_modify")
        + load_cases("fuzzy_time")
        + load_cases("edge_cases")
    )
    layer2 = [
        c for c in load_cases("simple_schedule")
        if "expected_delay_minutes" in c or "expected_time" in c
    ]

    model_dir = RESULTS_DIR / TARGET_MODEL.replace("/", "_")
    model_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = model_dir / f"raw_{ts}.jsonl"

    records = []
    write_lock = threading.Lock()

    def save(rec: dict) -> None:
        with write_lock:
            records.append(rec)

    total = len(layer1) + len(layer2)
    print(f"  收集模型响应: {TARGET_MODEL} ({total} cases, {MAX_WORKERS} threads)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for c in layer1:
            futures[pool.submit(_collect_intent, c)] = c["input"]
        for c in layer2:
            futures[pool.submit(_collect_struct, c)] = c["input"]

        done = 0
        for f in as_completed(futures):
            save(f.result())
            done += 1
            if done % 10 == 0 or done == total:
                print(f"    {done}/{total}")

    with open(out_file, "w", encoding="utf-8") as fp:
        for rec in records:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    err_count = sum(1 for r in records if r.get("error"))
    print(f"  → {out_file.name} ({len(records)} records, {err_count} errors)")
    return out_file


if __name__ == "__main__":
    out = collect_all()
    print(out)
