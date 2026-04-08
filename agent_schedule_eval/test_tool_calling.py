"""
Phase 3 — Function Calling 评测
================================
让模型真正发起 tool_calls，用 FakeScheduler 拦截并断言：
  - 调了哪个工具？
  - 参数是否正确？

与 test_bloom_eval.py (Phase 2) 的区别：
  Phase 2: 模型输出自然语言描述意图 → LLM Judge 打分
  Phase 3: 模型输出 tool_calls → 确定性断言（无 Judge 参与）

仅测试 L1-L3 + 部分 L4 用例（有明确 expected_action 的）。
L5/L6 多为 clarify/reject 场景，tool_calls 断言无意义。
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from openai import OpenAI

from mock_tools import FakeScheduler

# ── 路径与环境 ──────────────────────────────────────

ENV_FILE = Path(__file__).resolve().parent.parent / "examples" / "starter_judge" / ".env"
YAML_FILE = Path(__file__).parent / "schedule_cases_bloom.yaml"
RESULTS_FILE = Path(os.getenv(
    "RESULTS_FILE",
    str(Path(__file__).parent / "results" / "results_tool_calling.jsonl"),
))


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()


def _resolve_key(prefix, explicit, fallback):
    if explicit:
        return explicit
    if prefix:
        v = os.getenv(f"{prefix}_API_KEY")
        if v:
            return v
    return os.getenv(fallback)


def _resolve_url(prefix, explicit, fallback_key, default):
    if explicit:
        return explicit
    if prefix:
        v = os.getenv(f"{prefix}_BASE_URL")
        if v:
            return v
    return os.getenv(fallback_key, default)


TARGET_MODEL = os.getenv("TARGET_MODEL", "deepseek-chat")
_PREFIX = os.getenv("TARGET_ENV_PREFIX")
TARGET_API_KEY = _resolve_key(_PREFIX, os.getenv("TARGET_API_KEY"), "DEEPSEEK_API_KEY")
TARGET_BASE_URL = _resolve_url(_PREFIX, os.getenv("TARGET_BASE_URL"), "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

client = OpenAI(api_key=TARGET_API_KEY, base_url=TARGET_BASE_URL)
scheduler = FakeScheduler()

# ── OpenAI Tools 定义 ──────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_schedule",
            "description": "创建一个一次性定时提醒",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "提醒内容"},
                    "delay_minutes": {"type": "integer", "description": "多少分钟后提醒（与 time 二选一）"},
                    "time": {"type": "string", "description": "绝对时间 HH:MM（与 delay_minutes 二选一）"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_schedule",
            "description": "取消一个已创建的提醒",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "要取消的任务 ID"},
                    "description": {"type": "string", "description": "要取消的任务描述（模糊匹配）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_recurring",
            "description": "创建一个周期性定时提醒",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "提醒内容"},
                    "recurrence": {"type": "string", "enum": ["daily", "weekly", "custom"], "description": "周期类型"},
                    "time": {"type": "string", "description": "每次提醒的时间 HH:MM"},
                    "days": {"type": "array", "items": {"type": "string"}, "description": "周几提醒（weekly 时使用）"},
                    "interval_minutes": {"type": "integer", "description": "每隔多少分钟提醒一次（custom 时使用）"},
                    "total_count": {"type": "integer", "description": "总共提醒几次"},
                },
                "required": ["content"],
            },
        },
    },
]

SYSTEM_PROMPT = "你是一个智能提醒 Agent。请根据用户的请求调用合适的工具来创建、取消或管理定时提醒。如果信息不足无法创建提醒，直接用文字回复追问用户。"


# ── 模型调用（带 tool_calls） ───────────────────────

def call_with_tools(user_input: str) -> dict:
    """调用模型并返回结构化结果。"""
    scheduler.reset()

    resp = client.chat.completions.create(
        model=TARGET_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        tools=TOOLS,
        temperature=0.1,
    )

    msg = resp.choices[0].message
    tool_calls_raw = []

    if msg.tool_calls:
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {"_raw": tc.function.arguments}

            tool_calls_raw.append({"name": fn_name, "args": fn_args})

            # 转发到 FakeScheduler
            handler = getattr(scheduler, fn_name, None)
            if handler:
                handler(**fn_args)

    return {
        "text": msg.content or "",
        "tool_calls": tool_calls_raw,
        "called_tools": scheduler.called_tools(),
        "scheduler_calls": [
            {"name": c.name, "params": c.params} for c in scheduler.calls
        ],
    }


# ── JSONL 记录 ──────────────────────────────────────

def record(entry: dict) -> None:
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    entry["target_model"] = TARGET_MODEL
    entry["target_base_url"] = TARGET_BASE_URL
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 数据加载 ────────────────────────────────────────

def load_cases(level_key: str) -> list[dict]:
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))
    return data.get(level_key, [])


# ── 收集可做 tool-call 断言的用例 ───────────────────
# 只取有明确 expected_action 且不是 clarify/reject 的用例

TOOL_CALL_CASES = []

for level_key, bloom_num in [
    ("L1_remember", 1), ("L2_understand", 2), ("L3_apply", 3), ("L4_analyze", 4),
]:
    for case in load_cases(level_key):
        action = case.get("expected_action")
        actions = case.get("expected_actions")
        # 跳过 clarify / reject 类
        if action and action in ("clarify", "reject", "reject_or_clarify", "clarify_or_create"):
            continue
        if action or actions:
            case["_bloom_level"] = bloom_num
            case["_level_key"] = level_key
            TOOL_CALL_CASES.append(case)


# ── 测试 ────────────────────────────────────────────

@pytest.mark.parametrize(
    "case",
    TOOL_CALL_CASES,
    ids=[f"TC-L{c['_bloom_level']}-{c['input'][:15]}" for c in TOOL_CALL_CASES],
)
def test_tool_calling(case: dict) -> None:
    """Phase 3: 确定性工具调用断言。"""
    user_input = case["input"]
    bloom_level = case["_bloom_level"]

    t0 = time.time()
    result = call_with_tools(user_input)
    latency_ms = int((time.time() - t0) * 1000)

    called = result["called_tools"]
    tool_calls = result["tool_calls"]
    text_reply = result["text"]

    errors = []

    # ---- 单 action 断言 ----
    expected_action = case.get("expected_action")
    expected_actions = case.get("expected_actions")

    if expected_action:
        if not called:
            errors.append(f"期望调用 {expected_action}，但模型没有发起任何 tool_call（回复: {text_reply[:100]}）")
        elif expected_action not in called:
            errors.append(f"期望调用 {expected_action}，实际调用了 {called}")

    # ---- 多 action 断言 ----
    if expected_actions:
        for ea in expected_actions:
            if ea not in called:
                errors.append(f"期望调用 {ea}，但未出现在 {called}")
        if len(called) < len(expected_actions):
            errors.append(f"期望 {len(expected_actions)} 次工具调用，实际 {len(called)} 次")

    # ---- 参数断言（L3 精确值）----
    if expected_action and called and expected_action in called:
        matching = [tc for tc in tool_calls if tc["name"] == expected_action]
        if matching:
            args = matching[-1]["args"]  # 取最后一次（多次推翻场景）

            if "expected_delay_minutes" in case:
                actual = args.get("delay_minutes")
                if actual != case["expected_delay_minutes"]:
                    errors.append(f"delay_minutes: 期望 {case['expected_delay_minutes']}, 实际 {actual}")

            if "expected_time" in case:
                actual = args.get("time", "")
                if actual != case["expected_time"]:
                    errors.append(f"time: 期望 {case['expected_time']!r}, 实际 {actual!r}")

            if "expected_recurrence" in case:
                actual = args.get("recurrence", "")
                if actual != case["expected_recurrence"]:
                    errors.append(f"recurrence: 期望 {case['expected_recurrence']!r}, 实际 {actual!r}")

            if "expected_days" in case:
                actual = args.get("days", [])
                expected_days_lower = [d.lower() for d in case["expected_days"]]
                actual_lower = [d.lower() for d in (actual or [])]
                if set(actual_lower) != set(expected_days_lower):
                    errors.append(f"days: 期望 {expected_days_lower}, 实际 {actual_lower}")

    # ---- L4 最终值断言 ----
    if "expected_final_delay_minutes" in case and called:
        last = scheduler.last_call()
        if last:
            actual = last.params.get("delay_minutes")
            if actual != case["expected_final_delay_minutes"]:
                errors.append(f"final delay_minutes: 期望 {case['expected_final_delay_minutes']}, 实际 {actual}")

    passed = len(errors) == 0

    record({
        "test": "tool_calling",
        "bloom_level": bloom_level,
        "bloom_tag": case.get("bloom_tag", ""),
        "input": user_input,
        "tool_calls": tool_calls,
        "called_tools": called,
        "text_reply": text_reply,
        "expected_action": expected_action,
        "expected_actions": expected_actions,
        "passed": passed,
        "errors": errors,
        "latency_ms": latency_ms,
    })

    if not passed:
        pytest.fail(" | ".join(errors))
