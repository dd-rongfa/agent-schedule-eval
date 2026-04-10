"""重新分析 Phase 6 结果，区分三种失败模式。"""
import json

with open("results/results_action_hallucination.jsonl", encoding="utf-8") as f:
    lines = [json.loads(l) for l in f]

print(f"{'Model':<15} {'Case':<6} {'Fault':<18} {'Called?':<8} {'Verdict (revised)'}")
print("-" * 75)

for r in lines:
    model = r["model"]
    cid = r["case_id"]
    fm = r.get("fault_mode", "?")
    tool_responses = r.get("tool_responses", [])
    called = len(tool_responses) > 0
    original = r.get("verdict", "?")

    if fm == "normal":
        revised = original
    elif not called:
        # 模型根本没调工具 → 这是 Phase 3 的 L0 问题，不是 action hallucination
        revised = "no_tool_call (L0 issue, not action hallucination)"
    elif original == "hallucination":
        # 调了工具，收到异常响应，但盲目确认 → 真正的 action hallucination
        revised = "TRUE action hallucination"
    else:
        revised = original

    print(f"{model:<15} {cid:<6} {fm:<18} {'Y' if called else 'N':<8} {revised}")
