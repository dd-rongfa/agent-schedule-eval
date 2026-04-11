"""
假工具模块
用途：记录 Agent 的工具调用，不产生真实副作用。
在自动化测试里把这些假工具注入给 Agent，
就能断言"调了什么工具、传了什么参数"，
而不用真的等定时任务触发。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    params: dict[str, Any]


class FakeScheduler:
    """记录所有调度类工具调用，供测试断言使用。"""

    def __init__(self, current_time: str = "2026-04-10 14:30") -> None:
        self.calls: list[ToolCall] = []
        self._current_time = current_time

    def reset(self) -> None:
        self.calls.clear()

    def set_current_time(self, time_str: str) -> None:
        """设置模拟的当前时间（供 get_current_time 返回）。"""
        self._current_time = time_str

    # ---------- 工具方法（模拟 Agent 可调用的工具） ----------

    def get_current_time(self, **kwargs: Any) -> dict:
        call = ToolCall(name="get_current_time", params=kwargs)
        self.calls.append(call)
        return {"status": "ok", "current_time": self._current_time}

    def create_schedule(self, content: str, delay_minutes: int | None = None,
                        time: str | None = None, recurrence: str | None = None,
                        **kwargs: Any) -> dict:
        call = ToolCall(name="create_schedule", params={
            "content": content,
            "delay_minutes": delay_minutes,
            "time": time,
            "recurrence": recurrence,
            **kwargs,
        })
        self.calls.append(call)
        return {"status": "ok", "task_id": f"mock-{len(self.calls)}"}

    def cancel_schedule(self, task_id: str | None = None,
                        description: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="cancel_schedule", params={
            "task_id": task_id,
            "description": description,
            **kwargs,
        })
        self.calls.append(call)
        return {"status": "ok"}

    def create_recurring(self, content: str, interval_minutes: int | None = None,
                         total_count: int | None = None, recurrence: str | None = None,
                         days: list[str] | None = None, time: str | None = None,
                         **kwargs: Any) -> dict:
        call = ToolCall(name="create_recurring", params={
            "content": content,
            "interval_minutes": interval_minutes,
            "total_count": total_count,
            "recurrence": recurrence,
            "days": days,
            "time": time,
            **kwargs,
        })
        self.calls.append(call)
        return {"status": "ok", "task_id": f"mock-recurring-{len(self.calls)}"}

    def list_schedules(self, date: str | None = None,
                       keyword: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="list_schedules", params={
            "date": date, "keyword": keyword, **kwargs,
        })
        self.calls.append(call)
        # 返回预设的假数据，模拟已有提醒列表
        return {
            "status": "ok",
            "tasks": [
                {"task_id": "mock-1", "content": "喝水", "time": "09:00", "recurrence": "daily"},
                {"task_id": "mock-2", "content": "开会", "time": "14:00", "recurrence": None},
                {"task_id": "mock-3", "content": "喝水", "time": "15:00", "recurrence": "daily"},
            ],
        }

    # ---------- 帮助方法，方便测试里做断言 ----------

    def called_tools(self) -> list[str]:
        """返回调用过的工具名列表，顺序保留。"""
        return [c.name for c in self.calls]

    def last_call(self) -> ToolCall | None:
        return self.calls[-1] if self.calls else None

    def calls_for(self, tool_name: str) -> list[ToolCall]:
        return [c for c in self.calls if c.name == tool_name]
