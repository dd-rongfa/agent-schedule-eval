"""
诊断与弹性工具 — 扩展工具集
============================
在原有 20 个工具基础上新增 2 个能力测试工具：

1. diagnose_error   — 工具调用失败后获取诊断信息（测试：主动排查 vs 盲目重试）
2. wait_and_retry   — 退避等待后重试（测试：瞬态故障理解 + 指数退避策略）

另外提供 TransientFailScheduler：使写操作前 N 次返回瞬态错误，
之后恢复正常。用于构造"重试陷阱"场景。

与 mock_tools.py 的关系：
  mock_tools.py 提供正常工具后端 + ToolDispatcher
  本文件扩展出 EnhancedDispatcher（增加诊断/退避工具 + 瞬态故障注入）
"""

from typing import Any

from mock_tools import FakeScheduler, ToolCall, ToolDispatcher


# ── 新工具 Schema（与 test_tool_calling.py 中 TOOLS 格式一致）──

DIAGNOSTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "diagnose_error",
            "description": "当工具调用返回错误或异常结果时，获取详细的诊断信息。"
                           "可以帮助判断是参数错误、权限不足还是系统瞬态故障，从而决定是修正参数还是重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "出错的工具名称",
                    },
                    "error_message": {
                        "type": "string",
                        "description": "工具返回的错误信息（可选）",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_and_retry",
            "description": "当操作因系统繁忙、网络超时等瞬态错误失败时，等待指定秒数后重试。"
                           "建议使用指数退避策略（如 1s, 2s, 4s）。最多允许等待 3 次，超过后应放弃或告知用户。",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "integer",
                        "description": "等待秒数（1-30）",
                    },
                    "reason": {
                        "type": "string",
                        "description": "等待原因（如'系统繁忙'、'网络超时'）",
                    },
                    "retry_count": {
                        "type": "integer",
                        "description": "当前是第几次重试（从 1 开始）",
                    },
                },
                "required": ["seconds"],
            },
        },
    },
]


# ── 新工具后端 ──

class FakeErrorDiagnostic:
    """诊断工具后端。

    模型在工具调用失败后可主动调用此工具获取诊断信息。
    通过预设 diagnostic_map 控制不同工具的诊断结果。
    """

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._diagnostic_map: dict[str, dict] = {}

    def reset(self) -> None:
        self.calls.clear()

    def set_diagnostic(self, tool_name: str, info: dict) -> None:
        """预设某个工具的诊断信息。"""
        self._diagnostic_map[tool_name] = info

    def diagnose_error(self, tool_name: str, error_message: str | None = None,
                       **kwargs: Any) -> dict:
        call = ToolCall(name="diagnose_error", params={
            "tool_name": tool_name, "error_message": error_message, **kwargs,
        })
        self.calls.append(call)

        if tool_name in self._diagnostic_map:
            return {"status": "ok", "diagnostic": self._diagnostic_map[tool_name]}

        # 默认诊断：返回通用建议
        return {
            "status": "ok",
            "diagnostic": {
                "cause": "transient_failure",
                "retryable": True,
                "suggestion": "系统暂时繁忙，建议等待 2-5 秒后重试",
            },
        }

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeBackoffController:
    """退避控制器后端。

    模型遇到瞬态故障时可请求等待后重试。
    内置最大重试次数限制，超出后返回错误。
    """

    def __init__(self, max_retries: int = 3) -> None:
        self.calls: list[ToolCall] = []
        self._max_retries = max_retries
        self._retry_count = 0

    def reset(self) -> None:
        self.calls.clear()
        self._retry_count = 0

    def wait_and_retry(self, seconds: int = 1, reason: str | None = None,
                       retry_count: int | None = None, **kwargs: Any) -> dict:
        self._retry_count += 1
        call = ToolCall(name="wait_and_retry", params={
            "seconds": seconds, "reason": reason, "retry_count": retry_count,
            **kwargs,
        })
        self.calls.append(call)

        if self._retry_count > self._max_retries:
            return {
                "status": "error",
                "message": f"已达最大重试次数({self._max_retries})，请告知用户操作失败或换用其他方式",
            }

        return {
            "status": "ok",
            "waited_seconds": seconds,
            "retry_count": self._retry_count,
            "remaining_retries": self._max_retries - self._retry_count,
        }

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


# ── 瞬态故障注入 ──

class TransientFailScheduler(FakeScheduler):
    """前 N 次写操作返回瞬态错误，之后恢复正常。

    与 FlakyScheduler（永远故障）不同，这里模拟的是真实的瞬态故障：
    系统暂时繁忙 → 等待后重试 → 成功。

    用途：测试模型是否理解"失败可重试"，以及是否使用 diagnose_error / wait_and_retry。
    """

    TRANSIENT_ERROR = {
        "status": "error",
        "code": "TRANSIENT_FAILURE",
        "message": "系统繁忙，请稍后重试",
        "retryable": True,
    }

    def __init__(self, fail_count: int = 1, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fail_count = fail_count
        self._write_attempts: dict[str, int] = {}  # tool_name -> attempt count

    def _check_transient(self, tool_name: str) -> dict | None:
        """如果当前工具还在故障窗口内，返回错误；否则返回 None（正常执行）。"""
        count = self._write_attempts.get(tool_name, 0) + 1
        self._write_attempts[tool_name] = count
        if count <= self._fail_count:
            call = ToolCall(name=tool_name, params={"_transient_fail": True})
            self.calls.append(call)
            return dict(self.TRANSIENT_ERROR)
        return None

    def create_schedule(self, content: str, **kwargs: Any) -> dict:
        err = self._check_transient("create_schedule")
        if err:
            return err
        return super().create_schedule(content=content, **kwargs)

    def cancel_schedule(self, task_id: str | None = None, **kwargs: Any) -> dict:
        err = self._check_transient("cancel_schedule")
        if err:
            return err
        return super().cancel_schedule(task_id=task_id, **kwargs)

    def create_recurring(self, content: str, **kwargs: Any) -> dict:
        err = self._check_transient("create_recurring")
        if err:
            return err
        return super().create_recurring(content=content, **kwargs)


# ── 增强版 Dispatcher ──

class EnhancedDispatcher(ToolDispatcher):
    """在 ToolDispatcher 基础上加入诊断/退避工具 + 可选瞬态故障注入。

    用法：
        dispatcher = EnhancedDispatcher()
        dispatcher.enable_transient_fail(fail_count=1)  # 写操作首次失败
        dispatcher.set_diagnostic("create_schedule", {...})
    """

    def __init__(self, current_time: str = "2026-04-12 14:30") -> None:
        super().__init__(current_time=current_time)
        self.diagnostic = FakeErrorDiagnostic()
        self.backoff = FakeBackoffController()
        self._tools.extend([self.diagnostic, self.backoff])

    def reset(self) -> None:
        super().reset()
        self.diagnostic.reset()
        self.backoff.reset()

    def enable_transient_fail(self, fail_count: int = 1) -> None:
        """替换 scheduler 为 TransientFailScheduler。"""
        old_time = self.scheduler._current_time
        old_tasks = self.scheduler._mock_tasks
        transient = TransientFailScheduler(
            fail_count=fail_count, current_time=old_time,
        )
        transient.set_mock_tasks(old_tasks)
        # 替换 dispatcher 中的 scheduler
        idx = self._tools.index(self.scheduler)
        self._tools[idx] = transient
        self.scheduler = transient

    def set_diagnostic(self, tool_name: str, info: dict) -> None:
        self.diagnostic.set_diagnostic(tool_name, info)
