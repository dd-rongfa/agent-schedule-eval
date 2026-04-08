"""
promptfoo provider — Agent 定时任务意图评测（Bloom L1-L3 示例）

演示如何用 promptfoo 框架跑与 agent_schedule_eval 相同的评测逻辑。
最终选择 pytest 而非 promptfoo 的原因见 schedule-eval.yaml 顶部注释。
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

# ── 环境 ────────────────────────────────────────────

ENV_FILE = Path(__file__).resolve().parent.parent / "starter_judge" / ".env"


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

SYSTEM_PROMPT = """\
你是一个智能提醒 Agent。用户发来一条消息，请分析意图并说明你会采取的行动。
要求：
1. 判断信息是否充分，选择唯一动作：create_schedule / create_recurring / cancel_schedule / clarify / reject
2. 如果选择执行类动作，说明时间参数和提醒内容
3. 仅当关键信息严重缺失时才选 clarify
请用简洁的中文回答，先给出动作，再给出说明。"""


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """promptfoo 调用入口。"""
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )

    user_input = context.get("vars", {}).get("input", prompt)

    resp = client.chat.completions.create(
        model=os.environ.get("MODEL_NORMAL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0,
        max_tokens=512,
    )

    output = resp.choices[0].message.content or ""
    return {
        "output": output,
        "tokenUsage": {
            "total": resp.usage.total_tokens if resp.usage else 0,
            "prompt": resp.usage.prompt_tokens if resp.usage else 0,
            "completion": resp.usage.completion_tokens if resp.usage else 0,
        },
    }
