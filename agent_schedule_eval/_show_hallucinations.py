import json

with open("results/results_action_hallucination.jsonl", encoding="utf-8") as f:
    lines = [json.loads(l) for l in f]

for r in lines:
    if r.get("verdict") == "hallucination":
        model = r["model"]
        cid = r["case_id"]
        fm = r["fault_mode"]
        print(f"=== {model} | {cid} ({fm}) ===")
        print(f"User: {r['user_request']}")
        tr = json.dumps(r.get("tool_responses", []), ensure_ascii=False, indent=2)
        print(f"Tool responses: {tr}")
        print(f"Round1 reply: {r.get('round1_reply', '')[:300]}")
        print(f"Followup: {r['followup']}")
        print(f"Round2 reply: {r.get('round2_reply', '')[:300]}")
        print()
