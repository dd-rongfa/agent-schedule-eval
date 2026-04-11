"""
工具调用评测（v2 — 一次用户指令，多次工具调用）
===============================================
测什么：让模型通过 OpenAI tool_calls 真正发起工具调用，
        用 FakeScheduler 拦截并做确定性断言：
          - 调了哪个工具？顺序是否正确？
          - 参数是否精确？

与 v1 的区别：
  v1: 纯文本评测（模型输出自然语言 → LLM Judge / JSON 断言）
  v2: 真实 tool_calls → agent_loop 多轮调用 → 确定性断言（无 Judge）

用例来自 schedule_cases.yaml 中有明确 expected_action(s) 的条目。
boundary/complex 多为 clarify/reject/suggest 场景，tool_calls 断言无意义，故跳过。
clarify 类 case 已有 user_followups，会作为多轮 case 参与测试。

并发策略：
  ThreadPoolExecutor 并发调 API（I/O 密集型），单进程内多线程。
  每个线程创建独立 FakeScheduler（线程安全）。
  module fixture 预跑所有 case，parametrize 只做结果断言。

数据存档策略：
  每次运行写入 results/{model}/run_{timestamp}.jsonl，不覆盖历史数据。
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ── 路径设置（不依赖 conftest.py） ──────────────────
_HERE = Path(__file__).resolve().parent          # eval/
_PROJECT = _HERE.parent                          # v2_tool_eval/
sys.path.insert(0, str(_HERE))                   # agent_loop, mock_tools
sys.path.insert(0, str(_PROJECT.parent))         # provider

import pytest
import yaml
from agent_loop import agent_loop
from mock_tools import FakeScheduler, ToolDispatcher
from provider import target_client, TARGET_MODEL

# ── 结果记录 ─────────────────────────────────────
RESULTS_DIR = _PROJECT / "results"
_model_tag = TARGET_MODEL.replace("/", "_")
_model_dir = RESULTS_DIR / _model_tag
_model_dir.mkdir(parents=True, exist_ok=True)
_run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_run_file = _model_dir / f"run_{_run_ts}.jsonl"
_write_lock = threading.Lock()

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))

# ── OpenAI Tools 定义 ──────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前系统时间",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_schedule",
            "description": "创建一个一次性定时提醒",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "提醒内容"},
                    "delay_minutes": {"type": "integer", "description": "多少分钟后提醒（与 time/date 组合二选一）"},
                    "time": {"type": "string", "description": "提醒时间 HH:MM"},
                    "date": {"type": "string", "description": "提醒日期 YYYY-MM-DD（不填则为今天）"},
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
    {
        "type": "function",
        "function": {
            "name": "list_schedules",
            "description": "查询已创建的提醒列表，包含每条提醒的当前状态（pending=未触发, triggered=已触发, completed=已完成, expired=已过期, cancelled=已取消）",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "按日期筛选 YYYY-MM-DD（可选）"},
                    "keyword": {"type": "string", "description": "按关键词模糊搜索（可选）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_schedule",
            "description": "更新一个已有提醒的状态或内容。常见用法：将已触发的提醒标记为 completed（如用户说‘药吃过了’）",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "提醒 ID"},
                    "status": {"type": "string", "enum": ["pending", "triggered", "completed", "cancelled", "expired"], "description": "新状态"},
                    "content": {"type": "string", "description": "更新提醒内容（可选）"},
                    "time": {"type": "string", "description": "更新提醒时间 HH:MM（可选）"},
                },
                "required": ["task_id"],
            },
        },
    },
    # ── 待办事项工具 ──
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "创建一个待办事项（非定时提醒，只记录要做的事）",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "待办内容"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级"},
                    "due_date": {"type": "string", "description": "截止日期 YYYY-MM-DD（可选）"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_todo",
            "description": "将一个待办事项标记为已完成",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "待办 ID"},
                    "description": {"type": "string", "description": "待办描述（模糊匹配）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "查询待办事项列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "completed"], "description": "按状态筛选"},
                    "keyword": {"type": "string", "description": "按关键词搜索"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "删除一个待办事项",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "待办 ID"},
                    "description": {"type": "string", "description": "待办描述（模糊匹配）"},
                },
            },
        },
    },
    # ── 媒体播放工具 ──
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "播放指定的媒体内容（电视剧、电影、音乐等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "媒体标题"},
                    "episode": {"type": "integer", "description": "集数（电视剧时使用）"},
                    "resume": {"type": "boolean", "description": "是否从上次位置继续播放"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_media",
            "description": "暂停当前播放的媒体",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_play_history",
            "description": "获取媒体播放历史（最近看过的电视剧、电影等及播放进度）",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_media_library",
            "description": "浏览媒体库中的可播放内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "按关键词搜索"},
                    "type": {"type": "string", "enum": ["tv", "movie", "music"], "description": "媒体类型"},
                },
            },
        },
    },
    # ── 应用操作工具 ──
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开指定的应用程序",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名称"},
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apps",
            "description": "列出可用的应用程序",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    # ── 系统操作工具（借鉴 voiceinput agent_tools.py）──
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行系统命令。可用于打开文件夹(start D:\\)、启动程序(start \"\" \"path\")等系统级操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_program",
            "description": "查找程序的安装路径。在打开未知应用前，先用此工具查找其 .exe 路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "应用名称或关键词（如 'weixin', '抖音'）"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_window",
            "description": "控制已打开的窗口（最小化、最大化、关闭等）。需要提供窗口标题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["minimize", "maximize", "restore", "close", "hide", "show"],
                        "description": "对窗口执行的操作",
                    },
                    "window_title": {"type": "string", "description": "窗口标题（部分匹配即可）"},
                },
                "required": ["action", "window_title"],
            },
        },
    },
    # ── 后台任务状态查询工具 ──
    {
        "type": "function",
        "function": {
            "name": "check_task_status",
            "description": "查询后台运行中的任务状态。返回任务进度、已运行时间、日志等信息。不传 task_id 则列出所有运行中的任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID（可选，不填则列出所有）"},
                },
            },
        },
    },
]

SYSTEM_PROMPT = """\
你是一个运行在 Windows 系统上的智能个人助手，可以管理日程提醒、待办事项、媒体播放、应用操作和系统命令。

可用工具：
- 日程提醒：create_schedule, cancel_schedule, create_recurring, list_schedules, update_schedule, get_current_time
- 待办事项：create_todo, complete_todo, list_todos, delete_todo
- 媒体播放：play_media, pause_media, get_play_history, list_media_library
- 应用操作：open_app, list_apps, find_program
- 系统操作：bash（执行命令，如打开文件夹 start D:\\）, control_window（控制窗口）
- 任务监控：check_task_status（查询后台任务运行进度）

关键行为准则：
- 你管理着用户的完整提醒列表和待办列表，可以随时查看。
- 当用户说某件事"做完了"、"结束了"、"吃过了"等，先判断是提醒还是待办，然后取消/完成对应项。
- 提醒有状态：pending=未触发，triggered=已触发已提醒用户，completed=用户已确认完成，expired=已过期未触发，cancelled=已取消。
- 对于已触发(triggered)的提醒，用户确认完成时应用 update_schedule 标记为 completed，而不是 cancel_schedule。
- 对于过期(expired)的提醒，应告知用户已过期，可以建议重新创建。
- 可以用 check_task_status 查看后台任务的运行进度，并根据进度估算剩余时间来设定提醒。
- 当用户要修改提醒时（如改时间），先取消旧的再创建新的。
- "记一下/记着"通常指待办事项，"提醒我/叫我"通常指定时提醒。
- 打开文件夹/磁盘可以用 bash 命令（如 start D:\\）。
- 打开应用优先用 open_app；如果不确定路径，先用 find_program 查找。
- 用户的语音输入可能有识别错误（如"地盘"="地图"，"抖影"="抖音"），请尽量理解其真实意图。
- 如果信息不足无法执行操作，用文字追问用户。
- 一次性任务用 create_schedule，周期性任务用 create_recurring。
"""


def _save_record(record: dict) -> None:
    """追加一条记录到当前 run 文件（线程安全）。"""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _write_lock:
        with open(_run_file, "a", encoding="utf-8") as f:
            f.write(line)


# ── 数据加载 ────────────────────────────────────────

YAML_FILE = _PROJECT / "schedule_cases.yaml"


def load_cases(level_key: str) -> list[dict]:
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))
    return data.get(level_key, [])


# ── 收集可做 tool-call 断言的用例 ───────────────────
# 取所有有明确 expected_action(s) 且不是 reject/clarify_or_create 类型的用例
# boundary / complex 区不参与自动化评测

TOOL_CALL_CASES = []

# 三轴分类体系的 section → 自动化测试
_TEST_SECTIONS = ["direct", "clarify", "compound", "correct_turn", "implicit", "rich_context",
                  "tool_selection", "temporal_reasoning", "asr_tolerance", "boundary",
                  "status_aware", "chain_reasoning"]

for section_key in _TEST_SECTIONS:
    for case in load_cases(section_key):
        action = case.get("expected_action")
        actions = case.get("expected_actions")
        # 跳过 clarify / reject / suggest 类型（无 followups 时无法断言）
        if action and action in ("clarify", "reject", "reject_or_clarify", "clarify_or_create", "suggest_or_clarify"):
            continue
        if action or actions:
            case["_section"] = section_key
            case["_bloom_level"] = case.get("bloom_level", 0)
            case["_level_key"] = section_key
            # 唯一键（同一 input 可能出现在 implicit 和 rich_context 中）
            case["_case_key"] = f"{section_key}::{case['input']}"
            TOOL_CALL_CASES.append(case)


# ── Mock 任务表：为特定 case 注入匹配的预设任务 ──────
# key = case["input"] 的前缀或完整文本
# 未匹配的 case 使用 DEFAULT_MOCK_TASKS（喝水×2 + 开会）

CASE_MOCK_TASKS = {
    "把明天早上8点的会议提醒取消": [
        {"task_id": "t-1", "content": "会议", "time": "08:00", "recurrence": None, "date": "2026-04-11"},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
    ],
    "先帮我设一个明天下午3点的提醒": [
        {"task_id": "t-1", "content": "开会", "time": "15:00", "recurrence": None, "date": "2026-04-10"},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
    ],
    "把每天9点的打卡提醒改到8点半": [
        {"task_id": "t-1", "content": "打卡", "time": "09:00", "recurrence": "daily"},
        {"task_id": "t-2", "content": "喝水", "time": "15:00", "recurrence": "daily"},
    ],
    "明天的提醒不要了": [
        {"task_id": "t-1", "content": "买菜", "time": "10:00", "recurrence": None, "date": "2026-04-11"},
        {"task_id": "t-2", "content": "寄快递", "time": "14:00", "recurrence": None, "date": "2026-04-12"},
        {"task_id": "t-3", "content": "取文件", "time": "10:00", "recurrence": None, "date": "2026-04-13"},
    ],
    # --- implicit 区 ---
    "药吃过了": [
        {"task_id": "t-1", "content": "吃药", "time": "09:00", "recurrence": None},
        {"task_id": "t-2", "content": "喝水", "time": "15:00", "recurrence": "daily"},
    ],
    "会开完了": [
        {"task_id": "t-1", "content": "部门周会", "time": "14:00", "recurrence": None},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
    ],
    "刚收到通知，下午的会取消了": [
        {"task_id": "t-1", "content": "下午会议", "time": "14:00", "recurrence": None},
        {"task_id": "t-2", "content": "喝水", "time": "15:00", "recurrence": "daily"},
    ],
    "查一下我有没有重复的提醒": [
        {"task_id": "t-1", "content": "喝水", "time": "09:00", "recurrence": "daily"},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
        {"task_id": "t-3", "content": "开会", "time": "14:00", "recurrence": None},
    ],
    "帮我把下午的会议提醒删掉": [
        {"task_id": "t-1", "content": "下午会议", "time": "14:00", "recurrence": None},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
    ],
    "取消那个提醒": [
        {"task_id": "t-1", "content": "开会", "time": "14:00", "recurrence": None},
    ],
    "我今天还有什么事": [
        {"task_id": "t-1", "content": "开会", "time": "14:00", "recurrence": None},
        {"task_id": "t-2", "content": "喝水", "time": "09:00", "recurrence": "daily"},
        {"task_id": "t-3", "content": "买菜", "time": "18:00", "recurrence": None},
    ],
    "部署完了": [
        {"task_id": "t-1", "content": "检查部署状态", "time": "16:30", "recurrence": None},
        {"task_id": "t-2", "content": "检查部署状态", "time": "17:00", "recurrence": None},
        {"task_id": "t-3", "content": "喝水", "time": "09:00", "recurrence": "daily"},
        {"task_id": "t-4", "content": "站会", "time": "10:00", "recurrence": "daily"},
        {"task_id": "t-5", "content": "吃药", "time": "12:00", "recurrence": None},
    ],
}


def _get_mock_tasks(case: dict) -> list[dict] | None:
    """获取 mock 任务：优先用 case 内联的 mock_tasks，再按输入前缀匹配，都没有则返回 None（用默认）。"""
    # inline mock_tasks（rich_context 区）
    if "mock_tasks" in case:
        return case["mock_tasks"]
    # 按输入前缀匹配
    user_input = case["input"]
    for prefix, tasks in CASE_MOCK_TASKS.items():
        if user_input.startswith(prefix):
            return tasks
    return None


# ===========================================================
# 线程 worker：每个 case 的完整执行逻辑
# ===========================================================

def _run_tool_case(case: dict) -> dict:
    """单条 case：agent_loop 调用 + 断言 + 写 jsonl。线程安全。"""
    user_input = case["input"]
    bloom_level = case["_bloom_level"]

    # 每个线程独立 ToolDispatcher（线程安全）
    scheduler = ToolDispatcher()
    if case.get("current_time"):
        scheduler.set_current_time(case["current_time"])
    mock_tasks = _get_mock_tasks(case)
    if mock_tasks is not None:
        scheduler.set_mock_tasks(mock_tasks)
    if case.get("mock_todos"):
        scheduler.set_mock_todos(case["mock_todos"])
    if case.get("mock_media"):
        scheduler.set_mock_media(case["mock_media"])
    if case.get("mock_running_tasks"):
        scheduler.set_mock_running_tasks(case["mock_running_tasks"])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    # 多轮追加消息（L4 连续修改场景）
    followups = case.get("user_followups")

    t0 = time.monotonic()
    try:
        result = agent_loop(target_client, TARGET_MODEL, messages, TOOLS, scheduler,
                            user_followups=followups)
    except Exception as e:
        record = {
            "test": "tool_calling", "input": user_input,
            "bloom_level": bloom_level,
            "passed": False, "error": str(e),
            "timestamp": datetime.now().astimezone().isoformat(),
            "target_model": TARGET_MODEL,
        }
        _save_record(record)
        return record
    latency_ms = int((time.monotonic() - t0) * 1000)

    called = result["called_tools"]
    tool_calls = result["tool_calls"]
    text_reply = result["text"]

    errors = []

    # ---- 单 action 断言 ----
    expected_action = case.get("expected_action")
    expected_actions = case.get("expected_actions")
    # expected_action_any: 任一工具命中即可（如 create_schedule / create_recurring 均可接受）
    expected_action_any = case.get("expected_action_any")

    if expected_action:
        accept_set = set(expected_action_any) if expected_action_any else {expected_action}
        if not called:
            errors.append(f"期望调用 {accept_set}，但模型没有发起任何 tool_call（回复: {text_reply[:100]}）")
        elif not (accept_set & set(called)):
            errors.append(f"期望调用 {accept_set} 之一，实际调用了 {called}")

    # ---- 多 action 断言 ----
    if expected_actions:
        for ea in expected_actions:
            if ea not in called:
                errors.append(f"期望调用 {ea}，但未出现在 {called}")
        if len(called) < len(expected_actions):
            errors.append(f"期望 {len(expected_actions)} 次工具调用，实际 {len(called)} 次")

    # ---- 参数断言（L3 精确值）----
    if expected_action and called and (accept_set & set(called)):
        # 找到命中的工具调用（优先匹配 expected_action，fallback 到 any）
        matched_tool = expected_action if expected_action in called else (accept_set & set(called)).pop()
        matching = [tc for tc in tool_calls if tc["name"] == matched_tool]
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

            if "expected_delay_minutes_range" in case:
                lo, hi = case["expected_delay_minutes_range"]
                actual = args.get("delay_minutes")
                if actual is None:
                    errors.append(f"delay_minutes: 期望在 [{lo}, {hi}]，但未传入 delay_minutes 参数")
                elif not (lo <= actual <= hi):
                    errors.append(f"delay_minutes={actual}, 期望在 [{lo}, {hi}]")

            if "expected_status" in case:
                actual = args.get("status", "")
                if actual != case["expected_status"]:
                    errors.append(f"status: 期望 {case['expected_status']!r}, 实际 {actual!r}")

    # ---- L4 最终值断言 ----
    if "expected_final_delay_minutes" in case and called:
        create_calls = [tc for tc in tool_calls if tc["name"] == "create_schedule"]
        if create_calls:
            actual = create_calls[-1]["args"].get("delay_minutes")
            if actual != case["expected_final_delay_minutes"]:
                errors.append(f"final delay_minutes: 期望 {case['expected_final_delay_minutes']}, 实际 {actual}")

    passed = len(errors) == 0

    # ---- 观察指标：创建前是否先查 / 创建后是否验证 ----
    create_tools = {"create_schedule", "create_recurring", "create_todo"}
    check_tools = {"get_current_time", "list_schedules", "list_todos"}
    did_create = bool(create_tools & set(called))

    create_indices = [i for i, t in enumerate(called) if t in create_tools]
    check_indices = [i for i, t in enumerate(called) if t in check_tools]

    did_check_before_create = (
        bool(create_indices) and bool(check_indices)
        and min(check_indices) < min(create_indices)
    )
    did_verify_after_create = (
        bool(create_indices) and bool(check_indices)
        and max(check_indices) > max(create_indices)
    )

    record = {
        "test": "tool_calling",
        "bloom_level": bloom_level,
        "bloom_tag": case.get("bloom_tag", ""),
        "operation": case.get("operation", ""),
        "context": case.get("context", ""),
        "turns_type": case.get("turns", ""),
        "section": case.get("_section", ""),
        "difficulty": case.get("difficulty"),
        "input": user_input,
        "tool_calls": tool_calls,
        "called_tools": called,
        "text_reply": text_reply,
        "expected_action": expected_action,
        "expected_actions": expected_actions,
        "passed": passed,
        "errors": errors,
        "latency_ms": latency_ms,
        "turns": result.get("turns", 1),
        "user_turns": result.get("user_turns", 0),
        "post_create_verify": did_verify_after_create,
        "pre_create_check": did_check_before_create,
        "timestamp": datetime.now().astimezone().isoformat(),
        "target_model": TARGET_MODEL,
    }
    # 失败时记录完整对话链，方便调试
    if not passed:
        record["conversation"] = result.get("conversation", [])
    _save_record(record)
    return record


# ===========================================================
# Fixture：ThreadPoolExecutor 并发预跑所有 case
# ===========================================================

@pytest.fixture(scope="module")
def all_results():
    """单进程内多线程并发执行所有 API 调用，返回预计算结果。"""
    results = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for c in TOOL_CALL_CASES:
            futures[pool.submit(_run_tool_case, c)] = c["_case_key"]

        for f in as_completed(futures):
            key = futures[f]
            try:
                results[key] = f.result()
            except Exception as e:
                results[key] = {"input": key, "passed": False, "error": str(e)}

    return results


# ===========================================================
# 测试
# ===========================================================

@pytest.mark.parametrize(
    "case",
    TOOL_CALL_CASES,
    ids=[f"{c['_section']}-{c['input'][:15]}" for c in TOOL_CALL_CASES],
)
def test_tool_calling(case: dict, all_results) -> None:
    """v2: 确定性工具调用断言（agent_loop 多轮）。"""
    result = all_results[case["_case_key"]]
    assert result["passed"], (
        " | ".join(result.get("errors", [result.get("error", "unknown")]))
    )
