import json

from judge_logic import run_judge


def call_api(prompt, options, context):
    vars_data = context.get("vars", {})

    question = vars_data["question"]
    answer_a = vars_data["answer_a"]
    answer_b = vars_data["answer_b"]

    result = run_judge(question, answer_a, answer_b)
    payload = {
        "question": question,
        "winner": result.get("winner"),
        "reason": result.get("reason"),
    }

    return {
        "output": json.dumps(payload, ensure_ascii=False),
        "cached": False,
        "cost": 0,
    }