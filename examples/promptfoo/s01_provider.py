import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import s01_simple_judge as s01  # noqa: E402


def call_api(prompt, options, context):
    vars_data = context.get("vars", {})
    question = vars_data.get("question", "")
    answer_a = vars_data.get("answer_a", "")
    answer_b = vars_data.get("answer_b", "")

    judge_prompt = s01.get_judge_prompt(question, answer_a, answer_b)

    response = s01.client.chat.completions.create(
        model=s01.JUDGE_MODEL,
        messages=[
            {"role": "system", "content": "你是一个只输出 JSON 的机器。"},
            {"role": "user", "content": judge_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    judge_result = json.loads(response.choices[0].message.content)
    payload = {
        "question": question,
        "winner": judge_result.get("winner"),
        "reason": judge_result.get("reason"),
    }

    return {
        "output": json.dumps(payload, ensure_ascii=False),
    }