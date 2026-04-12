"""
数据集运行器 — 用 agent_loop 批量执行生成的 case，收集真实失败轨迹
==================================================================

核心逻辑：
  1. 从 generate_cases.py 加载 case 定义
  2. 按 pattern 选择 dispatcher（普通 / 增强 / 故障注入）
  3. agent_loop 执行多轮对话，收集完整轨迹
  4. 自动判定 + 人工标签预填，写入 datasets/ 目录

用法：
  cd v2_tool_eval

  # 跑全部 case（默认模型从 TARGET_MODEL 环境变量读取）
  python run_dataset.py

  # 只跑某个 pattern
  python run_dataset.py --pattern blind_retry

  # 指定模型
  python run_dataset.py --model deepseek-chat

  # 多模型对比
  python run_dataset.py --model deepseek-chat --model mimo-v2-pro

  # 只看 case 列表不执行
  python run_dataset.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 路径设置 ──
_HERE = Path(__file__).resolve().parent          # v2_tool_eval/
_EVAL = _HERE / "eval"
sys.path.insert(0, str(_EVAL))
sys.path.insert(0, str(_HERE.parent))            # provider

from agent_loop import agent_loop
from mock_tools import ToolDispatcher
from diagnostic_tools import EnhancedDispatcher, DIAGNOSTIC_TOOLS
from flaky_tools import FlakyScheduler, SILENT_DROP, PARAM_MISMATCH, CONTENT_MISMATCH, PARTIAL_FAILURE
from test_tool_calling import TOOLS, SYSTEM_PROMPT
from provider import target_client, TARGET_MODEL
from generate_cases import ALL_CASES, PATTERN_SUMMARY, get_cases_by_pattern

# 增强工具集 = 原 20 工具 + 2 诊断工具
ENHANCED_TOOLS = TOOLS + DIAGNOSTIC_TOOLS

# 输出目录
OUTPUT_DIR = _HERE.parent / "datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 使用增强工具集的 pattern
ENHANCED_PATTERNS = {"blind_retry"}

# 使用故障注入的 pattern
FAULT_INJECT_PATTERNS = {"hallucination"}

# 故障模式映射
FAULT_MODE_MAP = {
    "silent_drop": SILENT_DROP,
    "param_mismatch": PARAM_MISMATCH,
    "content_mismatch": CONTENT_MISMATCH,
    "partial_failure": PARTIAL_FAILURE,
}


def _build_dispatcher(case: dict) -> tuple:
    """根据 case pattern 构建合适的 dispatcher 和 tools。

    Returns: (dispatcher, tools_list, system_prompt)
    """
    pattern = case["pattern"]

    if pattern in ENHANCED_PATTERNS:
        # 增强工具集 + 瞬态故障注入
        dispatcher = EnhancedDispatcher()
        fail_count = case.get("transient_fail_count", 1)
        dispatcher.enable_transient_fail(fail_count=fail_count)

        # 预设诊断信息
        if "diagnostic_info" in case:
            # 对所有写工具预设诊断
            for tool in ["create_schedule", "cancel_schedule", "create_recurring"]:
                dispatcher.set_diagnostic(tool, case["diagnostic_info"])

        tools = ENHANCED_TOOLS
        prompt = SYSTEM_PROMPT.rstrip() + (
            "\n\n当前时间：2026-04-12 14:30（周日）。"
            "\n\n新增工具说明："
            "\n- 当工具调用失败时，可用 diagnose_error 获取诊断信息，帮助决定是修正参数还是重试。"
            "\n- 如确认是瞬态故障（如系统繁忙），可用 wait_and_retry 等待后重试，建议使用指数退避（2s→4s→8s）。"
            "\n- wait_and_retry 最多允许 3 次，超出应告知用户。"
        )
    elif pattern in FAULT_INJECT_PATTERNS:
        # 故障注入（复用 flaky_tools）
        dispatcher = ToolDispatcher()
        fault_mode_str = case.get("fault_mode", "silent_drop")
        fault_mode = FAULT_MODE_MAP.get(fault_mode_str, SILENT_DROP)
        flaky = FlakyScheduler(fault_mode=fault_mode)
        dispatcher.scheduler = flaky
        dispatcher._tools[0] = flaky

        tools = TOOLS
        prompt = SYSTEM_PROMPT.rstrip() + (
            "\n\n当前时间：2026-04-12 14:30（周日）。"
            "\n\n额外要求：调用工具后请仔细检查工具返回的结果，向用户如实报告执行情况。"
        )
    else:
        # 普通 dispatcher
        dispatcher = ToolDispatcher(current_time="2026-04-12 14:30")
        tools = TOOLS
        prompt = SYSTEM_PROMPT.rstrip() + "\n\n当前时间：2026-04-12 14:30（周日）。"

    # 注入 mock 数据
    if "mock_tasks" in case:
        dispatcher.set_mock_tasks(case["mock_tasks"])
    if "mock_todos" in case:
        dispatcher.set_mock_todos(case["mock_todos"])

    return dispatcher, tools, prompt


def _auto_judge(case: dict, result: dict, dispatcher) -> dict:
    """自动判定：根据 case 的 expected_* 字段和实际轨迹，生成判定标签。"""
    called = result.get("called_tools", [])
    text = result.get("text", "")
    pattern = case["pattern"]

    labels = {
        "pattern": pattern,
        "auto_verdict": "unknown",
        "details": {},
    }

    if pattern == "tool_confusion":
        expected = case.get("expected_tool", "")
        confusion = case.get("confusion_target", "")
        if expected in called and confusion not in called:
            labels["auto_verdict"] = "correct"
        elif confusion in called:
            labels["auto_verdict"] = "confused"
            labels["details"]["used_wrong_tool"] = confusion
        elif not called:
            labels["auto_verdict"] = "no_tool_call"
        else:
            labels["auto_verdict"] = "other"

    elif pattern == "missing_tool":
        expected = case.get("expected_tool", "")
        if expected in called:
            labels["auto_verdict"] = "correct"
        elif called:
            labels["auto_verdict"] = "wrong_tool"
            labels["details"]["actual_tools"] = called
        else:
            labels["auto_verdict"] = "text_only"

    elif pattern == "wrong_params":
        expected_tool = case.get("expected_tool", "")
        if expected_tool not in called:
            labels["auto_verdict"] = "wrong_tool_or_missing"
        else:
            # 参数检查：从 dispatcher 的 calls 中获取
            matching = [c for c in dispatcher.calls if c.name == expected_tool]
            if not matching:
                labels["auto_verdict"] = "no_matching_call"
            else:
                params = matching[-1].params
                issues = []
                if "expected_time" in case and params.get("time") != case["expected_time"]:
                    issues.append(f"time: expected={case['expected_time']}, actual={params.get('time')}")
                if "expected_recurrence" in case and params.get("recurrence") != case["expected_recurrence"]:
                    issues.append(f"recurrence: expected={case['expected_recurrence']}, actual={params.get('recurrence')}")
                if "expected_task_id" in case and params.get("task_id") != case["expected_task_id"]:
                    issues.append(f"task_id: expected={case['expected_task_id']}, actual={params.get('task_id')}")
                if issues:
                    labels["auto_verdict"] = "param_error"
                    labels["details"]["param_issues"] = issues
                else:
                    labels["auto_verdict"] = "correct"

    elif pattern == "blind_retry":
        recovery_tools = case.get("expected_recovery_tools", [])
        used_recovery = [t for t in called if t in ("diagnose_error", "wait_and_retry")]
        if set(recovery_tools) & set(used_recovery):
            labels["auto_verdict"] = "used_recovery"
            labels["details"]["recovery_tools_used"] = used_recovery
        elif any(called.count(t) > 2 for t in called):
            # 同一工具调了 3 次以上 = 盲目重试
            labels["auto_verdict"] = "blind_retry"
            labels["details"]["repeated_tools"] = {t: called.count(t) for t in set(called) if called.count(t) > 1}
        else:
            labels["auto_verdict"] = "other"

    elif pattern == "hallucination":
        followup = case.get("followup", "")
        # 简单判定：如果有 followup 且回复中包含编造信息
        labels["auto_verdict"] = "needs_manual_review"

    elif pattern == "chain_break":
        expected_seq = case.get("expected_sequence", [])
        if not expected_seq:
            labels["auto_verdict"] = "no_expected_sequence"
        else:
            # 检查 expected_sequence 中每个工具是否都被调用了
            missing = [t for t in expected_seq if t not in called]
            if not missing:
                # 检查顺序
                positions = [called.index(t) for t in expected_seq if t in called]
                if positions == sorted(positions):
                    labels["auto_verdict"] = "correct_sequence"
                else:
                    labels["auto_verdict"] = "wrong_order"
                    labels["details"]["actual_order"] = called
            else:
                labels["auto_verdict"] = "missing_steps"
                labels["details"]["missing_tools"] = missing

    return labels


def run_single_case(case: dict, model: str, client) -> dict:
    """执行单个 case，返回完整记录。"""
    dispatcher, tools, prompt = _build_dispatcher(case)

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": case["input"]},
    ]

    # hallucination 类型有 followup
    followups = []
    if case.get("followup"):
        followups = [case["followup"]]

    t0 = time.time()
    try:
        result = agent_loop(
            client, model, messages, tools, dispatcher,
            user_followups=followups if followups else None,
            max_turns=10,
            temperature=0.1,
        )
        latency_ms = int((time.time() - t0) * 1000)
        error = None
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        result = {"called_tools": [], "tool_calls": [], "text": "", "turns": 0, "conversation": messages}
        error = str(e)

    # 自动判定
    labels = _auto_judge(case, result, dispatcher)

    # 序列化对话轨迹
    conversation = []
    for msg in result.get("conversation", messages):
        if isinstance(msg, dict):
            conversation.append(msg)
        else:
            entry = {"role": msg.role, "content": msg.content}
            if getattr(msg, "tool_calls", None):
                entry["tool_calls"] = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            conversation.append(entry)

    record = {
        "id": f"ds_{case['id']}_{model.replace('-','_')}",
        "case_id": case["id"],
        "pattern": case["pattern"],
        "subtype": case.get("subtype", ""),
        "model": model,
        "user_input": case["input"],
        "description": case.get("description", ""),
        "tools_called": result.get("called_tools", []),
        "tool_calls_detail": result.get("tool_calls", []),
        "text_reply": result.get("text", ""),
        "conversation": conversation,
        "labels": labels,
        "turns": result.get("turns", 0),
        "latency_ms": latency_ms,
        "error": error,
        "case_metadata": {
            k: v for k, v in case.items()
            if k not in ("input", "description", "mock_tasks", "mock_todos", "diagnostic_info")
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return record


def run_all(models: list[str], patterns: list[str] | None, dry_run: bool = False):
    """批量执行所有 case。"""
    # 筛选 case
    if patterns:
        cases = []
        for p in patterns:
            cases.extend(get_cases_by_pattern(p))
    else:
        cases = list(ALL_CASES)

    print(f"Cases to run: {len(cases)}")
    print(f"Models: {models}")
    print(f"Total runs: {len(cases) * len(models)}")
    print()

    for p, info in PATTERN_SUMMARY.items():
        count = len([c for c in cases if c["pattern"] == p])
        if count > 0:
            enhanced = " [+diagnose/backoff]" if info["需要增强工具集"] else ""
            print(f"  {p}: {count} cases{enhanced}")

    if dry_run:
        print("\n[DRY RUN] Case list:")
        for c in cases:
            print(f"  {c['id']:8s} | {c['pattern']:16s} | {c.get('subtype',''):24s} | {c['input'][:50]}")
        return

    print()

    # 执行
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_records = []

    for model in models:
        print(f"\n{'='*60}")
        print(f"Model: {model}")
        print(f"{'='*60}")

        # 构建 client
        os.environ["TARGET_MODEL"] = model
        # 重新加载 provider 获取正确的 client
        import importlib
        import provider as prov
        importlib.reload(prov)
        client = prov.target_client

        for i, case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {case['id']} ({case['pattern']}/{case.get('subtype','')})... ", end="", flush=True)
            record = run_single_case(case, model, client)
            verdict = record["labels"]["auto_verdict"]
            print(f"{verdict} ({record['latency_ms']}ms)")
            all_records.append(record)

    # 写入
    out_file = OUTPUT_DIR / f"generated_hard_cases_{ts}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Written {len(all_records)} records to {out_file}")

    # 统计
    from collections import Counter
    verdict_dist = Counter(r["labels"]["auto_verdict"] for r in all_records)
    pattern_dist = Counter(r["pattern"] for r in all_records)
    print(f"\nBy verdict: {dict(verdict_dist.most_common())}")
    print(f"By pattern: {dict(pattern_dist.most_common())}")


def main():
    parser = argparse.ArgumentParser(description="Run generated cases and collect trajectories")
    parser.add_argument("--model", action="append", dest="models",
                        help="Model(s) to test (repeatable). Default: TARGET_MODEL env var")
    parser.add_argument("--pattern", action="append", dest="patterns",
                        help="Only run specific pattern(s) (repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list cases, don't execute")
    args = parser.parse_args()

    models = args.models or [TARGET_MODEL]
    run_all(models, args.patterns, args.dry_run)


if __name__ == "__main__":
    main()
