"""
批量评测运行器（v1 — 意图理解）
================================
两阶段流水线：
  Phase 1 (collect): 调用目标模型，收集原始响应 → raw_{ts}.jsonl
  Phase 2 (judge):   GEval 评分 + 结构化断言    → run_{ts}.jsonl

跨模型用 ThreadPoolExecutor 并发（I/O 密集型，API 为主要开销）。
同一模型多轮串行（避免 rate limit）。

用法:
    python run.py                     # 3 模型各 1 轮
    python run.py --runs 3            # 各 3 轮
    python run.py --models deepseek-chat mimo-v2-pro
    python run.py --workers 4         # 每阶段并发线程数
    python run.py --phase collect     # 只跑收集（不评分）
    python run.py --phase judge       # 只跑评分（需要已有 raw 文件）
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

PROJECT_DIR = Path(__file__).resolve().parent  # v1_intent_eval/
ANALYZE_SCRIPT = PROJECT_DIR / "analyze.py"

ALL_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "mimo-v2-pro",
    "doubao-seed-2-0-pro-260215",
]


def run_collect(model: str, workers: int) -> tuple[bool, float, str]:
    """Phase 1: 收集模型原始响应。返回 (success, elapsed_s, stdout)。"""
    env = {**os.environ, "TARGET_MODEL": model, "MAX_WORKERS": str(workers)}
    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "eval/collect.py"],
        cwd=str(PROJECT_DIR),
        env=env,
        timeout=600,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    output = result.stdout.strip()
    if not ok:
        output = result.stderr.strip() or output
    return ok, elapsed, output


def run_judge(raw_file: str, workers: int) -> tuple[bool, float, str]:
    """Phase 2: GEval 评分。返回 (success, elapsed_s, stdout)。"""
    env = {**os.environ, "MAX_WORKERS": str(workers)}
    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "eval/judge.py", raw_file],
        cwd=str(PROJECT_DIR),
        env=env,
        timeout=900,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    output = result.stdout.strip()
    if not ok:
        output = result.stderr.strip() or output
    return ok, elapsed, output


def run_one_round(model: str, run_idx: int, total_runs: int,
                  workers: int, phase: str) -> tuple[str, int, bool, float]:
    """执行一轮 collect → judge，返回 (model, run_idx, success, elapsed_s)。"""
    label = f"[{model} {run_idx+1}/{total_runs}]"
    total_elapsed = 0.0

    if phase in ("all", "collect"):
        ok, elapsed, output = run_collect(model, workers)
        total_elapsed += elapsed
        if not ok:
            print(f"  {label} collect FAIL ({elapsed:.0f}s)")
            print(f"    {output[-200:]}")
            return model, run_idx, False, total_elapsed
        # 提取 raw 文件路径（collect.py 最后一行输出路径）
        raw_file = output.strip().split("\n")[-1].strip()
        print(f"  {label} collect OK ({elapsed:.0f}s)")

        if phase == "collect":
            return model, run_idx, True, total_elapsed

    if phase == "judge":
        # 找最新的 raw 文件
        model_dir = PROJECT_DIR / "results" / model.replace("/", "_")
        raws = sorted(model_dir.glob("raw_*.jsonl"), reverse=True)
        if not raws:
            print(f"  {label} judge FAIL: no raw file found")
            return model, run_idx, False, 0.0
        raw_file = str(raws[0])

    if phase in ("all", "judge"):
        ok, elapsed, output = run_judge(raw_file, workers)
        total_elapsed += elapsed
        status = "OK" if ok else "FAIL"
        print(f"  {label} judge {status} ({elapsed:.0f}s)")
        if not ok:
            print(f"    {output[-200:]}")
        return model, run_idx, ok, total_elapsed

    return model, run_idx, True, total_elapsed


def _run_model_all_rounds(model: str, runs: int, workers: int,
                          phase: str) -> list[tuple[str, int, bool, float]]:
    """串行执行一个模型的全部轮次。"""
    results = []
    for i in range(runs):
        results.append(run_one_round(model, i, runs, workers, phase))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="批量多模型意图理解评测")
    parser.add_argument("--models", nargs="+", default=ALL_MODELS, help="要跑的模型列表")
    parser.add_argument("--runs", type=int, default=1, help="每模型跑几轮 (默认 1)")
    parser.add_argument("--workers", type=int, default=8, help="每阶段并发线程数")
    parser.add_argument("--phase", choices=["all", "collect", "judge"], default="all",
                        help="只跑指定阶段 (默认 all)")
    parser.add_argument("--no-analyze", action="store_true", help="跑完不自动分析")
    args = parser.parse_args()

    models = args.models
    runs = args.runs
    total = len(models) * runs

    print(f"{'=' * 60}")
    print(f"  批量评测: {len(models)} 模型 × {runs} 轮 = {total} 次")
    print(f"  模型: {models}")
    print(f"  阶段: {args.phase}")
    print(f"  并发线程数: {args.workers}")
    print(f"{'=' * 60}")

    t_start = time.monotonic()
    summary: dict[str, list[bool]] = {m: [] for m in models}

    # 不同模型并行、同模型多轮串行
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        futures = {
            pool.submit(_run_model_all_rounds, m, runs, args.workers, args.phase): m
            for m in models
        }
        for f in as_completed(futures):
            for model, run_idx, ok, elapsed in f.result():
                summary[model].append(ok)

    elapsed_total = time.monotonic() - t_start

    print(f"\n{'=' * 60}")
    print(f"  完成: {elapsed_total:.0f}s")
    print(f"{'=' * 60}")
    for model in models:
        results = summary[model]
        ok_count = sum(results)
        print(f"  {model}: {ok_count}/{len(results)} passed")

    if not args.no_analyze and args.phase in ("all", "judge"):
        print(f"\n{'=' * 60}")
        print("  正在生成分析报告 ...")
        print(f"{'=' * 60}")
        subprocess.run(
            [sys.executable, str(ANALYZE_SCRIPT), "--latest", str(runs), "--report"],
            cwd=str(PROJECT_DIR),
        )


if __name__ == "__main__":
    main()
