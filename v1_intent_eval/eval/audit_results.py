"""
v1 结果审计脚本
===============
两层审计（借鉴 v2 _audit_v2_results.py）：
  1. 自动校验：数据完整性、字段一致性、通过率、异常检测
  2. 人工抽检：输出样本的完整模型回复，供人审查幻觉

用法：
  cd v1_intent_eval
  python scripts/_audit_v1_results.py                       # 审计最新 run
  python scripts/_audit_v1_results.py results/run_xxx.jsonl  # 审计指定文件
  python scripts/_audit_v1_results.py --all                  # 审计全部 run 文件
"""

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# 固定随机种子，保证可复现
random.seed(42)

lines_out: list[str] = []


def pr(s=""):
    lines_out.append(s)
    print(s)


def section(title):
    pr()
    pr("=" * 70)
    pr(title)
    pr("=" * 70)


def load_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    records, errors = [], []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"  Line {i+1}: {e}")
    return records, errors


def find_latest_run() -> Path | None:
    runs = sorted(RESULTS_DIR.glob("*/run_*.jsonl"))
    return runs[-1] if runs else None


def audit_file(path: Path):
    pr(f"审计文件: {path.name}")
    pr(f"路径: {path}")

    records, parse_errors = load_jsonl(path)

    # ========================================
    # 1. 数据完整性
    # ========================================
    section("1. 数据完整性校验")

    if parse_errors:
        pr(f"  [PARSE ERROR] {len(parse_errors)} lines failed:")
        for e in parse_errors:
            pr(e)
    else:
        pr(f"  [OK] {len(records)} records, no parse errors")

    if not records:
        pr("  [FATAL] 文件为空，终止审计")
        return

    # 基本统计
    models = set(r.get("target_model", "?") for r in records)
    pr(f"  模型: {models}")
    timestamps = [r.get("timestamp", "") for r in records]
    pr(f"  时间范围: {min(timestamps)} → {max(timestamps)}")

    # ========================================
    # 2. 字段一致性
    # ========================================
    section("2. 字段一致性检查")

    EXPECTED_INTENT = ["test", "input", "actual_output", "expected", "score",
                       "passed", "reason", "latency_ms", "timestamp", "target_model"]
    EXPECTED_STRUCT = ["test", "input", "actual_output", "expected",
                       "passed", "latency_ms", "timestamp", "target_model"]

    by_test = defaultdict(list)
    for r in records:
        by_test[r.get("test", "?")].append(r)

    for test_type, recs in by_test.items():
        expected_fields = EXPECTED_INTENT if test_type == "bloom_intent" else EXPECTED_STRUCT
        missing = defaultdict(int)
        for r in recs:
            for f in expected_fields:
                if f not in r:
                    missing[f] += 1
        if missing:
            pr(f"  [WARN] {test_type} ({len(recs)} records): missing fields")
            for f, cnt in missing.items():
                pr(f"    {f}: missing in {cnt}/{len(recs)}")
        else:
            pr(f"  [OK] {test_type}: {len(recs)} records, all fields present")

    # ========================================
    # 3. 通过率
    # ========================================
    section("3. 通过率统计")

    for test_type, recs in sorted(by_test.items()):
        passed = sum(1 for r in recs if r.get("passed"))
        total = len(recs)
        rate = passed / total * 100 if total else 0
        pr(f"  {test_type}: {passed}/{total} ({rate:.1f}%)")

    # Layer 1 按 difficulty 分
    intent_recs = by_test.get("bloom_intent", [])
    if intent_recs:
        pr("\n  Layer 1 (bloom_intent) by difficulty:")
        by_diff = defaultdict(lambda: {"p": 0, "f": 0})
        for r in intent_recs:
            d = r.get("difficulty", "?") or "?"
            by_diff[d]["p" if r["passed"] else "f"] += 1
        for d in ["easy", "medium", "hard", "?"]:
            if d in by_diff:
                v = by_diff[d]
                t = v["p"] + v["f"]
                pr(f"    {d:8s}: {v['p']}/{t} ({v['p']/t*100:.0f}%)")

    # ========================================
    # 4. 异常检测
    # ========================================
    section("4. 异常检测")

    anomalies = 0

    # 4a. score 异常（Layer 1）
    if intent_recs:
        no_score = [r for r in intent_recs if r.get("score") is None]
        if no_score:
            pr(f"  [WARN] {len(no_score)} intent records with score=None")
            anomalies += len(no_score)

        low_pass = [r for r in intent_recs if r.get("passed") and (r.get("score") or 0) < 0.5]
        if low_pass:
            pr(f"  [ANOMALY] {len(low_pass)} PASSED with score < 0.5 (可疑假阳性):")
            for r in low_pass[:3]:
                pr(f"    input: {r['input'][:50]} | score: {r.get('score')}")
            anomalies += len(low_pass)

        high_fail = [r for r in intent_recs if not r.get("passed") and (r.get("score") or 0) >= 0.65]
        if high_fail:
            pr(f"  [ANOMALY] {len(high_fail)} FAILED with score >= 0.65 (边界假阴性):")
            for r in high_fail[:3]:
                pr(f"    input: {r['input'][:50]} | score: {r.get('score')}")
            anomalies += len(high_fail)

    # 4b. 延迟异常
    latencies = [r.get("latency_ms", 0) for r in records if r.get("latency_ms")]
    if latencies:
        fast = [l for l in latencies if l < 300]
        slow = [l for l in latencies if l > 30000]
        avg = sum(latencies) / len(latencies)
        pr(f"\n  延迟: avg={avg:.0f}ms, min={min(latencies)}ms, max={max(latencies)}ms")
        if fast:
            pr(f"  [WARN] {len(fast)} cases < 300ms (suspiciously fast)")
            anomalies += len(fast)
        if slow:
            pr(f"  [WARN] {len(slow)} cases > 30s (very slow)")
            anomalies += len(slow)

    # 4c. 重复 input 检测
    inputs = [r["input"] for r in records]
    dup = {inp for inp in inputs if inputs.count(inp) > 1}
    # bloom_intent 和 structured_output 可能共用 input，只检查同 test 内重复
    for test_type, recs in by_test.items():
        test_inputs = [r["input"] for r in recs]
        test_dup = {inp for inp in test_inputs if test_inputs.count(inp) > 1}
        if test_dup:
            pr(f"  [WARN] {test_type}: {len(test_dup)} duplicate inputs")
            anomalies += len(test_dup)

    # 4d. Layer 2: JSON 解析失败
    struct_recs = by_test.get("structured_output", [])
    json_fails = [r for r in struct_recs if r.get("errors") and "invalid JSON" in str(r["errors"])]
    if json_fails:
        pr(f"  [ANOMALY] {len(json_fails)} structured_output with invalid JSON")
        anomalies += len(json_fails)

    if anomalies == 0:
        pr("  [OK] 未检测到异常")

    # ========================================
    # 5. 人工抽检样本
    # ========================================
    section("5. 人工抽检样本（请逐条审查模型回复）")

    pr("""
  审查指南：
  - 重点关注以下 AI 幻觉模式：
    (a) PASSED 但模型行为不对（假阳性）— 尤其 score 在 0.7 附近的
    (b) FAILED 但模型行为合理（假阴性）— 用例设计或 judge 偏差
    (c) 模型编造时间（如输入"明早"→ 模型自行决定7:00/8:00）
    (d) 该追问但直接执行的（缺参数时不追问）
    (e) Judge reason 与 score 自相矛盾
""")

    if intent_recs:
        pr("  --- Layer 1 (bloom_intent) 抽检 ---")
        passed_list = [r for r in intent_recs if r["passed"]]
        failed_list = [r for r in intent_recs if not r["passed"]]

        # 抽 3 passed + 3 failed（或全部，如果不够）
        sample = (random.sample(passed_list, min(3, len(passed_list)))
                  + random.sample(failed_list, min(3, len(failed_list))))

        for i, r in enumerate(sample, 1):
            status = "PASS" if r["passed"] else "FAIL"
            pr(f"\n  [{i}] {status} | score={r.get('score')} | diff={r.get('difficulty','?')} | latency={r.get('latency_ms')}ms")
            pr(f"  Input:    {r['input']}")
            pr(f"  Expected: {r['expected'][:150]}")
            pr(f"  Actual:   {r['actual_output'][:200]}")
            pr(f"  Reason:   {(r.get('reason') or '')[:200]}")
            pr(f"  ▶ 你的判断：[  ] 合理  [  ] 有问题（请标注）")

    if struct_recs:
        pr("\n  --- Layer 2 (structured_output) 全量检查 ---")
        for i, r in enumerate(struct_recs, 1):
            status = "PASS" if r["passed"] else "FAIL"
            pr(f"\n  [{i}] {status} | latency={r.get('latency_ms')}ms")
            pr(f"  Input:  {r['input']}")
            pr(f"  Output: {r['actual_output'][:300]}")
            if r.get("errors"):
                pr(f"  Errors: {r['errors']}")
            pr(f"  ▶ 你的判断：[  ] 合理  [  ] 有问题（请标注）")

    # ========================================
    # 6. 与历史快照对比
    # ========================================
    baseline = RESULTS_DIR / "results.jsonl"
    if baseline.exists() and path != baseline:
        section("6. 与历史快照对比 (results.jsonl)")
        base_records, _ = load_jsonl(baseline)
        if base_records:
            base_pass = sum(1 for r in base_records if r.get("passed"))
            base_total = len(base_records)
            curr_intent = by_test.get("bloom_intent", [])
            curr_pass = sum(1 for r in curr_intent if r.get("passed"))
            curr_total = len(curr_intent)

            pr(f"  历史快照: {base_pass}/{base_total} ({base_pass/base_total*100:.1f}%)")
            pr(f"  本次运行: {curr_pass}/{curr_total} ({curr_pass/curr_total*100:.1f}%)")

            # 按 input 对比
            base_by_input = {r["input"]: r.get("passed") for r in base_records
                             if r.get("test") == "bloom_intent"}
            regressions = []
            improvements = []
            for r in curr_intent:
                inp = r["input"]
                if inp in base_by_input:
                    if base_by_input[inp] and not r["passed"]:
                        regressions.append(inp)
                    elif not base_by_input[inp] and r["passed"]:
                        improvements.append(inp)

            if regressions:
                pr(f"\n  [REGRESSION] {len(regressions)} cases 从 PASS → FAIL:")
                for inp in regressions:
                    pr(f"    {inp[:60]}")
            if improvements:
                pr(f"\n  [IMPROVED] {len(improvements)} cases 从 FAIL → PASS:")
                for inp in improvements:
                    pr(f"    {inp[:60]}")
            if not regressions and not improvements:
                pr("  [OK] 无回归/改进（或 input 不匹配）")

    # ========================================
    # 写报告
    # ========================================
    report_path = path.parent / f"audit_{path.stem}.txt"
    report_path.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\n报告已保存到: {report_path}")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--all":
            runs = sorted(RESULTS_DIR.glob("*/run_*.jsonl"))
            if not runs:
                print("没有找到 run_*.jsonl 文件")
                return
            for p in runs:
                lines_out.clear()
                audit_file(p)
        else:
            p = Path(arg)
            if not p.is_absolute():
                p = RESULTS_DIR / arg
            if not p.exists():
                print(f"文件不存在: {p}")
                return
            audit_file(p)
    else:
        latest = find_latest_run()
        if latest:
            audit_file(latest)
        else:
            print("没有找到 run_*.jsonl 文件。请先运行 pytest test_schedule_eval.py")


if __name__ == "__main__":
    main()
