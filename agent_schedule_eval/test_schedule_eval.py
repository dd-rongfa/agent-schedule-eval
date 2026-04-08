"""
定时任务场景自动化评测
=====================
测什么：大模型作为 Agent 基础，能否正确理解定时任务类指令。

两层测试：
  Layer 1 - 意图与规划（LLM judge）
    直接问大模型"你会怎么处理这条指令"，用 GEval 判断回复是否正确。
    这层不需要真实 Agent，只测模型的理解和规划能力。

  Layer 2 - 参数正确性（确定性断言）
    要求大模型输出结构化 JSON，再用普通 assert 断言关键字段。
    这层测的是"能不能输出可被系统直接消费的规划结果"。
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.models import GPTModel
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from openai import OpenAI

ENV_FILE = Path(__file__).resolve().parent.parent / "examples" / "starter_judge" / ".env"

SYSTEM_PROMPT_INTENT = """\
你是一个智能提醒 Agent。用户发来一条消息，请分析意图并说明你会采取的行动。
要求：
- 说明你会调用哪个动作（create_schedule / create_recurring / cancel_schedule / clarify / reject）
- 说明时间参数（几分钟后、具体几点、周期规则等）
- 说明提醒内容
- 如果信息不足，说明你会追问什么
请用简洁的中文说明，不要编造信息。"""

SYSTEM_PROMPT_JSON = """\
你是一个智能提醒 Agent。用户发来一条消息，请输出一个 JSON 描述你的行动计划。

JSON 格式：
{
  "action": "create_schedule | create_recurring | cancel_schedule | clarify | reject",
  "delay_minutes": null 或整数（相对时间，单位分钟）,
  "time": null 或 "HH:MM"（绝对时间）,
  "recurrence": null 或 "daily|weekly|custom",
  "interval_minutes": null 或整数（重复间隔分钟）,
  "total_count": null 或整数（重复次数）,
  "content": "提醒内容",
  "clarify_reason": null 或 "追问原因"
}

只输出 JSON，不要有任何其他文字。"""


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

judge_model = GPTModel(
    model=os.getenv("JUDGE_MODEL", "deepseek-chat"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

openai_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

intent_metric = GEval(
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
    model=judge_model,
    threshold=0.7,
)


def call_model(user_input: str, system_prompt: str) -> str:
    resp = openai_client.chat.completions.create(
        model=os.getenv("JUDGE_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


def load_cases(category: str) -> list[dict]:
    yaml_path = Path(__file__).parent / "schedule_cases.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return data.get(category, [])


# ===========================================================
# Layer 1：意图理解测试（LLM judge）
# 覆盖：简单定时、周期任务、取消、复合操作、模糊时间、无效输入
# ===========================================================

LAYER1_CASES = (
    load_cases("simple_schedule")
    + load_cases("recurring_schedule")
    + load_cases("cancel_schedule")
    + load_cases("fuzzy_time")
    + load_cases("invalid_input")
)


def make_expected_desc(case: dict) -> str:
    """把 yaml 字段拼成人类可读的期望描述，供 GEval 对比用。"""
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


@pytest.mark.parametrize(
    "case",
    LAYER1_CASES,
    ids=[c["input"][:20] for c in LAYER1_CASES],
)
def test_intent_understanding(case: dict) -> None:
    """Layer 1：用 GEval 判断模型是否正确理解了定时任务意图。"""
    user_input = case["input"]
    actual = call_model(user_input, SYSTEM_PROMPT_INTENT)
    expected_desc = make_expected_desc(case)

    test_case = LLMTestCase(
        input=user_input,
        actual_output=actual,
        expected_output=expected_desc,
        context=["用户正在使用一个智能提醒 Agent"],
        tags=["schedule", case.get("difficulty", "medium")],
    )
    assert_test(test_case, [intent_metric])


# ===========================================================
# Layer 2：结构化输出正确性测试（确定性断言）
# 只测有明确预期值的用例，不依赖 LLM judge
# ===========================================================

LAYER2_CASES = [
    c for c in load_cases("simple_schedule")
    if "expected_delay_minutes" in c or "expected_time" in c
]


@pytest.mark.parametrize(
    "case",
    LAYER2_CASES,
    ids=[c["input"][:20] for c in LAYER2_CASES],
)
def test_structured_output(case: dict) -> None:
    """Layer 2：断言模型输出的 JSON 关键字段是否正确。"""
    user_input = case["input"]
    raw = call_model(user_input, SYSTEM_PROMPT_JSON)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        pytest.fail(f"模型没有输出合法 JSON:\n{raw}")

    action = parsed.get("action", "")
    expected_action = case.get("expected_action", "create_schedule")
    assert action == expected_action, (
        f"action 不对: 期望 {expected_action!r}, 实际 {action!r}\n完整输出: {raw}"
    )

    if "expected_delay_minutes" in case:
        actual_delay = parsed.get("delay_minutes")
        expected_delay = case["expected_delay_minutes"]
        assert actual_delay == expected_delay, (
            f"delay_minutes 不对: 期望 {expected_delay}, 实际 {actual_delay}\n完整输出: {raw}"
        )

    if "expected_time" in case:
        actual_time = parsed.get("time", "")
        expected_time = case["expected_time"]
        assert actual_time == expected_time, (
            f"time 不对: 期望 {expected_time!r}, 实际 {actual_time!r}\n完整输出: {raw}"
        )
