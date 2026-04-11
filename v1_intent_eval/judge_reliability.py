import json
import math
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
ANNOTATIONS_FILE = BASE_DIR / "human_annotations.yaml"


def find_latest_run(model: str = "deepseek-chat") -> Path:
    """找 results/{model}/ 下最新的 run_*.jsonl 文件。"""
    model_dir = RESULTS_DIR / model
    runs = sorted(model_dir.glob("run_*.jsonl"))
    if not runs:
        # 回退：扫描所有模型
        runs = sorted(RESULTS_DIR.glob("*/run_*.jsonl"))
    if not runs:
        raise FileNotFoundError("results/ 下没有 run_*.jsonl 文件，请先运行评测。")
    return runs[-1]


def load_results(jsonl_path: Path) -> dict[str, dict]:
    rows = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            key = f"{row.get('test')}::{row.get('input')}"
            rows[key] = row
    return rows


def load_annotations() -> list[dict]:
    data = yaml.safe_load(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    return data.get("annotations", [])


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            original_index = indexed[k][0]
            ranks[original_index] = avg_rank
        i = j + 1
    return ranks


def pearson_corr(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def spearman_rho(xs: list[float], ys: list[float]) -> float:
    return pearson_corr(average_ranks(xs), average_ranks(ys))


def cohen_kappa(human: list[bool], machine: list[bool]) -> float:
    n = len(human)
    observed = sum(1 for h, m in zip(human, machine) if h == m) / n

    p_h_true = sum(1 for h in human if h) / n
    p_h_false = 1 - p_h_true
    p_m_true = sum(1 for m in machine if m) / n
    p_m_false = 1 - p_m_true
    expected = p_h_true * p_m_true + p_h_false * p_m_false

    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def main() -> None:
    run_path = find_latest_run()
    print(f"使用结果文件: {run_path.name}")
    results = load_results(run_path)
    annotations = load_annotations()

    merged = []
    skipped = 0
    for ann in annotations:
        # 从 dim_A/B/C 计算 human_score；跳过未填写的
        dims = [ann.get("dim_A"), ann.get("dim_B"), ann.get("dim_C")]
        if any(d is None for d in dims):
            skipped += 1
            continue
        human_score = round(sum(dims) / 3, 4)
        human_pass = human_score >= 0.7

        key = f"bloom_intent::{ann['input']}"
        if key not in results:
            print(f"[WARN] result not found for: {ann['input']}")
            continue
        row = results[key]
        machine_score = row.get("score")
        if machine_score is None:
            machine_score = 1.0 if row.get("passed") else 0.0
        machine_pass = row.get("passed")
        merged.append({
            "id": ann["id"],
            "input": ann["input"],
            "human_score": human_score,
            "human_pass": human_pass,
            "machine_score": machine_score,
            "machine_pass": machine_pass,
            "rationale": ann.get("rationale", ""),
        })

    if skipped:
        print(f"[INFO] 跳过 {skipped} 条未填写的标注")
    if len(merged) < 3:
        print(f"已填写 {len(merged)} 条，至少需要 3 条才能计算一致性。")
        return

    human_scores = [row["human_score"] for row in merged]
    machine_scores = [row["machine_score"] for row in merged]
    human_pass = [row["human_pass"] for row in merged]
    machine_pass = [row["machine_pass"] for row in merged]

    rho = spearman_rho(human_scores, machine_scores)
    kappa = cohen_kappa(human_pass, machine_pass)

    print("=== Pairwise Comparison ===")
    for row in merged:
        print(
            f"{row['id']} | human_score={row['human_score']:.1f} | "
            f"machine_score={row['machine_score']:.3f} | "
            f"human_pass={row['human_pass']} | machine_pass={row['machine_pass']} | "
            f"input={row['input']}"
        )

    print("\n=== Reliability Summary ===")
    print(f"Samples: {len(merged)}")
    print(f"Spearman rho: {rho:.4f}")
    print(f"Cohen kappa: {kappa:.4f}")

    print("\nInterpretation:")
    print("- rho 越接近 1，说明人和机器的排序越一致")
    print("- kappa > 0.6 通常说明一致性较好")
    print("- 如果 kappa 很低，优先怀疑 judge prompt / threshold / case 设计")


if __name__ == "__main__":
    main()
