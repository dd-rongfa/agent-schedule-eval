"""
定时任务场景评测 — pytest 断言层
=================================
读取 scored results（run_*.jsonl），参数化断言。

两种用法：
  1. collect → judge → pytest（推荐，通过 run.py 自动编排）
  2. 独立运行：自动触发 collect + judge，再断言（向后兼容）

     TARGET_MODEL=deepseek-chat python -m pytest eval/test_schedule_eval.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT.parent))

from provider import TARGET_MODEL

RESULTS_DIR = _PROJECT / "results"


def _find_latest_run() -> Path | None:
    """找当前模型最新的 run_*.jsonl。"""
    model_dir = RESULTS_DIR / TARGET_MODEL.replace("/", "_")
    if not model_dir.exists():
        return None
    runs = sorted(model_dir.glob("run_*.jsonl"), reverse=True)
    return runs[0] if runs else None


def _ensure_results() -> list[dict]:
    """尝试加载已有 scored results；没有则先跑 collect + judge。"""
    run_file = _find_latest_run()

    if run_file is None:
        # 向后兼容：没有 scored results 时自动触发两阶段
        from eval.collect import collect_all
        from eval.judge import judge_all
        raw_file = collect_all()
        run_file = judge_all(raw_file)

    records = []
    with open(run_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ── 加载结果 ──────────────────────────────────────
ALL_SCORED = _ensure_results()
INTENT_RESULTS = [r for r in ALL_SCORED if r.get("test") == "bloom_intent"]
STRUCT_RESULTS = [r for r in ALL_SCORED if r.get("test") == "structured_output"]


# ── Layer 1：意图理解 ─────────────────────────────

@pytest.mark.parametrize(
    "result",
    INTENT_RESULTS,
    ids=[r["input"][:20] for r in INTENT_RESULTS],
)
def test_intent_understanding(result: dict) -> None:
    assert result["passed"], (
        f"score={result.get('score')}, reason={result.get('reason', '')[:150]}"
    )


# ── Layer 2：结构化输出 ───────────────────────────

@pytest.mark.parametrize(
    "result",
    STRUCT_RESULTS,
    ids=[r["input"][:20] for r in STRUCT_RESULTS],
)
def test_structured_output(result: dict) -> None:
    assert result["passed"], (
        f"errors={result.get('errors')}\noutput={result.get('actual_output', '')[:200]}"
    )
