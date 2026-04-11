"""
行为模式分析：从 results/{model}/ 提取模型行为特征
================================================================
分析维度：
  1. 通过率横评（多轮取均值 ± 标准差）
  2. 按 section 拆分通过率
  3. 主动检查行为 — pre_create_check / post_create_verify
  4. 延迟对比

目录结构：
  results/
    deepseek-chat/          ← 新布局（按模型分文件夹）
      run_20260411_123344.jsonl
    run_deepseek-chat_*.jsonl  ← 旧布局（自动兼容）

用法：
  python analyze.py                  # 每模型取最新 1 个文件
  python analyze.py --latest 3       # 每模型取最新 3 个文件取均值
  python analyze.py --markdown       # 输出 Markdown 表格
  python analyze.py --json           # 输出 JSON
  python analyze.py --report         # 写入 results/report.md
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"

CHECK_TOOLS = {"get_current_time", "list_schedules", "list_todos"}
CREATE_TOOLS = {"create_schedule", "create_recurring", "create_todo"}


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
    """扫描 results/ 下的模型文件夹，返回 {model: [sorted run files]}。

    兼容两种布局：
      新: results/{model}/run_{ts}.jsonl
      旧: results/run_{model}_{ts}.jsonl
    """
    model_files: dict[str, list[Path]] = defaultdict(list)

    # 新布局: results/{model}/run_*.jsonl
    if RESULTS_DIR.exists():
        for model_dir in sorted(RESULTS_DIR.iterdir()):
            if model_dir.is_dir() and model_dir.name != "archive":
                runs = sorted(model_dir.glob("run_*.jsonl"))
                if runs:
                    model_files[model_dir.name] = runs

    # 旧布局: results/run_{model}_{date}_{time}.jsonl
    for f in sorted(RESULTS_DIR.glob("run_*.jsonl")):
        parts = f.stem.split("_")
        if len(parts) >= 4:
            model = "_".join(parts[1:-2])
            if model not in model_files:
                model_files[model].append(f)

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


def analyze_one_run(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {"total": 0, "passed": 0, "pass_rate": 0.0}

    passed = sum(1 for r in records if r.get("passed"))

    # 延迟
    latencies = [r["latency_ms"] for r in records if r.get("latency_ms")]
    avg_latency = sum(latencies) / len(latencies) / 1000 if latencies else 0

    # 主动检查
    used_get_time = 0
    pre_check = 0
    post_verify = 0
    total_with_create = 0

    for r in records:
        called = r.get("called_tools", [])
        if "get_current_time" in called:
            used_get_time += 1

        create_indices = [i for i, t in enumerate(called) if t in CREATE_TOOLS]
        check_indices = [i for i, t in enumerate(called) if t in CHECK_TOOLS]

        if create_indices:
            total_with_create += 1

        if r.get("pre_create_check"):
            pre_check += 1
        elif create_indices and check_indices and min(check_indices) < min(create_indices):
            pre_check += 1

        if r.get("post_create_verify"):
            post_verify += 1
        elif create_indices and check_indices and max(check_indices) > max(create_indices):
            post_verify += 1

    # per section
    section_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in records:
        sec = r.get("section") or "unknown"
        section_stats[sec]["total"] += 1
        if r.get("passed"):
            section_stats[sec]["passed"] += 1

    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total * 100,
        "avg_latency_s": round(avg_latency, 1),
        "get_current_time_pct": used_get_time / total * 100,
        "total_with_create": total_with_create,
        "pre_check": pre_check,
        "pre_check_pct": pre_check / total_with_create * 100 if total_with_create else 0,
        "post_verify": post_verify,
        "post_verify_pct": post_verify / total_with_create * 100 if total_with_create else 0,
        "section_breakdown": {
            k: {"passed": v["passed"], "total": v["total"],
                "rate": v["passed"] / v["total"] * 100 if v["total"] else 0}
            for k, v in sorted(section_stats.items())
        },
    }


# ── 多轮聚合 ──────────────────────────────────────


def aggregate_runs(run_stats: list[dict]) -> dict:
    """多轮结果取均值 ± 标准差。"""
    n = len(run_stats)
    if n == 0:
        return {}
    if n == 1:
        s = run_stats[0]
        return {
            "n_runs": 1,
            "total_cases": s["total"],
            "pass_rate_mean": round(s["pass_rate"], 1),
            "pass_rate_std": 0.0,
            "avg_latency_s": s["avg_latency_s"],
            "pre_check_pct": round(s["pre_check_pct"], 1),
            "post_verify_pct": round(s["post_verify_pct"], 1),
            "section_breakdown": s["section_breakdown"],
        }

    rates = [s["pass_rate"] for s in run_stats]
    mean = sum(rates) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in rates) / (n - 1))

    latencies = [s["avg_latency_s"] for s in run_stats]
    pre_checks = [s["pre_check_pct"] for s in run_stats]
    post_verifies = [s["post_verify_pct"] for s in run_stats]

    # 合并 section
    all_sections: set[str] = set()
    for s in run_stats:
        all_sections.update(s["section_breakdown"].keys())

    section_agg = {}
    for sec in sorted(all_sections):
        sec_rates = [
            s["section_breakdown"][sec]["rate"]
            for s in run_stats if sec in s["section_breakdown"]
        ]
        section_agg[sec] = {
            "rate": round(sum(sec_rates) / len(sec_rates), 1) if sec_rates else 0,
            "n": len(sec_rates),
        }

    return {
        "n_runs": n,
        "total_cases": run_stats[0]["total"],
        "pass_rate_mean": round(mean, 1),
        "pass_rate_std": round(std, 1),
        "avg_latency_s": round(sum(latencies) / n, 1),
        "pre_check_pct": round(sum(pre_checks) / n, 1),
        "post_verify_pct": round(sum(post_verifies) / n, 1),
        "section_breakdown": section_agg,
    }


# ── 输出格式 ──────────────────────────────────────


def print_text(all_results: dict[str, dict]) -> None:
    for model, agg in all_results.items():
        n = agg["n_runs"]
        rate = agg["pass_rate_mean"]
        std = agg.get("pass_rate_std", 0)
        rate_str = f"{rate:.1f}%" if n == 1 else f"{rate:.1f}% ± {std:.1f}%"

        print(f"\n{'=' * 60}")
        print(f"模型: {model}  ({n} run{'s' if n > 1 else ''}, {agg['total_cases']} cases)")
        print(f"{'=' * 60}")
        print(f"  通过率: {rate_str}")
        print(f"  平均延迟: {agg['avg_latency_s']}s")
        print(f"  创建前先查: {agg['pre_check_pct']:.0f}%")
        print(f"  创建后验证: {agg['post_verify_pct']:.0f}%")
        print()
        print("  ── 按 section 拆分 ──")
        for sec, info in agg["section_breakdown"].items():
            r = info["rate"] if isinstance(info["rate"], (int, float)) else info["rate"]
            print(f"  {sec:25s} {r:.0f}%")


def format_markdown(all_results: dict[str, dict]) -> str:
    """生成 Markdown 报告字符串。"""
    lines: list[str] = []
    models = list(all_results.keys())

    lines.append("## 模型通过率对比\n")
    lines.append("| 模型 | 通过率 | case 数 | 平均延迟 | 创建前先查 | 创建后验证 |")
    lines.append("|------|--------|---------|----------|-----------|-----------|")
    for m in models:
        a = all_results[m]
        n = a["n_runs"]
        r = a["pass_rate_mean"]
        s = a.get("pass_rate_std", 0)
        rate_str = f"{r:.1f}%" if n == 1 else f"{r:.1f}% ± {s:.1f}%"
        lines.append(f"| {m} | {rate_str} | {a['total_cases']} | {a['avg_latency_s']}s | {a['pre_check_pct']:.0f}% | {a['post_verify_pct']:.0f}% |")

    all_sections: set[str] = set()
    for a in all_results.values():
        all_sections.update(a["section_breakdown"].keys())

    lines.append("\n## 按 Section 拆分通过率\n")
    header = "| section | " + " | ".join(models) + " |"
    sep = "|---------|" + "|".join(["--------"] * len(models)) + "|"
    lines.append(header)
    lines.append(sep)
    for sec in sorted(all_sections):
        row = f"| {sec} |"
        for m in models:
            info = all_results[m]["section_breakdown"].get(sec)
            if info:
                r = info["rate"] if isinstance(info["rate"], (int, float)) else info["rate"]
                row += f" {r:.0f}% |"
            else:
                row += " — |"
        lines.append(row)

    return "\n".join(lines)


def print_markdown(all_results: dict[str, dict]) -> None:
    print("\n### 模型通过率对比\n")
    print("| 模型 | 通过率 | case 数 | 平均延迟 | 创建前先查 | 创建后验证 |")
    print("|------|--------|---------|----------|-----------|-----------|")
    models = list(all_results.keys())
    for m in models:
        a = all_results[m]
        n = a["n_runs"]
        r = a["pass_rate_mean"]
        s = a.get("pass_rate_std", 0)
        rate_str = f"{r:.1f}%" if n == 1 else f"{r:.1f}% ± {s:.1f}%"
        print(f"| {m} | {rate_str} | {a['total_cases']} | {a['avg_latency_s']}s | {a['pre_check_pct']:.0f}% | {a['post_verify_pct']:.0f}% |")

    all_sections: set[str] = set()
    for a in all_results.values():
        all_sections.update(a["section_breakdown"].keys())

    print("\n### 按 Section 拆分通过率\n")
    header = "| section | " + " | ".join(models) + " |"
    sep = "|---------|" + "|".join(["--------"] * len(models)) + "|"
    print(header)
    print(sep)
    for sec in sorted(all_sections):
        row = f"| {sec} |"
        for m in models:
            info = all_results[m]["section_breakdown"].get(sec)
            if info:
                r = info["rate"] if isinstance(info["rate"], (int, float)) else info["rate"]
                row += f" {r:.0f}% |"
            else:
                row += " — |"
        print(row)


def print_json(all_results: dict[str, dict]) -> None:
    print(json.dumps(all_results, ensure_ascii=False, indent=2))


# ── Main ──────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="v2 评测行为分析")
    parser.add_argument("--latest", type=int, default=1,
                        help="每模型取最新 N 个文件聚合 (默认 1)")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 表格")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--report", action="store_true",
                        help="将 Markdown 报告写入 results/report.md")
    parser.add_argument("files", nargs="*", help="指定 JSONL 文件（覆盖自动发现）")
    args = parser.parse_args()

    if args.files:
        model_files_map: dict[str, list[Path]] = defaultdict(list)
        for fp in args.files:
            p = Path(fp)
            if p.exists():
                model_files_map[p.parent.name].append(p)
        model_runs = dict(model_files_map)
    else:
        all_models = discover_models()
        model_runs = {
            model: pick_latest_n(files, args.latest)
            for model, files in all_models.items()
        }

    if not model_runs:
        print("未找到结果文件。请先运行: python scripts/batch_run.py")
        return

    all_results = {}
    for model in sorted(model_runs.keys()):
        files = model_runs[model]
        run_stats = [analyze_one_run(load_run(f)) for f in files]
        all_results[model] = aggregate_runs(run_stats)

    if args.json:
        print_json(all_results)
    elif args.markdown:
        print_markdown(all_results)
    else:
        print_text(all_results)
        if len(all_results) > 1:
            print(f"\n{'=' * 60}")
            print("  Markdown 汇总（复制到 README）")
            print(f"{'=' * 60}")
            print_markdown(all_results)

    # ── 写 report.md ──
    if args.report:
        from datetime import datetime
        report_path = RESULTS_DIR / "report.md"
        n_runs = next(iter(all_results.values()))["n_runs"]
        header = (
            f"# v2 评测报告\n\n"
            f"> 自动生成 @ {datetime.now():%Y-%m-%d %H:%M}  |  "
            f"每模型取最新 {n_runs} 轮\n\n"
        )
        # 单次明细
        detail_lines: list[str] = []
        for model in sorted(model_runs.keys()):
            files = model_runs[model]
            for f in files:
                records = load_run(f)
                stats = analyze_one_run(records)
                detail_lines.append(
                    f"| {model} | {f.name} | {stats['total']} | "
                    f"{stats['passed']} | {stats['pass_rate']:.1f}% | "
                    f"{stats['avg_latency_s']}s |"
                )
        detail_table = (
            "\n## 单次运行明细\n\n"
            "| 模型 | 文件 | case 数 | 通过 | 通过率 | 平均延迟 |\n"
            "|------|------|---------|------|--------|----------|\n"
            + "\n".join(detail_lines) + "\n"
        )
        content = header + format_markdown(all_results) + "\n" + detail_table
        report_path.write_text(content, encoding="utf-8")
        print(f"\n  报告已写入: {report_path}")


if __name__ == "__main__":
    main()
