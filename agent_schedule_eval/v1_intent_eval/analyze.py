"""
行为模式分析：从 results/{model}/ 提取 GEval 意图理解评测结果
================================================================
分析维度：
  1. 通过率横评（多轮取均值 ± 标准差）
  2. 按 difficulty / bloom_level 拆分
  3. Layer 2 结构化输出汇总
  4. 热力图生成（可选）

目录结构：
  results/
    deepseek-chat/          ← 新布局（按模型分文件夹）
      run_20260410_194240.jsonl

用法：
  python analyze.py                  # 每模型取最新 1 个文件
  python analyze.py --latest 3       # 每模型取最新 3 个文件取均值
  python analyze.py --markdown       # 输出 Markdown 表格
  python analyze.py --json           # 输出 JSON
  python analyze.py --report         # 写入 results/report.md
  python analyze.py --heatmap        # 生成热力图（需要 matplotlib/seaborn）
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"

DIFFICULTY_ORDER = ["easy", "medium", "hard"]
BLOOM_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6"]


# ── 数据加载 ──────────────────────────────────────


def load_run(filepath: Path) -> list[dict]:
    records = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def discover_models() -> dict[str, list[Path]]:
    """扫描 results/ 下的模型文件夹，返回 {model: [sorted run files]}。"""
    model_files: dict[str, list[Path]] = defaultdict(list)

    if RESULTS_DIR.exists():
        for model_dir in sorted(RESULTS_DIR.iterdir()):
            if model_dir.is_dir() and model_dir.name != "archive":
                runs = sorted(model_dir.glob("run_*.jsonl"))
                if runs:
                    model_files[model_dir.name] = runs

    return dict(model_files)


def pick_latest_n(files: list[Path], n: int) -> list[Path]:
    """取最新的 N 个非空文件（按文件名降序 = 时间戳降序）。"""
    sorted_files = sorted(files, key=lambda p: p.name, reverse=True)
    picked = []
    for f in sorted_files:
        line_count = sum(1 for line in open(f, encoding="utf-8") if line.strip())
        if line_count > 0:
            picked.append(f)
        if len(picked) >= n:
            break
    return picked


# ── 单次分析 ──────────────────────────────────────


def _pass_rate_by_dim(records: list[dict], dim_key: str) -> dict[str, dict]:
    """从单次 run 按 dim_key 汇总 pass_rate。"""
    stats: dict[str, dict] = defaultdict(lambda: {"pass": 0, "total": 0, "scores": []})
    for row in records:
        if row.get("test") != "bloom_intent":
            continue
        d = row.get(dim_key)
        if d is None:
            continue
        if dim_key == "bloom_level" and isinstance(d, int):
            d = f"L{d}"
        stats[d]["total"] += 1
        if row.get("passed"):
            stats[d]["pass"] += 1
        if row.get("score") is not None:
            stats[d]["scores"].append(row["score"])
    result = {}
    for k, data in stats.items():
        scores = data["scores"]
        result[k] = {
            "pass": data["pass"],
            "total": data["total"],
            "pass_rate": data["pass"] / data["total"] if data["total"] else 0,
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
        }
    return result


def analyze_one_run(records: list[dict]) -> dict:
    intent = [r for r in records if r.get("test") == "bloom_intent"]
    struct = [r for r in records if r.get("test") == "structured_output"]

    total_intent = len(intent)
    passed_intent = sum(1 for r in intent if r.get("passed"))
    total_struct = len(struct)
    passed_struct = sum(1 for r in struct if r.get("passed"))

    latencies = [r["latency_ms"] for r in records if r.get("latency_ms")]
    avg_latency = sum(latencies) / len(latencies) / 1000 if latencies else 0

    diff_breakdown = _pass_rate_by_dim(records, "difficulty")
    bloom_breakdown = _pass_rate_by_dim(records, "bloom_level")

    return {
        "total_intent": total_intent,
        "passed_intent": passed_intent,
        "intent_rate": passed_intent / total_intent * 100 if total_intent else 0,
        "total_struct": total_struct,
        "passed_struct": passed_struct,
        "struct_rate": passed_struct / total_struct * 100 if total_struct else 0,
        "avg_latency_s": round(avg_latency, 1),
        "difficulty_breakdown": diff_breakdown,
        "bloom_breakdown": bloom_breakdown,
    }


# ── 多轮聚合 ──────────────────────────────────────


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = sum(values) / len(values)
    if len(values) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return m, math.sqrt(var)


def aggregate_runs(run_stats: list[dict]) -> dict:
    """多轮结果取均值 ± 标准差。"""
    n = len(run_stats)
    if n == 0:
        return {}
    if n == 1:
        s = run_stats[0]
        return {
            "n_runs": 1,
            "total_cases": s["total_intent"],
            "intent_rate_mean": round(s["intent_rate"], 1),
            "intent_rate_std": 0.0,
            "struct_rate_mean": round(s["struct_rate"], 1) if s["total_struct"] else None,
            "avg_latency_s": s["avg_latency_s"],
            "difficulty_agg": {
                k: {"rate": round(v["pass_rate"] * 100, 1), "std": 0.0}
                for k, v in s["difficulty_breakdown"].items()
            },
            "bloom_agg": {
                k: {"rate": round(v["pass_rate"] * 100, 1), "std": 0.0}
                for k, v in s["bloom_breakdown"].items()
            },
        }

    intent_rates = [s["intent_rate"] for s in run_stats]
    i_mean, i_std = _mean_std(intent_rates)

    struct_rates = [s["struct_rate"] for s in run_stats if s["total_struct"]]
    s_mean, s_std = _mean_std(struct_rates)

    latencies = [s["avg_latency_s"] for s in run_stats]

    # 合并 difficulty
    all_diffs: set[str] = set()
    for s in run_stats:
        all_diffs.update(s["difficulty_breakdown"].keys())
    diff_agg = {}
    for d in sorted(all_diffs, key=lambda x: DIFFICULTY_ORDER.index(x) if x in DIFFICULTY_ORDER else 99):
        rates = [s["difficulty_breakdown"][d]["pass_rate"] * 100
                 for s in run_stats if d in s["difficulty_breakdown"]]
        m, sd = _mean_std(rates)
        diff_agg[d] = {"rate": round(m, 1), "std": round(sd, 1)}

    # 合并 bloom
    all_blooms: set[str] = set()
    for s in run_stats:
        all_blooms.update(s["bloom_breakdown"].keys())
    bloom_agg = {}
    for b in sorted(all_blooms, key=lambda x: BLOOM_ORDER.index(x) if x in BLOOM_ORDER else 99):
        rates = [s["bloom_breakdown"][b]["pass_rate"] * 100
                 for s in run_stats if b in s["bloom_breakdown"]]
        m, sd = _mean_std(rates)
        bloom_agg[b] = {"rate": round(m, 1), "std": round(sd, 1)}

    return {
        "n_runs": n,
        "total_cases": run_stats[0]["total_intent"],
        "intent_rate_mean": round(i_mean, 1),
        "intent_rate_std": round(i_std, 1),
        "struct_rate_mean": round(s_mean, 1) if struct_rates else None,
        "avg_latency_s": round(sum(latencies) / len(latencies), 1),
        "difficulty_agg": diff_agg,
        "bloom_agg": bloom_agg,
    }


# ── 输出格式 ──────────────────────────────────────


def format_plain(model: str, agg: dict) -> str:
    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"模型: {model}  ({agg['n_runs']} run, {agg['total_cases']} intent cases)")
    lines.append(f"{'=' * 60}")
    if agg["intent_rate_std"]:
        lines.append(f"  意图理解通过率: {agg['intent_rate_mean']}% ± {agg['intent_rate_std']}%")
    else:
        lines.append(f"  意图理解通过率: {agg['intent_rate_mean']}%")
    if agg.get("struct_rate_mean") is not None:
        lines.append(f"  结构化输出通过率: {agg['struct_rate_mean']}%")
    lines.append(f"  平均延迟: {agg['avg_latency_s']}s")

    if agg["difficulty_agg"]:
        lines.append(f"\n  ── 按 difficulty 拆分 ──")
        for d, v in agg["difficulty_agg"].items():
            if v["std"]:
                lines.append(f"  {d:<12} {v['rate']}% ± {v['std']}%")
            else:
                lines.append(f"  {d:<12} {v['rate']}%")

    if agg["bloom_agg"]:
        lines.append(f"\n  ── 按 bloom_level 拆分 ──")
        for b, v in agg["bloom_agg"].items():
            if v["std"]:
                lines.append(f"  {b:<12} {v['rate']}% ± {v['std']}%")
            else:
                lines.append(f"  {b:<12} {v['rate']}%")

    return "\n".join(lines)


def format_markdown(all_agg: dict[str, dict]) -> str:
    lines = []
    models = list(all_agg.keys())

    # 总览表
    lines.append("### 模型通过率对比\n")
    lines.append("| 模型 | 意图理解通过率 | case 数 | 平均延迟 | 结构化输出 |")
    lines.append("|------|---------------|---------|----------|-----------|")
    for m in models:
        a = all_agg[m]
        rate = f"{a['intent_rate_mean']}% ± {a['intent_rate_std']}%" if a["intent_rate_std"] else f"{a['intent_rate_mean']}%"
        struct = f"{a['struct_rate_mean']}%" if a.get("struct_rate_mean") is not None else "N/A"
        lines.append(f"| {m} | {rate} | {a['total_cases']} | {a['avg_latency_s']}s | {struct} |")

    # difficulty 矩阵
    all_diffs = set()
    for a in all_agg.values():
        all_diffs.update(a["difficulty_agg"].keys())
    diffs = sorted(all_diffs, key=lambda x: DIFFICULTY_ORDER.index(x) if x in DIFFICULTY_ORDER else 99)

    if diffs:
        lines.append("\n### Difficulty × Model 通过率\n")
        header = "| difficulty | " + " | ".join(models) + " |"
        sep = "|-----------|" + "|".join(["--------"] * len(models)) + "|"
        lines.append(header)
        lines.append(sep)
        for d in diffs:
            row = f"| {d} |"
            for m in models:
                v = all_agg[m]["difficulty_agg"].get(d)
                if v:
                    row += f" {v['rate']}%±{v['std']}% |" if v["std"] else f" {v['rate']}% |"
                else:
                    row += " N/A |"
            lines.append(row)

    # bloom 矩阵
    all_blooms = set()
    for a in all_agg.values():
        all_blooms.update(a["bloom_agg"].keys())
    blooms = sorted(all_blooms, key=lambda x: BLOOM_ORDER.index(x) if x in BLOOM_ORDER else 99)

    if blooms:
        lines.append("\n### Bloom Level × Model 通过率\n")
        header = "| bloom | " + " | ".join(models) + " |"
        sep = "|-------|" + "|".join(["--------"] * len(models)) + "|"
        lines.append(header)
        lines.append(sep)
        for b in blooms:
            row = f"| {b} |"
            for m in models:
                v = all_agg[m]["bloom_agg"].get(b)
                if v:
                    row += f" {v['rate']}%±{v['std']}% |" if v["std"] else f" {v['rate']}% |"
                else:
                    row += " N/A |"
            lines.append(row)

    return "\n".join(lines)


def write_report(all_agg: dict[str, dict]) -> Path:
    report_path = RESULTS_DIR / "report.md"
    lines = [
        f"# v1 意图理解评测报告",
        f"",
        f"> 自动生成，由 `analyze.py` 写入。",
        f"",
    ]
    lines.append(format_markdown(all_agg))

    # per-run detail
    lines.append("\n\n---\n")
    lines.append("### 各 run 文件明细\n")
    lines.append("| 模型 | 文件 | intent 通过率 | struct 通过率 | 延迟 |")
    lines.append("|------|------|--------------|--------------|------|")

    model_files = discover_models()
    for model in all_agg:
        n = all_agg[model]["n_runs"]
        files = pick_latest_n(model_files.get(model, []), n)
        for f in files:
            records = load_run(f)
            stats = analyze_one_run(records)
            lines.append(
                f"| {model} | {f.name} | "
                f"{stats['intent_rate']:.1f}% ({stats['passed_intent']}/{stats['total_intent']}) | "
                f"{stats['struct_rate']:.1f}% ({stats['passed_struct']}/{stats['total_struct']}) | "
                f"{stats['avg_latency_s']}s |"
            )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ── 热力图（可选） ────────────────────────────────


def _plot_heatmaps(all_agg: dict[str, dict]) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        import seaborn as sns
        import numpy as np
    except ImportError:
        print("  [SKIP] 热力图需要 matplotlib/seaborn/numpy，请 pip install")
        return

    models = list(all_agg.keys())

    # CJK font
    preferred = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"]
    available = {f.name for f in fm.fontManager.ttflist}
    cjk_font = next((n for n in preferred if n in available), None)
    if cjk_font:
        plt.rcParams["font.sans-serif"] = [cjk_font]
        plt.rcParams["axes.unicode_minus"] = False

    for dim_name, dim_key, dim_order in [
        ("Difficulty", "difficulty_agg", DIFFICULTY_ORDER),
        ("Bloom Level", "bloom_agg", BLOOM_ORDER),
    ]:
        all_dims = set()
        for a in all_agg.values():
            all_dims.update(a[dim_key].keys())
        dims = [d for d in dim_order if d in all_dims]
        if not dims:
            continue

        data, annot = [], []
        for m in models:
            row_d, row_a = [], []
            for d in dims:
                v = all_agg[m][dim_key].get(d)
                if v:
                    row_d.append(v["rate"] / 100)
                    if v["std"]:
                        row_a.append(f"{v['rate']:.0f}%\n±{v['std']:.0f}%")
                    else:
                        row_a.append(f"{v['rate']:.0f}%")
                else:
                    row_d.append(0)
                    row_a.append("N/A")
            data.append(row_d)
            annot.append(row_a)

        fig, ax = plt.subplots(figsize=(max(6, len(dims) * 1.8), max(3, len(models) * 1.2 + 1.5)))
        sns.heatmap(
            np.array(data), xticklabels=dims, yticklabels=models,
            annot=np.array(annot), fmt="",
            vmin=0, vmax=1, cmap="RdYlGn", linewidths=0.5, ax=ax,
        )
        ax.set_title(f"{dim_name} × Model  Pass Rate (mean±std)", fontsize=13, pad=12)
        plt.tight_layout()
        out = RESULTS_DIR / f"{dim_name.lower().replace(' ', '_')}_heatmap.png"
        plt.savefig(out, dpi=150)
        plt.close()
        print(f"  热力图已保存: {out}")


# ── main ──────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="v1 意图理解评测分析")
    parser.add_argument("--latest", type=int, default=1, help="每模型取最新 N 个 run (默认 1)")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 表格")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--report", action="store_true", help="写入 results/report.md")
    parser.add_argument("--heatmap", action="store_true", help="生成热力图")
    args = parser.parse_args()

    model_files = discover_models()
    if not model_files:
        print("未找到任何模型结果，请先运行评测。")
        return

    all_agg: dict[str, dict] = {}
    for model, files in sorted(model_files.items()):
        picked = pick_latest_n(files, args.latest)
        run_stats = [analyze_one_run(load_run(f)) for f in picked]
        agg = aggregate_runs(run_stats)
        all_agg[model] = agg
        print(format_plain(model, agg))
        print()

    if args.markdown or args.report:
        md = format_markdown(all_agg)
        if args.markdown:
            print(f"\n{'=' * 60}")
            print("  Markdown 汇总（复制到 README）")
            print(f"{'=' * 60}\n")
            print(md)

    if args.json:
        print(json.dumps(all_agg, ensure_ascii=False, indent=2))

    if args.report:
        report_path = write_report(all_agg)
        print(f"\n  报告已写入: {report_path}")

    if args.heatmap:
        _plot_heatmaps(all_agg)


if __name__ == "__main__":
    main()
