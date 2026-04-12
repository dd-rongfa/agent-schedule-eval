"""
错误模式 Case 生成器
====================
按 6 种已知失败模式批量生成 test case，用于 run_dataset.py 执行和收集轨迹。

错误模式来源于 v2 评测中观察到的真实失败轨迹分析：

  模式 1: tool_confusion    — 相似工具干扰（schedule vs todo, open_app vs bash）
  模式 2: missing_tool      — 应调工具但退化为纯文本
  模式 3: wrong_params      — 工具选对但参数错误
  模式 4: blind_retry       — 瞬态失败后盲目重试，不用 diagnose/backoff
  模式 5: hallucination     — 工具返回异常但编造成功信息
  模式 6: chain_break       — 多步链路中断（漏掉 verify / pre-check）

每种模式生成多个变体，通过组合不同的：
  - 用户输入措辞（正式/口语/ASR 错误）
  - 背景复杂度（空/简单/丰富）
  - mock 数据（无提醒/多个相似提醒/有干扰项）

生成结果写入 YAML 或直接返回 dict 列表供 run_dataset.py 使用。
"""

from typing import Any


# ── 模式 1: 工具混淆 (tool_confusion) ──
# 动机：20 工具环境下 schedule/todo/app/bash 功能重叠
TOOL_CONFUSION_CASES = [
    {
        "id": "tc_01",
        "pattern": "tool_confusion",
        "subtype": "schedule_vs_todo",
        "input": "记一下明天要寄快递",
        "description": "用户说'记一下'→应该用 create_todo，但模型可能误用 create_schedule",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "create_todo",
        "confusion_target": "create_schedule",
    },
    {
        "id": "tc_02",
        "pattern": "tool_confusion",
        "subtype": "schedule_vs_todo",
        "input": "帮我记着下午4点有个面试",
        "description": "'记着'+具体时间 → 应该用 create_schedule（有时间点），但'记着'暗示 todo",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "create_schedule",
        "confusion_target": "create_todo",
    },
    {
        "id": "tc_03",
        "pattern": "tool_confusion",
        "subtype": "schedule_vs_todo",
        "input": "提醒我明天买生日蛋糕",
        "description": "'提醒我'+无具体时间 → create_schedule 但缺时间，合理行为是追问",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "create_schedule",
        "confusion_target": "create_todo",
    },
    {
        "id": "tc_04",
        "pattern": "tool_confusion",
        "subtype": "app_vs_bash",
        "input": "帮我打开计算器",
        "description": "打开应用 → open_app 是正解，但模型可能用 bash start calc",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "open_app",
        "confusion_target": "bash",
    },
    {
        "id": "tc_05",
        "pattern": "tool_confusion",
        "subtype": "app_vs_bash",
        "input": "打开D盘的项目文件夹",
        "description": "打开文件夹 → bash(start D:\\project) 是正解，而非 open_app",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "bash",
        "confusion_target": "open_app",
    },
    {
        "id": "tc_06",
        "pattern": "tool_confusion",
        "subtype": "cancel_vs_complete",
        "input": "那个吃药的提醒可以关了",
        "description": "'关了'有歧义 → 如果已触发应 update(completed)，未触发才 cancel",
        "mock_tasks": [
            {"task_id": "t-1", "content": "吃药", "time": "09:00", "status": "triggered"},
        ],
        "mock_todos": [],
        "expected_tool": "update_schedule",
        "confusion_target": "cancel_schedule",
    },
    {
        "id": "tc_07",
        "pattern": "tool_confusion",
        "subtype": "todo_complete_vs_delete",
        "input": "那个买菜不用了",
        "description": "'不用了'→ 应该 delete_todo（任务取消），还是 complete_todo（已完成）？",
        "mock_tasks": [],
        "mock_todos": [
            {"todo_id": "todo-1", "content": "买菜", "status": "pending"},
        ],
        "expected_tool": "delete_todo",
        "confusion_target": "complete_todo",
    },
    {
        "id": "tc_08",
        "pattern": "tool_confusion",
        "subtype": "schedule_vs_recurring",
        "input": "以后每天都 8 点叫我起床",
        "description": "'每天'→ 应该用 create_recurring，但模型可能用 create_schedule",
        "mock_tasks": [],
        "mock_todos": [],
        "expected_tool": "create_recurring",
        "confusion_target": "create_schedule",
    },
]


# ── 模式 2: 工具缺失/纯文本退化 (missing_tool) ──
# 动机：模型在 ASR 噪音或隐性意图下放弃调工具
MISSING_TOOL_CASES = [
    {
        "id": "mt_01",
        "pattern": "missing_tool",
        "subtype": "asr_noise",
        "input": "定个钟明天七点",
        "description": "ASR 错误'定个钟'→ 应理解为'定个闹钟'并 create_schedule",
        "mock_tasks": [],
        "expected_tool": "create_schedule",
    },
    {
        "id": "mt_02",
        "pattern": "missing_tool",
        "subtype": "asr_noise",
        "input": "把那个地头打开",
        "description": "ASR 错误'地头'→ 应理解为'地图'并 open_app",
        "mock_tasks": [],
        "expected_tool": "open_app",
    },
    {
        "id": "mt_03",
        "pattern": "missing_tool",
        "subtype": "implicit_intent",
        "input": "药吃过了",
        "description": "隐性意图 → 应 list_schedules 找吃药提醒 + update_schedule(completed)",
        "mock_tasks": [
            {"task_id": "t-1", "content": "吃药", "time": "09:00", "status": "triggered"},
        ],
        "expected_tool": "update_schedule",
    },
    {
        "id": "mt_04",
        "pattern": "missing_tool",
        "subtype": "implicit_intent",
        "input": "会开完了，没啥事了",
        "description": "隐性完成 → 应更新会议提醒状态",
        "mock_tasks": [
            {"task_id": "t-1", "content": "部门周会", "time": "14:00", "status": "triggered"},
            {"task_id": "t-2", "content": "客户会议", "time": "16:00", "status": "pending"},
        ],
        "expected_tool": "update_schedule",
    },
    {
        "id": "mt_05",
        "pattern": "missing_tool",
        "subtype": "vague_request",
        "input": "还有啥事没做完的",
        "description": "模糊查询 → 应 list_schedules + list_todos，但可能退化为纯文本猜测",
        "mock_tasks": [
            {"task_id": "t-1", "content": "开会", "time": "14:00"},
        ],
        "mock_todos": [
            {"todo_id": "todo-1", "content": "写周报", "status": "pending"},
        ],
        "expected_tool": "list_schedules",
    },
]


# ── 模式 3: 参数错误 (wrong_params) ──
# 动机：工具选对了但关键参数错，如时间格式、周期类型
WRONG_PARAMS_CASES = [
    {
        "id": "wp_01",
        "pattern": "wrong_params",
        "subtype": "time_format",
        "input": "下午三点半提醒我开会",
        "description": "时间应为 '15:30'，模型可能传 '3:30' 或 '下午3:30'",
        "expected_tool": "create_schedule",
        "expected_time": "15:30",
    },
    {
        "id": "wp_02",
        "pattern": "wrong_params",
        "subtype": "recurrence_type",
        "input": "每周三和周五早上 7 点提醒我锻炼",
        "description": "应传 recurrence='weekly' + days=['wednesday','friday']",
        "expected_tool": "create_recurring",
        "expected_recurrence": "weekly",
        "expected_days": ["wednesday", "friday"],
    },
    {
        "id": "wp_03",
        "pattern": "wrong_params",
        "subtype": "wrong_task_id",
        "input": "取消早上那个喝水的提醒",
        "description": "有两个喝水提醒(t-1/t-3)，模型需选对时间匹配的那个",
        "mock_tasks": [
            {"task_id": "t-1", "content": "喝水", "time": "09:00", "recurrence": "daily"},
            {"task_id": "t-2", "content": "开会", "time": "14:00"},
            {"task_id": "t-3", "content": "喝水", "time": "15:00", "recurrence": "daily"},
        ],
        "expected_tool": "cancel_schedule",
        "expected_task_id": "t-1",
    },
    {
        "id": "wp_04",
        "pattern": "wrong_params",
        "subtype": "date_ambiguity",
        "input": "后天下午 2 点提醒我去医院",
        "description": "需要先 get_current_time 确定今天日期，再计算后天",
        "expected_tool": "create_schedule",
        "expected_time": "14:00",
    },
    {
        "id": "wp_05",
        "pattern": "wrong_params",
        "subtype": "content_mismatch",
        "input": "把开会提醒改成下午 4 点",
        "description": "应 cancel 旧的 + create 新的（或 update），关键是内容和时间都要对",
        "mock_tasks": [
            {"task_id": "t-1", "content": "开会", "time": "14:00"},
        ],
        "expected_tool": "cancel_schedule",
    },
]


# ── 模式 4: 盲目重试（不用诊断/退避工具） (blind_retry) ──
# 动机：瞬态故障后模型不用 diagnose_error / wait_and_retry，直接重复调同一工具
# 这些 case 必须配合 EnhancedDispatcher + transient_fail=True 运行
BLIND_RETRY_CASES = [
    {
        "id": "br_01",
        "pattern": "blind_retry",
        "subtype": "no_diagnose",
        "input": "帮我设一个明天 9 点的开会提醒",
        "description": "create_schedule 首次返回 TRANSIENT_FAILURE，期望模型调 diagnose_error 或 wait_and_retry",
        "transient_fail_count": 1,
        "expected_recovery_tools": ["diagnose_error", "wait_and_retry"],
        "diagnostic_info": {
            "cause": "transient_failure",
            "retryable": True,
            "suggestion": "系统暂时繁忙，建议等待 2 秒后重试",
        },
    },
    {
        "id": "br_02",
        "pattern": "blind_retry",
        "subtype": "no_backoff",
        "input": "创建一个每天下午 3 点喝水的周期提醒",
        "description": "create_recurring 前 2 次失败，期望模型使用指数退避而非立即重试",
        "transient_fail_count": 2,
        "expected_recovery_tools": ["wait_and_retry"],
        "diagnostic_info": {
            "cause": "rate_limit",
            "retryable": True,
            "suggestion": "API 限流，建议等待 5 秒后重试",
        },
    },
    {
        "id": "br_03",
        "pattern": "blind_retry",
        "subtype": "persistent_after_diagnose",
        "input": "取消那个 14 点的开会提醒",
        "description": "cancel 失败且 diagnose 显示 permanent_failure，期望模型告知用户而非继续重试",
        "transient_fail_count": 99,  # 永远失败
        "expected_recovery_tools": ["diagnose_error"],
        "diagnostic_info": {
            "cause": "permanent_failure",
            "retryable": False,
            "suggestion": "后端服务不可用，无法执行取消操作",
        },
        "mock_tasks": [
            {"task_id": "t-1", "content": "开会", "time": "14:00"},
        ],
    },
    {
        "id": "br_04",
        "pattern": "blind_retry",
        "subtype": "recover_after_wait",
        "input": "5 分钟后提醒我休息一下",
        "description": "首次瞬态失败 → diagnose → wait(2s) → 重试成功",
        "transient_fail_count": 1,
        "expected_recovery_tools": ["diagnose_error", "wait_and_retry"],
        "diagnostic_info": {
            "cause": "transient_failure",
            "retryable": True,
            "suggestion": "网络波动，建议等待 2 秒后重试",
        },
    },
]


# ── 模式 5: 幻觉/编造 (hallucination) ──
# 动机：扩展现有 flaky_tools.py 的故障模式，增加更多变体
HALLUCINATION_CASES = [
    {
        "id": "hl_01",
        "pattern": "hallucination",
        "subtype": "silent_drop_with_context",
        "input": "设一个今天 20:00 的提醒看电影",
        "description": "create 返回空对象，但当前有多个提醒 → 模型是否混淆已有提醒和新创建的",
        "fault_mode": "silent_drop",
        "mock_tasks": [
            {"task_id": "t-1", "content": "吃饭", "time": "18:00"},
            {"task_id": "t-2", "content": "看电影", "time": "21:00"},
        ],
        "followup": "设好了吗？ID 是什么？",
    },
    {
        "id": "hl_02",
        "pattern": "hallucination",
        "subtype": "param_mismatch_subtle",
        "input": "创建一个 weekly 提醒，每周日 10:00 做运动",
        "description": "返回 ok 但 recurrence=daily（微妙不一致）",
        "fault_mode": "param_mismatch",
        "mock_tasks": [],
        "followup": "确认一下，是每周日还是每天？",
    },
    {
        "id": "hl_03",
        "pattern": "hallucination",
        "subtype": "content_swap",
        "input": "设一个明天早上 7 点的提醒，内容是跑步",
        "description": "返回 ok 但 content='提醒开会'（内容被替换）",
        "fault_mode": "content_mismatch",
        "mock_tasks": [],
        "followup": "确认一下提醒内容是什么？",
    },
    {
        "id": "hl_04",
        "pattern": "hallucination",
        "subtype": "partial_with_verify",
        "input": "先取消 task-001，再创建一个明天 10 点的提醒写报告",
        "description": "cancel 返回 warning(not found)，create 正常 → 模型是否如实报告取消失败",
        "fault_mode": "partial_failure",
        "mock_tasks": [],
        "followup": "两个操作都成功了吗？",
    },
]


# ── 模式 6: 多步链路中断 (chain_break) ──
# 动机：模型跳过关键步骤（先查再做、做完验证）
CHAIN_BREAK_CASES = [
    {
        "id": "cb_01",
        "pattern": "chain_break",
        "subtype": "no_pre_check",
        "input": "把下午的会议提醒取消了",
        "description": "当前有多个下午提醒 → 应先 list_schedules 确认，直接 cancel 可能取消错的",
        "mock_tasks": [
            {"task_id": "t-1", "content": "部门周会", "time": "14:00"},
            {"task_id": "t-2", "content": "客户会议", "time": "15:30"},
            {"task_id": "t-3", "content": "喝下午茶", "time": "15:00"},
        ],
        "expected_sequence": ["list_schedules", "cancel_schedule"],
    },
    {
        "id": "cb_02",
        "pattern": "chain_break",
        "subtype": "no_post_verify",
        "input": "帮我创建一个明天 8 点的提醒出门",
        "description": "创建后应 list_schedules 验证，但模型可能直接说'已创建'",
        "mock_tasks": [],
        "expected_sequence": ["create_schedule", "list_schedules"],
    },
    {
        "id": "cb_03",
        "pattern": "chain_break",
        "subtype": "no_time_check",
        "input": "设一个半小时后的提醒",
        "description": "需要先 get_current_time 确定当前时间，才能计算 delay 或绝对时间",
        "mock_tasks": [],
        "expected_sequence": ["get_current_time", "create_schedule"],
    },
    {
        "id": "cb_04",
        "pattern": "chain_break",
        "subtype": "incomplete_modify",
        "input": "把 9 点那个喝水改成 8 点半",
        "description": "修改 = 先查+取消旧+创建新（或 update），缺任一步都不完整",
        "mock_tasks": [
            {"task_id": "t-1", "content": "喝水", "time": "09:00", "recurrence": "daily"},
        ],
        "expected_sequence": ["list_schedules", "cancel_schedule", "create_recurring"],
    },
    {
        "id": "cb_05",
        "pattern": "chain_break",
        "subtype": "skip_status_check",
        "input": "我刚做完运动了",
        "description": "应先查提醒列表确认有运动相关提醒，再更新状态",
        "mock_tasks": [
            {"task_id": "t-1", "content": "运动", "time": "07:00", "status": "triggered"},
            {"task_id": "t-2", "content": "吃早餐", "time": "08:00", "status": "pending"},
        ],
        "expected_sequence": ["list_schedules", "update_schedule"],
    },
]


# ── 汇总 ──

ALL_CASES = (
    TOOL_CONFUSION_CASES
    + MISSING_TOOL_CASES
    + WRONG_PARAMS_CASES
    + BLIND_RETRY_CASES
    + HALLUCINATION_CASES
    + CHAIN_BREAK_CASES
)

PATTERN_SUMMARY = {
    "tool_confusion": {
        "count": len(TOOL_CONFUSION_CASES),
        "description": "相似工具干扰 — 功能重叠时选错工具",
        "需要增强工具集": False,
    },
    "missing_tool": {
        "count": len(MISSING_TOOL_CASES),
        "description": "工具缺失 — ASR噪音/隐性意图导致退化为纯文本",
        "需要增强工具集": False,
    },
    "wrong_params": {
        "count": len(WRONG_PARAMS_CASES),
        "description": "参数错误 — 工具选对但关键参数错误",
        "需要增强工具集": False,
    },
    "blind_retry": {
        "count": len(BLIND_RETRY_CASES),
        "description": "盲目重试 — 不用诊断/退避工具，直接重复调用",
        "需要增强工具集": True,
    },
    "hallucination": {
        "count": len(HALLUCINATION_CASES),
        "description": "幻觉编造 — 工具返回异常但编造成功信息",
        "需要增强工具集": False,
    },
    "chain_break": {
        "count": len(CHAIN_BREAK_CASES),
        "description": "链路中断 — 多步操作跳过关键步骤",
        "需要增强工具集": False,
    },
}

def get_cases_by_pattern(pattern: str) -> list[dict]:
    return [c for c in ALL_CASES if c["pattern"] == pattern]

def summary():
    """打印 case 汇总"""
    total = len(ALL_CASES)
    print(f"Total cases: {total}")
    print()
    for p, info in PATTERN_SUMMARY.items():
        enhanced = " [+diagnose/backoff]" if info["需要增强工具集"] else ""
        print(f"  {p}: {info['count']} cases — {info['description']}{enhanced}")
    print()
    print("Pattern distribution:")
    for p, info in PATTERN_SUMMARY.items():
        bar = "█" * info["count"]
        print(f"  {p:20s} {bar} ({info['count']})")


if __name__ == "__main__":
    summary()
