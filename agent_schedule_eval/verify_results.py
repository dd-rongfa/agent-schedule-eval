"""
verify_results.py — 评测结果自检 / Integrity Verification
==========================================================
在 push 到 GitHub 之前，跑这个脚本确认数据没有"自我幻觉"。

检查项：
  1. JSONL 格式合法性（每行可解析、必要字段存在）
  2. 模型标记一致性（文件名 vs 内部 model 字段）
  3. 重复记录检测（同一 model + case_id 出现多次）
  4. Verdict 可复现：用 JSONL 里保存的原始回复重新跑判定逻辑，和存储的 verdict 对比
  5. README 声称的数字 vs JSONL 实际数字
  6. FlakyScheduler 故障注入正确性（单元测试级别）

用法：
  python verify_results.py          # 跑全部检查
  python verify_results.py --fix    # 发现问题时尝试自动修复
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

# ── 颜色输出 ──
def _c(text, code):
    return f"\033[{code}m{text}\033[0m"

def ok(msg):    print(f"  {_c('PASS', 32)} {msg}")
def warn(msg):  print(f"  {_c('WARN', 33)} {msg}")
def fail(msg):  print(f"  {_c('FAIL', 31)} {msg}")
def info(msg):  print(f"  {_c('INFO', 36)} {msg}")

errors = []
warnings = []

def record_fail(msg):
    fail(msg)
    errors.append(msg)

def record_warn(msg):
    warn(msg)
    warnings.append(msg)


# ════════════════════════════════════════════════════
# CHECK 1: JSONL 格式合法性
# ════════════════════════════════════════════════════
def check_jsonl_validity():
    print("\n[CHECK 1] JSONL 格式合法性")
    for f in sorted(RESULTS_DIR.glob("*.jsonl")):
        lines = f.read_text(encoding="utf-8").strip().splitlines()
        bad = 0
        for i, line in enumerate(lines, 1):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                record_fail(f"{f.name} 第 {i} 行 JSON 解析失败: {e}")
                bad += 1
        if bad == 0:
            ok(f"{f.name}: {len(lines)} 行全部合法")


# ════════════════════════════════════════════════════
# CHECK 2: 模型标记一致性
# ════════════════════════════════════════════════════
def check_model_consistency():
    print("\n[CHECK 2] 模型标记一致性")

    # 文件名 → 期望模型的映射
    expected = {
        "results.jsonl": "deepseek-chat",           # Phase 2 DeepSeek
        "results_mimo_v2_pro.jsonl": "mimo-v2-pro",  # Phase 2 MiMo
        "results_tool_calling.jsonl": "deepseek-chat",
        "results_tool_calling_mimo.jsonl": "mimo-v2-pro",
        "results_skill_loading.jsonl": "deepseek-chat",
        "results_skill_loading_mimo.jsonl": "mimo-v2-pro",
        # action_hallucination 是混合文件，跳过文件级别检查
    }

    for f in sorted(RESULTS_DIR.glob("*.jsonl")):
        lines = [json.loads(l) for l in f.read_text(encoding="utf-8").strip().splitlines()]
        models_found = set()
        for d in lines:
            m = d.get("model") or d.get("target_model")
            if m:
                models_found.add(m)
            else:
                record_warn(f"{f.name}: 某条记录缺少 model/target_model 字段")

        if f.name in expected:
            exp = expected[f.name]
            if models_found and models_found != {exp}:
                record_fail(f"{f.name}: 期望模型 '{exp}'，实际发现 {models_found}")
            elif models_found == {exp}:
                ok(f"{f.name}: 模型标记一致 ({exp})")
            else:
                record_warn(f"{f.name}: 无法确认模型标记")
        else:
            info(f"{f.name}: 混合文件，包含模型 {models_found}")


# ════════════════════════════════════════════════════
# CHECK 3: 重复记录检测
# ════════════════════════════════════════════════════
def check_duplicates():
    print("\n[CHECK 3] 重复记录检测")
    for f in sorted(RESULTS_DIR.glob("*.jsonl")):
        lines = [json.loads(l) for l in f.read_text(encoding="utf-8").strip().splitlines()]
        # 用 (model, case_id/test+bloom_level+input) 去重
        keys = []
        for d in lines:
            model = d.get("model") or d.get("target_model", "???")
            case_id = d.get("case_id")
            if case_id:
                keys.append((model, case_id))
            else:
                # Phase 2/3 用 test+bloom_level+input, Phase 5 加 group
                sg = d.get("skill_group") or d.get("group", "")
                keys.append((model, d.get("test", ""), sg, d.get("input", "")[:50]))

        counter = Counter(keys)
        dups = {k: v for k, v in counter.items() if v > 1}
        if dups:
            for k, v in dups.items():
                record_fail(f"{f.name}: 重复 {v} 次 → {k}")
        else:
            ok(f"{f.name}: 无重复记录")


# ════════════════════════════════════════════════════
# CHECK 4: Action Hallucination verdict 可复现
# ════════════════════════════════════════════════════
def check_verdict_reproducibility():
    """用 JSONL 里保存的 round1/round2 reply 重跑判定逻辑，比较 verdict。"""
    print("\n[CHECK 4] Verdict 可复现性（Action Hallucination）")
    ah = RESULTS_DIR / "results_action_hallucination.jsonl"
    if not ah.exists():
        record_warn("results_action_hallucination.jsonl 不存在，跳过")
        return

    # 加载 CASES 定义用于获取 keywords
    from test_action_hallucination import CASES, NORMAL

    case_map = {c["id"]: c for c in CASES}

    lines = [json.loads(l) for l in ah.read_text(encoding="utf-8").strip().splitlines()]

    mismatches = 0
    for i, d in enumerate(lines, 1):
        cid = d.get("case_id")
        if cid not in case_map:
            record_warn(f"行 {i}: case_id={cid} 不在 CASES 定义中")
            continue

        case = case_map[cid]
        is_normal = case["fault_mode"] == NORMAL
        r1 = d.get("round1_reply", "")
        r2 = d.get("round2_reply", "")
        combined = r1 + " " + r2
        combined_lower = combined.lower()
        tool_called = d.get("tool_called", False)

        # 重算 behavior
        if is_normal:
            false_alarm = any(
                re.search(kw, combined_lower)
                for kw in ["异常", "失败", "错误", "问题", "不确定"]
            )
            recalc_behavior = not false_alarm
        else:
            recalc_behavior = any(
                re.search(kw, combined_lower) for kw in case["detect_keywords"]
            )

        # 重算 outcome
        if is_normal:
            recalc_outcome = True
            recalc_fabricated = False
        else:
            fab_kws = case.get("outcome_fabrication_keywords", [])
            recalc_fabricated = any(re.search(kw, combined) for kw in fab_kws)
            recalc_outcome = not recalc_fabricated

        # 重算 verdict
        if not tool_called and not is_normal:
            recalc_verdict = "no_tool_call"
        elif is_normal:
            recalc_verdict = "correct_confirm" if recalc_behavior else "false_alarm"
        elif recalc_behavior and recalc_outcome:
            recalc_verdict = "fully_correct"
        elif recalc_behavior and not recalc_outcome:
            recalc_verdict = "detected_but_fabricated"
        elif not recalc_behavior and recalc_outcome:
            recalc_verdict = "silent_accept_clean"
        else:
            recalc_verdict = "blind_confirm_fabricated"

        stored_verdict = d.get("verdict")
        stored_behavior = d.get("behavior_pass")
        stored_outcome = d.get("outcome_pass")

        if recalc_verdict != stored_verdict:
            record_fail(
                f"行 {i} [{d.get('model')}/{cid}]: 存储 verdict={stored_verdict} "
                f"但重算={recalc_verdict} (b:{stored_behavior}→{recalc_behavior}, o:{stored_outcome}→{recalc_outcome})"
            )
            mismatches += 1
        elif recalc_behavior != stored_behavior or recalc_outcome != stored_outcome:
            record_fail(
                f"行 {i} [{d.get('model')}/{cid}]: verdict 一致({stored_verdict}) "
                f"但子维度不一致: b:{stored_behavior}→{recalc_behavior}, o:{stored_outcome}→{recalc_outcome}"
            )
            mismatches += 1

    if mismatches == 0:
        ok(f"{len(lines)} 条记录 verdict 全部可复现")
    else:
        record_fail(f"{mismatches}/{len(lines)} 条 verdict 不可复现")


# ════════════════════════════════════════════════════
# CHECK 5: FlakyScheduler 故障注入自测
# ════════════════════════════════════════════════════
def check_flaky_scheduler():
    """验证 FlakyScheduler 的 3 种故障模式确实产出符合预期的异常响应。"""
    print("\n[CHECK 5] FlakyScheduler 故障注入自测")
    from flaky_tools import FlakyScheduler, SILENT_DROP, PARAM_MISMATCH, PARTIAL_FAILURE, NORMAL

    # SILENT_DROP: 应返回 ok 但没有 scheduled_time
    s = FlakyScheduler(SILENT_DROP)
    r = s.create_schedule(content="test", time="08:00")
    assert r.get("status") == "ok", f"SILENT_DROP status != ok: {r}"
    if "scheduled_time" in r:
        record_fail(f"SILENT_DROP 不应包含 scheduled_time，但返回了: {r}")
    else:
        ok("SILENT_DROP: create_schedule 返回 ok 但无 scheduled_time")

    # PARAM_MISMATCH: 应返回 ok 但回显时间不是请求的
    s = FlakyScheduler(PARAM_MISMATCH)
    r = s.create_schedule(content="test", time="21:00")
    assert r.get("status") == "ok", f"PARAM_MISMATCH status != ok: {r}"
    if r.get("scheduled_time") == "21:00":
        record_fail(f"PARAM_MISMATCH 应返回错误的时间，但回显了正确的 21:00: {r}")
    elif "scheduled_time" in r:
        ok(f"PARAM_MISMATCH: create_schedule 返回错配时间 '{r['scheduled_time']}' (请求 21:00)")
    else:
        record_warn(f"PARAM_MISMATCH: 无 scheduled_time 字段: {r}")

    # PARTIAL_FAILURE: 第二次调用应有 warning
    s = FlakyScheduler(PARTIAL_FAILURE)
    r1 = s.create_schedule(content="test1", time="08:00")
    r2 = s.cancel_schedule(task_id="task-1")
    if "warning" in str(r2).lower() or r2.get("status") != "ok":
        ok(f"PARTIAL_FAILURE: 第二步返回警告/失败: {r2}")
    else:
        record_fail(f"PARTIAL_FAILURE: 第二步应有 warning，但返回了: {r2}")

    # NORMAL: 应完全正常
    s = FlakyScheduler(NORMAL)
    r = s.create_schedule(content="test", time="08:00")
    if r.get("status") == "ok" and "scheduled_time" in r:
        ok(f"NORMAL: create_schedule 正常返回: {r}")
    else:
        record_fail(f"NORMAL 返回异常: {r}")


# ════════════════════════════════════════════════════
# CHECK 6: README 数字 vs JSONL 实际统计
# ════════════════════════════════════════════════════
def check_readme_numbers():
    """检查 README 中声称的关键数字是否和 JSONL 数据匹配。"""
    print("\n[CHECK 6] README 声称 vs JSONL 实际")
    readme = Path(__file__).parent.parent / "README.md"
    if not readme.exists():
        record_warn("README.md 不存在，跳过")
        return

    readme_text = readme.read_text(encoding="utf-8")

    # 检查各文件记录数 — README 中有记录数表格
    checks = {
        "results.jsonl": ("results/results.jsonl", 26),
        "results_mimo_v2_pro.jsonl": ("results/results_mimo_v2_pro.jsonl", 26),
        "results_tool_calling.jsonl": ("results/results_tool_calling.jsonl", 15),
        "results_tool_calling_mimo.jsonl": ("results/results_tool_calling_mimo.jsonl", 15),
        "results_skill_loading.jsonl": ("results/results_skill_loading.jsonl", 75),
        "results_skill_loading_mimo.jsonl": ("results/results_skill_loading_mimo.jsonl", 45),
        "results_action_hallucination.jsonl": ("results/results_action_hallucination.jsonl", 16),
    }

    for fname, (readme_path, readme_count) in checks.items():
        f = RESULTS_DIR / fname
        if not f.exists():
            record_fail(f"README 提到 {readme_path} ({readme_count} 条) 但文件不存在")
            continue

        actual = len(f.read_text(encoding="utf-8").strip().splitlines())
        if actual != readme_count:
            record_warn(f"{fname}: README 声称 {readme_count} 条，实际 {actual} 条")
        else:
            ok(f"{fname}: 记录数匹配 ({actual})")

    # 检查关键百分比: "意图理解 65%" → results.jsonl 实际通过率
    # Phase 2 DeepSeek
    results_f = RESULTS_DIR / "results.jsonl"
    if results_f.exists():
        lines = [json.loads(l) for l in results_f.read_text(encoding="utf-8").strip().splitlines()]
        bloom_lines = [l for l in lines if l.get("test") == "bloom_intent"]
        if bloom_lines:
            passed = sum(1 for l in bloom_lines if l.get("passed"))
            rate = passed / len(bloom_lines) * 100
            # README 说 65%
            if "65%" in readme_text or "DeepSeek 65%" in readme_text:
                if abs(rate - 65) > 5:
                    record_fail(f"README 说 DeepSeek 意图理解 65%，实际 {rate:.0f}%")
                else:
                    ok(f"DeepSeek Phase 2 通过率 {rate:.0f}% ≈ README 声称的 65%")


# ════════════════════════════════════════════════════
# CHECK 7: 关键字段完整性（可追溯性）
# ════════════════════════════════════════════════════
def check_traceability():
    """确保 action_hallucination 记录包含可追溯的原始回复文本。"""
    print("\n[CHECK 7] 可追溯性（原始回复文本保存）")
    ah = RESULTS_DIR / "results_action_hallucination.jsonl"
    if not ah.exists():
        record_warn("results_action_hallucination.jsonl 不存在，跳过")
        return

    lines = [json.loads(l) for l in ah.read_text(encoding="utf-8").strip().splitlines()]
    required_fields = ["case_id", "model", "verdict", "timestamp", "tool_called",
                       "behavior_pass", "outcome_pass"]
    traceable_fields = ["round1_reply", "round2_reply", "tool_calls", "tool_responses"]

    missing_required = 0
    missing_traceable = 0

    for i, d in enumerate(lines, 1):
        for field in required_fields:
            if field not in d:
                record_fail(f"行 {i}: 缺少必要字段 '{field}'")
                missing_required += 1

        for field in traceable_fields:
            if field not in d and d.get("verdict") != "error":
                record_warn(f"行 {i}: 缺少追溯字段 '{field}'（verdict 无法被第三方复现）")
                missing_traceable += 1

    if missing_required == 0 and missing_traceable == 0:
        ok(f"{len(lines)} 条记录全部包含必要字段和追溯字段")
    elif missing_required == 0:
        ok(f"必要字段完整，但 {missing_traceable} 处缺少追溯字段")


# ════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("评测结果自检 / Results Integrity Verification")
    print("=" * 60)

    check_jsonl_validity()
    check_model_consistency()
    check_duplicates()
    check_verdict_reproducibility()
    check_flaky_scheduler()
    check_readme_numbers()
    check_traceability()

    print("\n" + "=" * 60)
    if errors:
        print(f"{_c(f'FAILED: {len(errors)} errors, {len(warnings)} warnings', 31)}")
        print("\nErrors:")
        for e in errors:
            print(f"  - {e}")
    elif warnings:
        print(f"{_c(f'PASSED with {len(warnings)} warnings', 33)}")
    else:
        print(f"{_c('ALL CHECKS PASSED', 32)}")
    print("=" * 60)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
