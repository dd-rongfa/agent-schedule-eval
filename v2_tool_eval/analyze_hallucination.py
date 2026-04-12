"""
幻觉鲁棒性分析：从 results/hallucination/{model}/ 聚合多轮多温度实验结果
================================================================
分析维度：
  1. B (行为检测率) / O (结果准确率) 均值±标准差
  2. verdict 分布 (fully_correct / detected_but_fabricated / silent_accept_clean / blind_confirm_fabricated / no_tool_call)
  3. 温度对比 (t=0.1 vs t=0.7)
  4. case-level verdict 稳定性 (跨多轮同 case verdict 是否一致)
  5. Normal 对照组通过率

目录结构：
  results/hallucination/
    {model}/
      t{temp}_{timestamp}.jsonl    ← 每次 run 一个文件
    merged.jsonl                   ← test script 自动合并的最新快照

用法：
  python analyze_hallucination.py                   # 终端文本输出
  python analyze_hallucination.py --json             # 输出 JSON (可审计)
  python analyze_hallucination.py --report           # 写入 results/report_action_hallucination.md
  python analyze_hallucination.py --latest 3         # 每 model×temp 取最新 3 轮 (默认: 全部)
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
HALLUCINATION_DIR = RESULTS_DIR / "hallucination"
REPORT_PATH = RESULTS_DIR / "report_action_hallucination.md"


# ── 数据加载 ──────────────────────────────────────


def discover_runs() -> dict[tuple[str, float], list[Path]]:
    """扫描 results/hallucination/{model}/t*.jsonl，返回 {(model, temp): [sorted files]}。"""
    groups: dict[tuple[str, float], list[Path]] = defaultdict(list)
    if not HALLUCINATION_DIR.exists():
        return {}
    for model_dir in sorted(HALLUCINATION_DIR.iterdir()):
        if not model_dir.is_dir():
            continue
        for f in sorted(model_dir.glob("t*.jsonl")):
            temp_str, _ts = f.stem.split("_", 1)
            temp = float(temp_str[1:])  # "t0.1" -> 0.1
            groups[(model_dir.name, temp)].append(f)
    return dict(groups)


def load_run(filepath: Path) -> list[dict]:
    records = []
    for line in filepath.read_text("utf-8").strip().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def pick_latest_n(files: list[Path], n: int | None) -> list[Path]:
    """取最新 N 个文件（按文件名降序）。None = 全部。"""
    sorted_files = sorted(files, key=lambda p: p.name, reverse=True)
    if n is None:
        return sorted_files
    return sorted_files[:n]


# ── 单次分析 ──────────────────────────────────────


def analyze_one_run(records: list[dict]) -> dict:
    """分析一次 run (10 case) 的 fault cases。"""
    fault = [r for r in records if r.get("fault_mode") != "normal"]
    normal = [r for r in records if r.get("fault_mode") == "normal"]

    n = len(fault) if fault else 1
    b_pass = sum(1 for r in fault if r.get("behavior_pass"))
    o_pass = sum(1 for r in fault if r.get("outcome_pass"))

    verdicts = defaultdict(int)
    for r in fault:
        verdicts[r["verdict"]] += 1

    latencies = [r["latency_ms"] for r in records if r.get("latency_ms")]
    avg_latency = sum(latencies) / len(latencies) / 1000 if latencies else 0

    # 验证意图统计
    v_intent = sum(1 for r in fault if r.get("verification_intent"))
    turns = [r.get("turns", 0) for r in records if r.get("turns")]
    avg_turns = sum(turns) / len(turns) if turns else 0

    # 对照组
    normal_correct = sum(1 for r in normal if r.get("verdict") == "correct_confirm")

    return {
        "fault_total": len(fault),
        "normal_total": len(normal),
        "b_rate": b_pass / n * 100,
        "o_rate": o_pass / n * 100,
        "verdicts": dict(verdicts),
        "avg_latency_s": round(avg_latency, 1),
        "verification_intent_pct": v_intent / n * 100 if n else 0,
        "avg_turns": round(avg_turns, 1),
        "normal_correct": normal_correct,
        "normal_rate": normal_correct / len(normal) * 100 if normal else 100,
        "case_verdicts": {r["case_id"]: r["verdict"] for r in fault},
    }


# ── 多轮聚合 ──────────────────────────────────────


def aggregate_runs(run_stats: list[dict]) -> dict:
    n = len(run_stats)
    if n == 0:
        return {}

    def _mean_std(values):
        m = sum(values) / len(values)
        if len(values) > 1:
            s = math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))
        else:
            s = 0.0
        return round(m, 1), round(s, 1)

    b_rates = [s["b_rate"] for s in run_stats]
    o_rates = [s["o_rate"] for s in run_stats]
    b_mean, b_std = _mean_std(b_rates)
    o_mean, o_std = _mean_std(o_rates)

    # 合并 verdict 计数
    all_verdicts = defaultdict(int)
    for s in run_stats:
        for v, c in s["verdicts"].items():
            all_verdicts[v] += c

    latencies = [s["avg_latency_s"] for s in run_stats]
    v_intents = [s["verification_intent_pct"] for s in run_stats]
    turns = [s["avg_turns"] for s in run_stats]
    normal_rates = [s["normal_rate"] for s in run_stats]

    # case-level 稳定性
    case_across_runs = defaultdict(list)
    for s in run_stats:
        for cid, v in s["case_verdicts"].items():
            case_across_runs[cid].append(v)
    total_cases = len(case_across_runs)
    stable_cases = sum(1 for vs in case_across_runs.values() if len(set(vs)) == 1)
    unstable_detail = {
        cid: vs for cid, vs in sorted(case_across_runs.items()) if len(set(vs)) > 1
    }

    return {
        "n_runs": n,
        "b_mean": b_mean,
        "b_std": b_std,
        "o_mean": o_mean,
        "o_std": o_std,
        "verdicts": dict(all_verdicts),
        "avg_latency_s": round(sum(latencies) / n, 1),
        "verification_intent_pct": round(sum(v_intents) / n, 1),
        "avg_turns": round(sum(turns) / n, 1),
        "normal_rate": round(sum(normal_rates) / n, 1),
        "stability": {
            "total_cases": total_cases,
            "stable": stable_cases,
            "stable_pct": round(stable_cases / total_cases * 100) if total_cases else 0,
            "unstable": unstable_detail,
        },
    }


# ── 输出格式 ──────────────────────────────────────


def print_text(all_results: dict, temps: list[float]) -> None:
    models = sorted({k[0] for k in all_results})

    for temp in temps:
        print(f"\n{'='*60}")
        print(f"Temperature = {temp}")
        print(f"{'='*60}")
        for model in models:
            key = (model, temp)
            if key not in all_results:
                continue
            a = all_results[key]
            n = a["n_runs"]
            b_str = f"{a['b_mean']:.1f}% ± {a['b_std']:.1f}%" if n > 1 else f"{a['b_mean']:.1f}%"
            o_str = f"{a['o_mean']:.1f}% ± {a['o_std']:.1f}%" if n > 1 else f"{a['o_mean']:.1f}%"
            print(f"\n  {model} ({n} runs)")
            print(f"    B (行为检测): {b_str}")
            print(f"    O (结果准确): {o_str}")
            v = a["verdicts"]
            fc = v.get("fully_correct", 0)
            df = v.get("detected_but_fabricated", 0)
            sa = v.get("silent_accept_clean", 0)
            bc = v.get("blind_confirm_fabricated", 0)
            ntc = v.get("no_tool_call", 0)
            print(f"    Verdict: FC={fc} D+F={df} SA={sa} BC={bc} NTC={ntc}")
            print(f"    延迟: {a['avg_latency_s']}s  平均轮次: {a['avg_turns']}")
            stab = a["stability"]
            print(f"    稳定性: {stab['stable']}/{stab['total_cases']} ({stab['stable_pct']}%)")
            if stab["unstable"]:
                for cid, vs in stab["unstable"].items():
                    print(f"      {cid}: {vs}")
            print(f"    Normal 对照: {a['normal_rate']:.0f}%")

    # 温度对比
    if len(temps) >= 2:
        print(f"\n{'='*60}")
        print("温度对比")
        print(f"{'='*60}")
        for model in models:
            k1, k7 = (model, temps[0]), (model, temps[1])
            if k1 in all_results and k7 in all_results:
                a1, a7 = all_results[k1], all_results[k7]
                db = a7["b_mean"] - a1["b_mean"]
                do = a7["o_mean"] - a1["o_mean"]
                print(f"  {model}")
                print(f"    B: {a1['b_mean']:.0f}±{a1['b_std']:.0f}% → {a7['b_mean']:.0f}±{a7['b_std']:.0f}% (Δ={db:+.0f}%)")
                print(f"    O: {a1['o_mean']:.0f}±{a1['o_std']:.0f}% → {a7['o_mean']:.0f}±{a7['o_std']:.0f}% (Δ={do:+.0f}%)")
                print(f"    稳定性: {a1['stability']['stable_pct']}% → {a7['stability']['stable_pct']}%")


def format_report(all_results: dict, temps: list[float]) -> str:
    """生成 Markdown 报告。"""
    lines = []
    models = sorted({k[0] for k in all_results})
    ts_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_runs = next(iter(all_results.values()))["n_runs"]

    lines.append("# Action Hallucination Detection — 异常鲁棒性评测报告")
    lines.append("")
    lines.append(f"> 自动生成 @ {ts_now}  |  每 model×temp 取最新 {n_runs} 轮")
    lines.append(f"> 实验矩阵: {len(models)} 模型 × {len(temps)} 温度 × {n_runs} 轮 = {len(models)*len(temps)*n_runs} runs")
    lines.append("")

    # ── 设计概述 ──
    lines.append("## 设计")
    lines.append("")
    lines.append("v2 评测工具调用能力有两个维度：**正向执行力**（70 case）和**异常鲁棒性**（10 case）。")
    lines.append("共享同一套基础设施（agent_loop、20 工具、ToolDispatcher），区别仅在后端是正常的还是注入了故障。")
    lines.append("")
    lines.append("- **4 种故障模式**：Silent Drop / Param Mismatch / Content Mismatch / Partial Failure")
    lines.append("- **双维度评判**：B (行为检测 — 模型发现异常了吗) × O (结果准确 — 模型告诉用户的信息对吗)")
    lines.append("- **温度对比**：t=0.1 (确定性) vs t=0.7 (高温随机)，验证检测能力是否依赖采样策略")
    lines.append("- **多轮稳定性**：每个 model×temp 跑 3 轮，检查 case-level verdict 一致性")
    lines.append("")

    # ── 主表 ──
    lines.append("## 主表：行为检测率 (B) 与结果准确率 (O)")
    lines.append("")
    header = "| 模型 | Temp | B (行为检测) | O (结果准确) | FC | D+F | SA | BC | NTC | 稳定性 | 延迟 |"
    sep    = "|------|------|-------------|-------------|----|----|----|----|-----|--------|------|"
    lines.append(header)
    lines.append(sep)
    for temp in temps:
        for model in models:
            key = (model, temp)
            if key not in all_results:
                continue
            a = all_results[key]
            v = a["verdicts"]
            b_str = f"{a['b_mean']:.0f}±{a['b_std']:.0f}%"
            o_str = f"{a['o_mean']:.0f}±{a['o_std']:.0f}%"
            stab = f"{a['stability']['stable_pct']}%"
            fc = v.get("fully_correct", 0)
            df = v.get("detected_but_fabricated", 0)
            sa = v.get("silent_accept_clean", 0)
            bc = v.get("blind_confirm_fabricated", 0)
            ntc = v.get("no_tool_call", 0)
            short = model.replace("doubao-seed-2-0-pro-260215", "doubao")
            lines.append(f"| {short} | {temp} | {b_str} | {o_str} | {fc} | {df} | {sa} | {bc} | {ntc} | {stab} | {a['avg_latency_s']}s |")
    lines.append("")

    # ── 温度对比 ──
    if len(temps) >= 2:
        lines.append("## 温度对比：t=0.1 → t=0.7")
        lines.append("")
        lines.append("| 模型 | B Δ | O Δ | 稳定性 Δ |")
        lines.append("|------|-----|-----|----------|")
        for model in models:
            k1, k7 = (model, temps[0]), (model, temps[1])
            if k1 in all_results and k7 in all_results:
                a1, a7 = all_results[k1], all_results[k7]
                db = a7["b_mean"] - a1["b_mean"]
                do = a7["o_mean"] - a1["o_mean"]
                ds = a7["stability"]["stable_pct"] - a1["stability"]["stable_pct"]
                short = model.replace("doubao-seed-2-0-pro-260215", "doubao")
                lines.append(f"| {short} | {db:+.0f}% | {do:+.0f}% | {ds:+.0f}% |")
        lines.append("")

    # ── 稳定性明细 ──
    lines.append("## Case-level 稳定性")
    lines.append("")
    for temp in temps:
        lines.append(f"### t={temp}")
        lines.append("")
        for model in models:
            key = (model, temp)
            if key not in all_results:
                continue
            a = all_results[key]
            stab = a["stability"]
            short = model.replace("doubao-seed-2-0-pro-260215", "doubao")
            lines.append(f"**{short}**: {stab['stable']}/{stab['total_cases']} stable ({stab['stable_pct']}%)")
            if stab["unstable"]:
                for cid, vs in stab["unstable"].items():
                    lines.append(f"- {cid}: {' → '.join(vs)}")
            lines.append("")

    # ── 核心发现 ──
    lines.append("## 核心发现")
    lines.append("")

    # 自动提取排名
    t01_results = [(m, all_results[(m, temps[0])]) for m in models if (m, temps[0]) in all_results]
    t01_by_b = sorted(t01_results, key=lambda x: x[1]["b_mean"], reverse=True)

    lines.append(f"1. **行为检测排名 (t=0.1)**：" + " > ".join(
        f"{m.replace('doubao-seed-2-0-pro-260215','doubao')}({a['b_mean']:.0f}%)" for m, a in t01_by_b
    ))

    # B/O 负相关
    b_vals = [a["b_mean"] for _, a in t01_results]
    o_vals = [a["o_mean"] for _, a in t01_results]
    if len(b_vals) >= 2:
        b_mean_all = sum(b_vals) / len(b_vals)
        o_mean_all = sum(o_vals) / len(o_vals)
        cov = sum((b - b_mean_all) * (o - o_mean_all) for b, o in zip(b_vals, o_vals))
        b_var = sum((b - b_mean_all) ** 2 for b in b_vals)
        o_var = sum((o - o_mean_all) ** 2 for o in o_vals)
        if b_var > 0 and o_var > 0:
            r = cov / math.sqrt(b_var * o_var)
            lines.append(f"2. **B/O 相关性**: r = {r:.2f} — {'负相关' if r < -0.3 else '正相关' if r > 0.3 else '无显著相关'}")

    # 温度影响
    if len(temps) >= 2:
        deltas = []
        for model in models:
            k1, k7 = (model, temps[0]), (model, temps[1])
            if k1 in all_results and k7 in all_results:
                deltas.append(abs(all_results[k7]["b_mean"] - all_results[k1]["b_mean"]))
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        lines.append(f"3. **温度影响**: B 均值变化幅度平均 {avg_delta:.0f}%，异常检测能力{'不依赖' if avg_delta <= 10 else '依赖'}确定性采样")

    # 最稳定模型
    stab_01 = [(m, all_results[(m, temps[0])]["stability"]["stable_pct"])
               for m in models if (m, temps[0]) in all_results]
    stab_01.sort(key=lambda x: x[1], reverse=True)
    lines.append(f"4. **最稳定模型 (t=0.1)**: {stab_01[0][0].replace('doubao-seed-2-0-pro-260215','doubao')} ({stab_01[0][1]}% case-level 一致)")

    lines.append("")

    # ── Normal 对照 ──
    lines.append("## Normal 对照组")
    lines.append("")
    lines.append("| 模型 | Temp | 通过率 |")
    lines.append("|------|------|--------|")
    for temp in temps:
        for model in models:
            key = (model, temp)
            if key not in all_results:
                continue
            a = all_results[key]
            short = model.replace("doubao-seed-2-0-pro-260215", "doubao")
            lines.append(f"| {short} | {temp} | {a['normal_rate']:.0f}% |")
    lines.append("")

    return "\n".join(lines)


def print_json(all_results: dict) -> None:
    """输出 JSON，key 从 tuple 转 string。"""
    serializable = {}
    for (model, temp), agg in sorted(all_results.items()):
        key = f"{model}/t{temp}"
        serializable[key] = agg
    print(json.dumps(serializable, ensure_ascii=False, indent=2))


# ── Main ──────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="v2 幻觉鲁棒性分析")
    parser.add_argument("--latest", type=int, default=None,
                        help="每 model×temp 取最新 N 轮 (默认: 全部)")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--report", action="store_true",
                        help="写入 results/report_action_hallucination.md")
    args = parser.parse_args()

    all_run_files = discover_runs()
    if not all_run_files:
        print("未找到结果文件。请先运行: .\\run_hallucination.ps1")
        return

    # 按 model×temp 聚合
    all_results = {}
    temps = sorted({temp for _, temp in all_run_files})
    for (model, temp), files in sorted(all_run_files.items()):
        selected = pick_latest_n(files, args.latest)
        run_stats = [analyze_one_run(load_run(f)) for f in selected]
        all_results[(model, temp)] = aggregate_runs(run_stats)

    if args.json:
        print_json(all_results)
    elif args.report:
        report = format_report(all_results, temps)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"Report written to {REPORT_PATH}")
        # 同时输出到终端
        print_text(all_results, temps)
    else:
        print_text(all_results, temps)


if __name__ == "__main__":
    main()
