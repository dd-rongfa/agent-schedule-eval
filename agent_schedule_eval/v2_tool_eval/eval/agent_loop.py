"""
agent_loop — 多轮工具调用循环
================================
让模型反复调工具直到给出最终文字回复（或达到轮次上限）。

用法：
    from agent_loop import agent_loop

    scheduler = FakeScheduler()
    result = agent_loop(client, MODEL, messages, TOOLS, scheduler, max_turns=10)
    # result["called_tools"]  → ["get_current_time", "create_schedule"]
    # result["tool_calls"]    → [{"name": ..., "args": ...}, ...]
    # result["text"]          → 最终文字回复
    # result["turns"]         → 实际轮次数
"""

import json
import logging
import time
from typing import Any

from openai import APIStatusError, APITimeoutError, OpenAI

logger = logging.getLogger(__name__)

# ── Retry 配置 ─────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # 秒，指数退避基数
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
API_TIMEOUT = 120  # 秒，单次 API 调用超时


def _serialize_messages(messages: list) -> list[dict]:
    """将对话历史序列化为可 JSON 化的列表（含 tool_calls 对象）。"""
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        else:
            # OpenAI ChatCompletionMessage 对象
            entry = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {"name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in m.tool_calls
                ]
            result.append(entry)
    return result


def agent_loop(
    client: OpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict],
    scheduler,  # FakeScheduler | ToolDispatcher
    *,
    max_turns: int = 10,
    temperature: float = 0.1,
    user_followups: list[str] | None = None,
) -> dict[str, Any]:
    """
    执行多轮 tool_call 循环，收集所有调用结果。

    Parameters
    ----------
    client : OpenAI client
    model : 模型名称
    messages : 初始 messages（含 system + user）
    tools : OpenAI tools schema
    scheduler : FakeScheduler 实例（已 reset）
    max_turns : 最大轮次（防无限循环）
    temperature : 采样温度
    user_followups : 用户追加消息队列。
        当模型返回纯文本（无 tool_call）且队列非空时，
        弹出第一条作为新 user message 继续对话。
        为 None 时行为与之前完全一致。

    Returns
    -------
    dict with keys:
        text            - 最终文字回复
        tool_calls      - 所有轮次的 tool_call 列表
        called_tools    - 去重后的工具名列表（保留顺序）
        scheduler_calls - scheduler 记录的全部调用
        turns           - 实际执行轮次
        user_turns      - 实际使用的用户追加轮数
        conversation    - 完整对话历史
    """
    all_tool_calls: list[dict] = []
    messages = list(messages)  # 浅拷贝，不污染外部
    followups = list(user_followups) if user_followups else []
    user_turns_used = 0

    def _build_result(turn: int, final_text: str = "") -> dict[str, Any]:
        return {
            "text": final_text,
            "tool_calls": all_tool_calls,
            "called_tools": [tc["name"] for tc in all_tool_calls],
            "scheduler_calls": [
                {"name": c.name, "params": c.params} for c in scheduler.calls
            ],
            "turns": turn,
            "user_turns": user_turns_used,
            "conversation": _serialize_messages(messages),
        }

    for turn in range(1, max_turns + 1):
        # ── 带重试的 API 调用 ──
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    timeout=API_TIMEOUT,
                )
                break
            except (APIStatusError, APITimeoutError) as e:
                status = getattr(e, "status_code", 0)
                if isinstance(e, APITimeoutError) or status in RETRYABLE_STATUS:
                    delay = RETRY_BASE_DELAY ** attempt
                    logger.warning(
                        "API call failed (attempt %d/%d, status=%s), "
                        "retrying in %ds: %s",
                        attempt, MAX_RETRIES, status, delay, e,
                    )
                    last_err = e
                    time.sleep(delay)
                else:
                    raise
        else:
            raise last_err  # type: ignore[misc]

        msg = resp.choices[0].message

        if not msg.tool_calls:
            # 模型给出了文字回复（无 tool_call）
            messages.append({"role": "assistant", "content": msg.content or ""})

            if followups:
                # 还有用户追加消息，注入后继续对话
                followup = followups.pop(0)
                messages.append({"role": "user", "content": followup})
                user_turns_used += 1
                continue

            # 没有更多 followup，循环结束
            return _build_result(turn, msg.content or "")

        # 把 assistant message（含 tool_calls）追加到对话
        messages.append(msg)

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {"_raw": tc.function.arguments}

            all_tool_calls.append({"name": fn_name, "args": fn_args})

            # 转发到 FakeScheduler 执行
            handler = getattr(scheduler, fn_name, None)
            if handler:
                tool_result = handler(**fn_args)
            else:
                tool_result = {"error": f"unknown tool: {fn_name}"}

            # 把工具结果追加到对话
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result, ensure_ascii=False),
            })

    # 达到 max_turns 仍未结束
    return _build_result(max_turns)
