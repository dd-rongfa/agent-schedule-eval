"""
Phase 4 — Skill Loading 评测
================================
研究问题：在 System Prompt 里注入"技能说明（Skill Card）"
是否能显著提升模型的 Function Calling 成功率？

实验设计（2×2 变体）：
  Group A: 裸 Agent，无技能注入（基线，复现 Phase 3）
  Group B: 注入正确技能（schedule_skill.md）
  Group C: 注入错误技能（email_skill.md，不相关领域）
  Group D: 注入 3 个技能（1 正确 + 2 噪音），模拟"技能库"场景

评测用例：与 Phase 3 相同（L1~L4，过滤 clarify/reject）
断言方式：与 Phase 3 相同（确定性 tool_call 断言，无 Judge）

结果写入：results_skill_loading.jsonl
  字段新增：group（A/B/C/D）、skill_files（注入的文件列表）

用法示例：
  # 跑所有 group，使用 DeepSeek
  pytest test_skill_loading.py -v

  # 只跑 Group B 和 C
  pytest test_skill_loading.py -v -k "group_B or group_C"

  # 换 MiMo 模型
  TARGET_MODEL=mimo-v2-pro TARGET_ENV_PREFIX=MiMo \\
  RESULTS_FILE=results_skill_loading_mimo.jsonl \\
  pytest test_skill_loading.py -v
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
SKILLS_DIR = Path(__file__).parent / "skills"
RESULTS_FILE = Path(os.getenv(
    "RESULTS_FILE",
    str(Path(__file__).parent / "results" / "results_skill_loading.jsonl"),
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

# ── OpenAI Tools 定义（与 Phase 3 完全一致）──────────

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

BASE_SYSTEM = (
    "你是一个智能提醒 Agent。请根据用户的请求调用合适的工具来创建、"
    "取消或管理定时提醒。如果信息不足无法创建提醒，直接用文字回复追问用户。"
)

# ── Skill Loading 工具函数 ────────────────────────────

def load_skill(path: Path) -> str:
    """读取技能文件内容。"""
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(skill_paths: list[Path]) -> str:
    """将技能说明注入 system prompt。"""
    if not skill_paths:
        return BASE_SYSTEM
    blocks = "\n\n".join(
        f"<skill name=\"{p.stem}\">\n{load_skill(p)}\n</skill>"
        for p in skill_paths
    )
    return (
        f"{BASE_SYSTEM}\n\n"
        f"以下是你当前加载的技能说明，请优先参考这些说明来选择工具和填写参数：\n\n"
        f"{blocks}"
    )


# ── 实验组定义 ────────────────────────────────────────

GROUPS: dict[str, list[Path]] = {
    "A_no_skill":     [],
    "B_correct_skill": [SKILLS_DIR / "schedule_skill.md"],
    "C_wrong_skill":  [SKILLS_DIR / "email_skill.md"],
    "D_multi_skill":  [
        SKILLS_DIR / "schedule_skill.md",
        SKILLS_DIR / "email_skill.md",
        SKILLS_DIR / "note_skill.md",
    ],
    # E 组：正确 skill + 矛盾 skill 同时注入
    # conflict_skill 要求"时间不明必须追问"，与 schedule_skill v3 的默认值映射直接冲突
    "E_conflict_skill": [
        SKILLS_DIR / "schedule_skill.md",
        SKILLS_DIR / "conflict_skill.md",
    ],
}

# ── 调用封装 ──────────────────────────────────────────

def call_with_tools(user_input: str, system_prompt: str) -> tuple[dict, FakeScheduler]:
    """调用模型，返回结构化结果与 scheduler 实例。"""
    scheduler = FakeScheduler()

    resp = client.chat.completions.create(
        model=TARGET_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
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
    }, scheduler


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


TOOL_CALL_CASES: list[dict] = []

for _level_key, _bloom_num in [
    ("L1_remember", 1), ("L2_understand", 2), ("L3_apply", 3), ("L4_analyze", 4),
]:
    for _case in load_cases(_level_key):
        _action = _case.get("expected_action")
        _actions = _case.get("expected_actions")
        if _action and _action in ("clarify", "reject", "reject_or_clarify", "clarify_or_create"):
            continue
        if _action or _actions:
            _case = dict(_case)  # 浅拷贝，避免污染原数据
            _case["_bloom_level"] = _bloom_num
            _case["_level_key"] = _level_key
            TOOL_CALL_CASES.append(_case)


# ── 参数化：(group_name, case) ─────────────────────

_PARAMS = [
    (group_name, case)
    for group_name in GROUPS
    for case in TOOL_CALL_CASES
]

_IDS = [
    f"{gname}-L{case['_bloom_level']}-{case['input'][:12]}"
    for gname, case in _PARAMS
]


# ── 测试主体 ─────────────────────────────────────────

@pytest.mark.parametrize("group_name,case", _PARAMS, ids=_IDS)
def test_skill_loading(group_name: str, case: dict) -> None:
    """Phase 4: 技能注入对 Function Calling 成功率的影响。"""

    skill_paths = GROUPS[group_name]
    system_prompt = build_system_prompt(skill_paths)
    user_input = case["input"]
    bloom_level = case["_bloom_level"]

    t0 = time.time()
    result, scheduler = call_with_tools(user_input, system_prompt)
    latency_ms = int((time.time() - t0) * 1000)

    called = result["called_tools"]
    tool_calls = result["tool_calls"]
    text_reply = result["text"]

    errors: list[str] = []

    # ---- 单 action 断言 ----
    expected_action = case.get("expected_action")
    expected_actions = case.get("expected_actions")

    if expected_action:
        if not called:
            errors.append(
                f"期望调用 {expected_action}，但模型没有发起任何 tool_call"
                f"（回复: {text_reply[:100]}）"
            )
        elif expected_action not in called:
            errors.append(f"期望调用 {expected_action}，实际调用了 {called}")

    # ---- 多 action 断言 ----
    if expected_actions:
        for ea in expected_actions:
            if ea not in called:
                errors.append(f"期望调用 {ea}，但未出现在 {called}")
        if len(called) < len(expected_actions):
            errors.append(
                f"期望 {len(expected_actions)} 次工具调用，实际 {len(called)} 次"
            )

    # ---- 参数断言（L3 精确值）----
    if expected_action and called and expected_action in called:
        matching = [tc for tc in tool_calls if tc["name"] == expected_action]
        if matching:
            args = matching[-1]["args"]

            if "expected_delay_minutes" in case:
                actual = args.get("delay_minutes")
                if actual != case["expected_delay_minutes"]:
                    errors.append(
                        f"delay_minutes: 期望 {case['expected_delay_minutes']}, 实际 {actual}"
                    )

            if "expected_time" in case:
                actual = args.get("time", "")
                if actual != case["expected_time"]:
                    errors.append(
                        f"time: 期望 {case['expected_time']!r}, 实际 {actual!r}"
                    )

            if "expected_recurrence" in case:
                actual = args.get("recurrence", "")
                if actual != case["expected_recurrence"]:
                    errors.append(
                        f"recurrence: 期望 {case['expected_recurrence']!r}, 实际 {actual!r}"
                    )

            if "expected_days" in case:
                actual = args.get("days", [])
                expected_days_lower = [d.lower() for d in case["expected_days"]]
                actual_lower = [d.lower() for d in (actual or [])]
                if set(actual_lower) != set(expected_days_lower):
                    errors.append(
                        f"days: 期望 {expected_days_lower}, 实际 {actual_lower}"
                    )

    # ---- L4 最终值断言 ----
    if "expected_final_delay_minutes" in case and called:
        last = scheduler.last_call()
        if last:
            actual = last.params.get("delay_minutes")
            if actual != case["expected_final_delay_minutes"]:
                errors.append(
                    f"final delay_minutes: 期望 {case['expected_final_delay_minutes']}, 实际 {actual}"
                )

    passed = len(errors) == 0

    record({
        "test": "skill_loading",
        "group": group_name,
        "skill_files": [p.name for p in skill_paths],
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
