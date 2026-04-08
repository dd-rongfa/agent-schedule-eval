import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import s02_blind_judge as s02  # noqa: E402


def call_api(prompt, options, context):
    vars_data = context.get("vars", {})
    question = vars_data.get("question", prompt)

    ans_v3 = s02.get_answer(s02.MODEL_NORMAL, question)
    ans_r1 = s02.get_answer(s02.MODEL_REASONER, question)

    judge_1 = s02.run_judge(question, ans_v3, ans_r1)
    judge_2 = s02.run_judge(question, ans_r1, ans_v3)

    final_winner = "Tie"
    if judge_1.get("winner") == "B" and judge_2.get("winner") == "A":
        final_winner = "R1"
    elif judge_1.get("winner") == "A" and judge_2.get("winner") == "B":
        final_winner = "V3"

    payload = {
        "question": question,
        "v3_answer": ans_v3,
        "r1_answer": ans_r1,
        "judge_1": judge_1,
        "judge_2": judge_2,
        "final_winner": final_winner,
    }

    return {
        "output": json.dumps(payload, ensure_ascii=False),
    }