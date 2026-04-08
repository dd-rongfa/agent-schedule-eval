import json
import os

from openai import OpenAI


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_JUDGE_MODEL = "deepseek-chat"


def get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set DEEPSEEK_API_KEY or OPENAI_API_KEY before running the template."
        )

    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)


def build_judge_prompt(question: str, answer_a: str, answer_b: str) -> str:
    return f"""你是一个公正的 AI 裁判。请判断两个回答中哪个更好。

请重点考察：
1. 最终答案是否准确。
2. 推理过程是否严密。
3. 是否掉入常见思维陷阱。

问题：{question}

【回答 A】
{answer_a}

【回答 B】
{answer_b}

你必须只输出 JSON，格式如下：
{{
  "winner": "A" 或 "B" 或 "Tie",
  "reason": "一句话说明理由"
}}
"""


def run_judge(question: str, answer_a: str, answer_b: str) -> dict:
    client = get_client()
    model_name = os.getenv("JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    prompt = build_judge_prompt(question, answer_a, answer_b)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个只输出 JSON 的机器。"},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)