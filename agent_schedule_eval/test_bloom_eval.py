"""
Agent 定时任务能力评测 — Bloom's Taxonomy 分层版
=================================================
理论依据：
  - Bloom's Taxonomy (Anderson & Krathwohl, 2001)
  - "LLMs meet Bloom's Taxonomy" (Huber & Niklaus, COLING 2025)

六层认知能力：
  L1 Remember  → 识别意图类型
  L2 Understand → 理解模糊/口语化时间
  L3 Apply      → 输出结构化参数
  L4 Analyze    → 拆解复合指令
  L5 Evaluate   → 判断是否执行/拒绝/追问
  L6 Create     → 处理开放式复杂场景

测试结果自动写入 results.jsonl，每条记录包含：
  - 时间戳、Bloom 层级、输入、输出、期望、通过/失败、分数、原因
"""

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.models import GPTModel
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from openai import OpenAI

# ── 路径与环境 ──────────────────────────────────────

ENV_FILE = Path(__file__).resolve().parent.parent / "examples" / "starter_judge" / ".env"
YAML_FILE = Path(__file__).parent / "schedule_cases_bloom.yaml"
DEFAULT_RESULTS_FILE = Path(__file__).parent / "results" / "results.jsonl"

SYSTEM_PROMPT_INTENT = """\
你是一个智能提醒 Agent。用户发来一条消息，请分析意图并说明你会采取的行动。
要求：
1. 首先判断信息是否充分，选择唯一动作：create_schedule / create_recurring / cancel_schedule / clarify / reject
2. 动作之间互斥——如果你选择 clarify（追问），则不要声明会调用 create_schedule 等执行类动作；反之亦然
3. 仅当关键信息（时间或内容）严重缺失、无法合理推断时才选 clarify；如果用户提供了足够信息，应直接选择执行类动作
4. 如果选择执行类动作，说明时间参数（几分钟后、具体几点、周期规则等）和提醒内容
5. 如果选择 clarify，只说明你会追问什么，以及追问的原因
6. 如果选择 reject，说明拒绝原因
请用简洁的中文说明，先给出你选择的动作，再给出相应说明。不要编造信息。"""

SYSTEM_PROMPT_JSON = """\
你是一个智能提醒 Agent。用户发来一条消息，请输出一个 JSON 描述你的行动计划。

JSON 格式：
{
  "action": "create_schedule | create_recurring | cancel_schedule | clarify | reject",
  "delay_minutes": null 或整数,
  "time": null 或 "HH:MM",
  "recurrence": null 或 "daily|weekly|custom",
  "interval_minutes": null 或整数,
  "total_count": null 或整数,
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


def resolve_api_key(prefix: str | None, explicit_key: str | None, fallback_key: str) -> str | None:
    if explicit_key:
        return explicit_key
    if prefix:
        prefixed_key = os.getenv(f"{prefix}_API_KEY")
        if prefixed_key:
            return prefixed_key
    return os.getenv(fallback_key)


def resolve_base_url(prefix: str | None, explicit_url: str | None, fallback_url_key: str, fallback_url: str) -> str:
    if explicit_url:
        return explicit_url
    if prefix:
        prefixed_url = os.getenv(f"{prefix}_BASE_URL")
        if prefixed_url:
            return prefixed_url
    return os.getenv(fallback_url_key, fallback_url)


JUDGE_MODEL_NAME = os.getenv("JUDGE_MODEL", "deepseek-chat")
JUDGE_ENV_PREFIX = os.getenv("JUDGE_ENV_PREFIX")
JUDGE_API_KEY = resolve_api_key(
    prefix=JUDGE_ENV_PREFIX,
    explicit_key=os.getenv("JUDGE_API_KEY"),
    fallback_key="DEEPSEEK_API_KEY",
)
JUDGE_BASE_URL = resolve_base_url(
    prefix=JUDGE_ENV_PREFIX,
    explicit_url=os.getenv("JUDGE_BASE_URL"),
    fallback_url_key="DEEPSEEK_BASE_URL",
    fallback_url="https://api.deepseek.com/v1",
)

TARGET_MODEL_NAME = os.getenv("TARGET_MODEL", JUDGE_MODEL_NAME)
TARGET_ENV_PREFIX = os.getenv("TARGET_ENV_PREFIX")
TARGET_API_KEY = resolve_api_key(
    prefix=TARGET_ENV_PREFIX,
    explicit_key=os.getenv("TARGET_API_KEY"),
    fallback_key="DEEPSEEK_API_KEY",
)
TARGET_BASE_URL = resolve_base_url(
    prefix=TARGET_ENV_PREFIX,
    explicit_url=os.getenv("TARGET_BASE_URL"),
    fallback_url_key="DEEPSEEK_BASE_URL",
    fallback_url="https://api.deepseek.com/v1",
)

RESULTS_FILE = Path(os.getenv("RESULTS_FILE", str(DEFAULT_RESULTS_FILE)))

judge_model = GPTModel(
    model=JUDGE_MODEL_NAME,
    api_key=JUDGE_API_KEY,
    base_url=JUDGE_BASE_URL,
)

openai_client = OpenAI(
    api_key=TARGET_API_KEY,
    base_url=TARGET_BASE_URL,
)


# ── JSONL 记录器 ────────────────────────────────────

def record_result(entry: dict) -> None:
    """追加一条 JSON 记录到 results.jsonl"""
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    entry["target_model"] = TARGET_MODEL_NAME
    entry["target_base_url"] = TARGET_BASE_URL
    entry["judge_model"] = JUDGE_MODEL_NAME
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def score_with_retries(test_case: LLMTestCase, metric: GEval, runs: int = 1) -> tuple[bool, float | None, str, list[float]]:
    """Run the same GEval metric multiple times and return averaged score plus raw scores."""
    scores: list[float] = []
    last_reason = ""

    for _ in range(max(1, runs)):
        metric.measure(test_case)
        if metric.score is not None:
            scores.append(metric.score)
        if metric.reason:
            last_reason = metric.reason

    avg_score = round(statistics.mean(scores), 4) if scores else None
    threshold = getattr(metric, "threshold", None)
    passed = True
    if threshold is not None and avg_score is not None:
        passed = avg_score >= threshold
    return passed, avg_score, last_reason, scores


# ── 模型调用 ────────────────────────────────────────

def call_model(user_input: str, system_prompt: str) -> str:
    resp = openai_client.chat.completions.create(
        model=TARGET_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


# ── 数据加载 ────────────────────────────────────────

def load_bloom_cases(level_key: str) -> list[dict]:
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))
    return data.get(level_key, [])


def make_expected_desc(case: dict) -> str:
    parts = []
    action = case.get("expected_action") or case.get("expected_actions")
    if action:
        parts.append(f"期望动作: {action}")
    for k in ("expected_delay_minutes", "expected_time", "expected_interval_minutes",
              "expected_total_count", "expected_recurrence", "expected_final_delay_minutes",
              "expected_new_time", "expected_time_range", "expected_days"):
        if k in case:
            parts.append(f"{k}: {case[k]}")
    if "note" in case:
        parts.append(f"备注: {case['note']}")
    if "test_goal" in case:
        parts.append(f"测试目标: {case['test_goal']}")
    return "；".join(parts) if parts else "正确识别用户意图"


# ── GEval 指标（每层可复用） ────────────────────────

def make_intent_metric(bloom_level: int) -> GEval:
    level_names = {1: "Remember", 2: "Understand", 3: "Apply",
                   4: "Analyze", 5: "Evaluate", 6: "Create"}
    return GEval(
        name=f"L{bloom_level} {level_names.get(bloom_level, '')} Intent",
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


# 缓存每层级的 metric 对象
_metrics: dict[int, GEval] = {}


def get_metric(bloom_level: int) -> GEval:
    if bloom_level not in _metrics:
        _metrics[bloom_level] = make_intent_metric(bloom_level)
    return _metrics[bloom_level]


# ── 收集所有自动化用例 ──────────────────────────────

BLOOM_LEVELS = [
    ("L1_remember", 1),
    ("L2_understand", 2),
    ("L3_apply", 3),
    ("L4_analyze", 4),
    ("L5_evaluate", 5),
    ("L6_create", 6),
]

ALL_CASES = []
for level_key, bloom_num in BLOOM_LEVELS:
    for case in load_bloom_cases(level_key):
        case["_bloom_level"] = bloom_num
        case["_level_key"] = level_key
        ALL_CASES.append(case)


# ===========================================================
# Layer 1：意图理解 (GEval)  — 覆盖 L1 ~ L6
# ===========================================================

@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=[f"L{c['_bloom_level']}-{c['input'][:15]}" for c in ALL_CASES],
)
def test_bloom_intent(case: dict) -> None:
    """Bloom 分层意图理解测试，结果写入 JSONL。"""
    bloom_level = case["_bloom_level"]
    user_input = case["input"]
    t0 = time.time()
    actual = call_model(user_input, SYSTEM_PROMPT_INTENT)
    latency_ms = int((time.time() - t0) * 1000)

    expected_desc = make_expected_desc(case)
    metric = get_metric(bloom_level)

    test_case = LLMTestCase(
        input=user_input,
        actual_output=actual,
        expected_output=expected_desc,
        context=["用户正在使用一个智能提醒 Agent"],
        tags=["bloom", case.get("bloom_tag", ""), case.get("difficulty", "medium")],
    )

    reliability_runs = int(os.getenv("JUDGE_REPEAT_RUNS", "1"))
    passed, score, reason, run_scores = score_with_retries(
        test_case,
        metric,
        runs=reliability_runs,
    )

    record_result({
        "test": "bloom_intent",
        "bloom_level": bloom_level,
        "bloom_tag": case.get("bloom_tag", ""),
        "difficulty": case.get("difficulty", ""),
        "time_complexity": case.get("time_complexity", ""),
        "intent_clarity": case.get("intent_clarity", ""),
        "action_count": case.get("action_count", ""),
        "info_completeness": case.get("info_completeness", ""),
        "context_dependency": case.get("context_dependency", ""),
        "test_goal": case.get("test_goal", ""),
        "input": user_input,
        "actual_output": actual,
        "expected": expected_desc,
        "score": score,
        "judge_runs": reliability_runs,
        "judge_scores": run_scores,
        "passed": passed,
        "reason": reason,
        "latency_ms": latency_ms,
    })

    if not passed:
        pytest.fail(f"Score {score} < threshold | {reason}")


# ===========================================================
# Layer 2：结构化输出 (JSON assert) — 仅 L3 Apply 层有精确预期值
# ===========================================================

LAYER2_CASES = [
    c for c in load_bloom_cases("L3_apply")
    if "expected_delay_minutes" in c or "expected_time" in c
]


@pytest.mark.parametrize(
    "case",
    LAYER2_CASES,
    ids=[f"JSON-{c['input'][:15]}" for c in LAYER2_CASES],
)
def test_structured_output(case: dict) -> None:
    """Layer 2：JSON 结构化输出断言，结果写入 JSONL。"""
    user_input = case["input"]
    t0 = time.time()
    raw = call_model(user_input, SYSTEM_PROMPT_JSON)
    latency_ms = int((time.time() - t0) * 1000)

    passed = True
    fail_reason = ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        passed = False
        fail_reason = f"模型没有输出合法 JSON: {raw[:200]}"
        record_result({
            "test": "structured_output",
            "bloom_level": 3,
            "bloom_tag": "apply",
            "input": user_input,
            "actual_output": raw,
            "expected": str(case),
            "passed": False,
            "reason": fail_reason,
            "latency_ms": latency_ms,
        })
        pytest.fail(fail_reason)
        return

    checks = []

    action = parsed.get("action", "")
    expected_action = case.get("expected_action", "create_schedule")
    if action != expected_action:
        checks.append(f"action: 期望 {expected_action!r}, 实际 {action!r}")

    if "expected_delay_minutes" in case:
        actual_delay = parsed.get("delay_minutes")
        if actual_delay != case["expected_delay_minutes"]:
            checks.append(
                f"delay_minutes: 期望 {case['expected_delay_minutes']}, 实际 {actual_delay}"
            )

    if "expected_time" in case:
        actual_time = parsed.get("time", "")
        if actual_time != case["expected_time"]:
            checks.append(
                f"time: 期望 {case['expected_time']!r}, 实际 {actual_time!r}"
            )

    if checks:
        passed = False
        fail_reason = " | ".join(checks)

    record_result({
        "test": "structured_output",
        "bloom_level": 3,
        "bloom_tag": "apply",
        "input": user_input,
        "actual_output": raw,
        "expected": str(case),
        "passed": passed,
        "reason": fail_reason if fail_reason else "all fields correct",
        "latency_ms": latency_ms,
    })

    if not passed:
        pytest.fail(f"JSON 字段不匹配: {fail_reason}\n完整输出: {raw}")
