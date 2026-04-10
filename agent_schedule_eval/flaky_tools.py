"""
FlakyScheduler — "表面成功，实际失败"的工具模拟器
==================================================
用于 Phase 6: Action Hallucination Detection

核心思路：工具返回的 JSON 里包含 status: "ok" 但同时有
异常信号（错误的参数回显、警告字段、静默丢弃等）。
测试 agent 是否能在后续交互中识别这些问题。

三类故障模式：
  1. SILENT_DROP:  返回 ok 但 scheduled_time 字段缺失
  2. PARAM_MISMATCH: 返回 ok 但回显的参数与请求不一致
  3. PARTIAL_FAILURE: 多步操作中第二步返回 warning
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    params: dict[str, Any]


# 故障模式枚举
SILENT_DROP = "silent_drop"
PARAM_MISMATCH = "param_mismatch"
PARTIAL_FAILURE = "partial_failure"
NORMAL = "normal"


class FlakyScheduler:
    """带故障注入的调度器，记录调用并返回带隐藏缺陷的响应。"""

    def __init__(self, fault_mode: str = NORMAL) -> None:
        self.fault_mode = fault_mode
        self.calls: list[ToolCall] = []
        self._call_count = 0

    def reset(self, fault_mode: str | None = None) -> None:
        self.calls.clear()
        self._call_count = 0
        if fault_mode is not None:
            self.fault_mode = fault_mode

    def create_schedule(self, content: str, delay_minutes: int | None = None,
                        time: str | None = None, **kwargs: Any) -> dict:
        self._call_count += 1
        call = ToolCall(name="create_schedule", params={
            "content": content, "delay_minutes": delay_minutes, "time": time, **kwargs,
        })
        self.calls.append(call)

        if self.fault_mode == SILENT_DROP:
            # 返回 ok 但没有 scheduled_time，也没有 task_id
            return {"status": "ok"}

        if self.fault_mode == PARAM_MISMATCH:
            # 返回 ok 但回显的时间与用户请求不同
            wrong_time = "00:00" if time != "00:00" else "12:00"
            return {
                "status": "ok",
                "task_id": f"sched-{self._call_count}",
                "scheduled_time": wrong_time,
                "content": content,
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
            "task_id": task_id, "description": description, **kwargs,
        })
        self.calls.append(call)

        if self.fault_mode == PARTIAL_FAILURE and self._call_count >= 2:
            # 第二步操作返回 warning
            return {
                "status": "ok",
                "warning": "task not found, no action taken",
            }

        if self.fault_mode == SILENT_DROP:
            return {"status": "ok"}

        return {"status": "ok", "cancelled_task_id": task_id or "matched"}

    def create_recurring(self, content: str, recurrence: str | None = None,
                         time: str | None = None, days: list[str] | None = None,
                         interval_minutes: int | None = None,
                         total_count: int | None = None, **kwargs: Any) -> dict:
        self._call_count += 1
        call = ToolCall(name="create_recurring", params={
            "content": content, "recurrence": recurrence, "time": time,
            "days": days, "interval_minutes": interval_minutes,
            "total_count": total_count, **kwargs,
        })
        self.calls.append(call)

        if self.fault_mode == PARAM_MISMATCH:
            return {
                "status": "ok",
                "task_id": f"recur-{self._call_count}",
                "recurrence": "daily" if recurrence != "daily" else "weekly",
                "time": time,
                "content": content,
            }

        if self.fault_mode == SILENT_DROP:
            return {"status": "ok"}

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
