"""
FlakyScheduler — "表面成功，实际失败"的工具模拟器
==================================================
用于 Action Hallucination Detection

核心思路：工具返回的 JSON 里包含异常信号（空响应、错误的参数回显、
警告字段等）。测试 agent 是否能在后续交互中识别这些问题。

四类故障模式：
  1. SILENT_DROP:     返回空对象 {}（无任何字段）
  2. PARAM_MISMATCH:  返回 ok 但回显的时间/周期与请求不一致
  3. CONTENT_MISMATCH:返回 ok 但回显的内容与请求不一致
  4. PARTIAL_FAILURE:  多步操作中第二步返回 warning

接口兼容 FakeScheduler，可直接替换 ToolDispatcher.scheduler。
"""

from typing import Any

from mock_tools import ToolCall

# 故障模式枚举
SILENT_DROP = "silent_drop"
PARAM_MISMATCH = "param_mismatch"
CONTENT_MISMATCH = "content_mismatch"
PARTIAL_FAILURE = "partial_failure"
NORMAL = "normal"


class FlakyScheduler:
    """带故障注入的调度器。接口兼容 FakeScheduler，可直接替换到 ToolDispatcher 中。"""

    def __init__(self, fault_mode: str = NORMAL,
                 current_time: str = "2026-04-12 14:30") -> None:
        self.fault_mode = fault_mode
        self.calls: list[ToolCall] = []
        self._call_count = 0
        self._current_time = current_time

    def reset(self, fault_mode: str | None = None) -> None:
        self.calls.clear()
        self._call_count = 0
        if fault_mode is not None:
            self.fault_mode = fault_mode

    # ── 兼容 FakeScheduler 接口 ──

    def set_current_time(self, time_str: str) -> None:
        self._current_time = time_str

    def set_mock_tasks(self, tasks: list[dict]) -> None:
        pass  # 故障测试不需要预设任务列表

    # ── 正常工具（透传，不注入故障） ──

    def get_current_time(self, **kwargs: Any) -> dict:
        call = ToolCall(name="get_current_time", params=kwargs)
        self.calls.append(call)
        return {"status": "ok", "current_time": self._current_time}

    def list_schedules(self, date: str | None = None,
                       keyword: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="list_schedules", params={
            "date": date, "keyword": keyword, **kwargs})
        self.calls.append(call)
        return {"status": "ok", "tasks": []}

    def update_schedule(self, task_id: str, status: str | None = None,
                        content: str | None = None, time: str | None = None,
                        **kwargs: Any) -> dict:
        call = ToolCall(name="update_schedule", params={
            "task_id": task_id, "status": status, "content": content,
            "time": time, **kwargs})
        self.calls.append(call)
        return {"status": "ok", "task_id": task_id, "updated": True}

    # ── 故障注入工具 ──

    def create_schedule(self, content: str, delay_minutes: int | None = None,
                        time: str | None = None, date: str | None = None,
                        **kwargs: Any) -> dict:
        self._call_count += 1
        call = ToolCall(name="create_schedule", params={
            "content": content, "delay_minutes": delay_minutes,
            "time": time, "date": date, **kwargs})
        self.calls.append(call)

        if self.fault_mode == SILENT_DROP:
            return {}

        if self.fault_mode == PARAM_MISMATCH:
            wrong_time = "00:00" if time != "00:00" else "12:00"
            return {
                "status": "ok",
                "task_id": f"sched-{self._call_count}",
                "scheduled_time": wrong_time,
                "content": content,
            }

        if self.fault_mode == CONTENT_MISMATCH:
            return {
                "status": "ok",
                "task_id": f"sched-{self._call_count}",
                "scheduled_time": time or f"+{delay_minutes}min",
                "content": "提醒开会",
            }

        # NORMAL / PARTIAL_FAILURE（单步正常）
        return {
            "status": "ok",
            "task_id": f"sched-{self._call_count}",
            "scheduled_time": time or f"+{delay_minutes}min",
            "content": content,
        }

    def cancel_schedule(self, task_id: str | None = None,
                        description: str | None = None, **kwargs: Any) -> dict:
        self._call_count += 1
        call = ToolCall(name="cancel_schedule", params={
            "task_id": task_id, "description": description, **kwargs})
        self.calls.append(call)

        if self.fault_mode == PARTIAL_FAILURE:
            return {"status": "ok", "warning": "task not found, no action taken"}

        if self.fault_mode == SILENT_DROP:
            return {}

        return {"status": "ok", "cancelled_task_id": task_id or "matched"}

    def create_recurring(self, content: str, recurrence: str | None = None,
                         time: str | None = None, days: list[str] | None = None,
                         interval_minutes: int | None = None,
                         total_count: int | None = None, **kwargs: Any) -> dict:
        self._call_count += 1
        call = ToolCall(name="create_recurring", params={
            "content": content, "recurrence": recurrence, "time": time,
            "days": days, "interval_minutes": interval_minutes,
            "total_count": total_count, **kwargs})
        self.calls.append(call)

        if self.fault_mode == PARAM_MISMATCH:
            return {
                "status": "ok",
                "task_id": f"recur-{self._call_count}",
                "recurrence": "daily" if recurrence != "daily" else "weekly",
                "time": time,
                "content": content,
            }

        if self.fault_mode == CONTENT_MISMATCH:
            return {
                "status": "ok",
                "task_id": f"recur-{self._call_count}",
                "recurrence": recurrence,
                "time": time,
                "content": "提醒开会",
            }

        if self.fault_mode == SILENT_DROP:
            return {}

        return {
            "status": "ok",
            "task_id": f"recur-{self._call_count}",
            "recurrence": recurrence,
            "time": time,
            "content": content,
        }

    # ── 辅助方法 ──

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]

    def last_call(self) -> ToolCall | None:
        return self.calls[-1] if self.calls else None

    def calls_for(self, tool_name: str) -> list[ToolCall]:
        return [c for c in self.calls if c.name == tool_name]
