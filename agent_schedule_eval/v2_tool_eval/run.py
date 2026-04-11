"""
批量评测运行器（v2 — 工具调用）
================================
跨模型并行 × 每模型 N 轮串行 → 一键跑完全部评测。

结果自动写入 results/{model}/run_{timestamp}.jsonl。
跑完后自动调 analyze_behavior.py 生成对比报告。

用法:
    python run.py                     # 4 模型各 1 轮
    python run.py --runs 3            # 各 3 轮
    python run.py --models deepseek-chat mimo-v2-pro
    python run.py --workers 4         # 内部并发线程数（降低可避 429）
    python run.py --no-analyze        # 跑完不分析

最佳实践: 正式评测跑 3 轮取均值，调试跑 1 轮。
"""

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent  # v2_tool_eval/
ANALYZE_SCRIPT = PROJECT_DIR / "analyze.py"

ALL_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "mimo-v2-pro",
    "doubao-seed-2-0-pro-260215",
]


def run_once(model: str, run_idx: int, total_runs: int, workers: int) -> tuple[str, int, bool, float]:
    """执行一次 pytest，返回 (model, run_idx, success, elapsed_s)。"""
    env = {**os.environ, "TARGET_MODEL": model, "MAX_WORKERS": str(workers)}
    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "eval/test_tool_calling.py", "-v", "--tb=short", "-q"],
        cwd=str(PROJECT_DIR),
        env=env,
        timeout=900,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"  [{model} {run_idx+1}/{total_runs}] {status} ({elapsed:.0f}s)")
    if not ok:
        # 只打最后 10 行帮助诊断
        tail = "\n".join(result.stdout.strip().split("\n")[-10:])
        print(f"    {tail}")
    return model, run_idx, ok, elapsed


def _run_model_all_rounds(model: str, runs: int, workers: int) -> list[tuple[str, int, bool, float]]:
    """串行执行一个模型的全部轮次。"""
    results = []
    for i in range(runs):
        results.append(run_once(model, i, runs, workers))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="批量多模型评测")
    parser.add_argument("--models", nargs="+", default=ALL_MODELS, help="要跑的模型列表")
    parser.add_argument("--runs", type=int, default=1, help="每模型跑几轮 (默认 1)")
    parser.add_argument("--workers", type=int, default=8, help="每次 pytest 内部并发线程数")
    parser.add_argument("--no-analyze", action="store_true", help="跑完不自动分析")
    args = parser.parse_args()

    models = args.models
    runs = args.runs
    total = len(models) * runs

    print(f"{'=' * 60}")
    print(f"  批量评测: {len(models)} 模型 × {runs} 轮 = {total} 次")
    print(f"  模型: {models}")
    print(f"  并发线程数/模型: {args.workers}")
    print(f"{'=' * 60}")

    t_start = time.monotonic()
    summary: dict[str, list[bool]] = {m: [] for m in models}

    # 不同模型并行、同模型多轮串行（避免同模型并发请求过载）
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        model_futures = {
            pool.submit(_run_model_all_rounds, m, runs, args.workers): m
            for m in models
        }

        for f in as_completed(model_futures):
            for model, run_idx, ok, elapsed in f.result():
                summary[model].append(ok)

    elapsed_total = time.monotonic() - t_start

    # ── 汇总 ──
    print(f"\n{'=' * 60}")
    print(f"  完成: {elapsed_total:.0f}s")
    print(f"{'=' * 60}")
    for model in models:
        results = summary[model]
        ok_count = sum(results)
        print(f"  {model}: {ok_count}/{len(results)} passed")

    # ── 自动分析 ──
    if not args.no_analyze:
        print(f"\n{'=' * 60}")
        print("  正在生成分析报告 ...")
        print(f"{'=' * 60}")
        subprocess.run(
            [sys.executable, str(ANALYZE_SCRIPT), "--latest", str(runs), "--report"],
            cwd=str(PROJECT_DIR),
        )


if __name__ == "__main__":
    main()
