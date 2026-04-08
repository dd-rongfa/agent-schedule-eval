"""
Baseline 对照分析脚本
====================
读取多份 results*.jsonl，按 Bloom 层级汇总通过率、平均分，
输出对比表格 + Bloom × Model 热力图（bloom_heatmap.png）。

用法:
    python agent_schedule_eval/baseline_compare.py

默认读取 agent_schedule_eval/ 下所有 results*.jsonl。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无 GUI 环境下保存图片
import matplotlib.pyplot as plt
import seaborn as sns

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
HEATMAP_FILE = RESULTS_DIR / "bloom_heatmap.png"

LEVEL_LABELS = {
    1: "L1 Remember",
    2: "L2 Understand",
    3: "L3 Apply",
    4: "L4 Analyze",
    5: "L5 Evaluate",
    6: "L6 Create",
}


def load_latest_bloom_results(jsonl_path: Path) -> list[dict]:
    """读取 bloom_intent 类条目，每个 (bloom_level, input) 只保留最新一条。"""
    latest: dict[tuple, dict] = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("test") != "bloom_intent":
                continue
            key = (row["bloom_level"], row["input"])
            prev = latest.get(key)
            if prev is None or row.get("timestamp", "") > prev.get("timestamp", ""):
                latest[key] = row
    return list(latest.values())


def model_label(rows: list[dict], path: Path) -> str:
    """从结果行中提取模型名称，无字段时从文件名推断。"""
    names = {r.get("target_model") for r in rows if r.get("target_model")}
    if names:
        return " / ".join(sorted(names))
    # 旧数据没有 target_model，从文件名推断
    stem = path.stem  # e.g. "results" → "deepseek-chat", "results_mimo_v2_pro" → "mimo-v2-pro"
    if stem == "results":
        return "deepseek-chat"
    return stem.replace("results_", "").replace("_", "-")


def summarize(rows: list[dict]) -> dict[int, dict]:
    """按 Bloom 层级汇总 pass_count, total, avg_score。"""
    stats: dict[int, dict] = defaultdict(lambda: {"pass": 0, "total": 0, "scores": []})
    for row in rows:
        level = row["bloom_level"]
        stats[level]["total"] += 1
        if row.get("passed"):
            stats[level]["pass"] += 1
        if row.get("score") is not None:
            stats[level]["scores"].append(row["score"])
    result = {}
    for level, data in stats.items():
        scores = data["scores"]
        result[level] = {
            "pass": data["pass"],
            "total": data["total"],
            "pass_rate": round(data["pass"] / data["total"], 3) if data["total"] else 0,
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        }
    return result


def print_table(model_stats: dict[str, dict[int, dict]]) -> None:
    models = list(model_stats.keys())
    levels = sorted({lvl for stats in model_stats.values() for lvl in stats})

    # Header
    col_w = 18
    header = f"{'Bloom Level':<20}" + "".join(f"{m[:col_w]:<{col_w}}" for m in models)
    print("\n" + "=" * len(header))
    print("Bloom Level × Model  通过率对比")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for lvl in levels:
        label = LEVEL_LABELS.get(lvl, f"L{lvl}")
        row_str = f"{label:<20}"
        for model in models:
            stats = model_stats[model].get(lvl)
            if stats:
                cell = f"{stats['pass']}/{stats['total']}  ({stats['pass_rate']*100:.0f}%)"
            else:
                cell = "N/A"
            row_str += f"{cell:<{col_w}}"
        print(row_str)

    # Overall row
    print("-" * len(header))
    overall_str = f"{'Overall':<20}"
    for model in models:
        total_pass = sum(s["pass"] for s in model_stats[model].values())
        total_all = sum(s["total"] for s in model_stats[model].values())
        pct = total_pass / total_all * 100 if total_all else 0
        cell = f"{total_pass}/{total_all}  ({pct:.0f}%)"
        overall_str += f"{cell:<{col_w}}"
    print(overall_str)
    print("=" * len(header))


def plot_heatmap(model_stats: dict[str, dict[int, dict]]) -> None:
    models = list(model_stats.keys())
    levels = sorted({lvl for stats in model_stats.values() for lvl in stats})
    level_labels = [LEVEL_LABELS.get(lvl, f"L{lvl}") for lvl in levels]

    # Build matrix: rows=models, cols=levels, value=pass_rate
    data = []
    for model in models:
        row = []
        for lvl in levels:
            stats = model_stats[model].get(lvl)
            row.append(stats["pass_rate"] if stats else 0.0)
        data.append(row)

    fig, ax = plt.subplots(figsize=(max(8, len(levels) * 1.5), max(3, len(models) * 1.2 + 1.5)))
    sns.heatmap(
        data,
        xticklabels=level_labels,
        yticklabels=models,
        annot=True,
        fmt=".0%",
        vmin=0,
        vmax=1,
        cmap="RdYlGn",
        linewidths=0.5,
        ax=ax,
    )
    ax.set_title("Bloom Level × Model  Pass Rate", fontsize=13, pad=12)
    ax.set_xlabel("Bloom Level")
    ax.set_ylabel("Model")
    plt.tight_layout()
    plt.savefig(HEATMAP_FILE, dpi=150)
    plt.close()
    print(f"\n热力图已保存到: {HEATMAP_FILE}")


def main() -> None:
    jsonl_files = sorted(RESULTS_DIR.glob("results*.jsonl"))
    if not jsonl_files:
        print("未找到 results*.jsonl 文件")
        return

    model_stats: dict[str, dict[int, dict]] = {}

    for path in jsonl_files:
        rows = load_latest_bloom_results(path)
        if not rows:
            print(f"  {path.name}: 无 bloom_intent 条目，跳过")
            continue
        label = model_label(rows, path)
        # 如果同一模型标签有多个文件，后者覆盖前者
        model_stats[label] = summarize(rows)
        print(f"  {path.name}  →  模型: {label}  ({len(rows)} 条)")

    if not model_stats:
        print("没有有效数据")
        return

    print_table(model_stats)
    plot_heatmap(model_stats)


if __name__ == "__main__":
    main()
