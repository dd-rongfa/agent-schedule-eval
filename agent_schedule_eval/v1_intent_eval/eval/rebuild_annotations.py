"""
从最新 run_*.jsonl 重建 human_annotations.yaml 模板。

策略：
  - 从 bloom_intent 结果中分层抽样 15 条（easy 5 / medium 5 / hard 5）
  - 对 input 匹配旧标注的，carry forward human_score 作为参考
  - 对新 case，human_score 留 null 待人工填写
  - actual_output 全部来自最新 run（不沿用旧的）

用法：
    python scripts/_rebuild_annotations.py
    # 生成 human_annotations.yaml（备份旧版为 human_annotations.yaml.bak）
"""

import json
import shutil
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
ANNOTATIONS_FILE = BASE_DIR / "human_annotations.yaml"

# 每个难度抽多少条
SAMPLE_PER_DIFFICULTY = 5


def find_latest_run() -> Path:
    runs = sorted(RESULTS_DIR.glob("*/run_*.jsonl"))
    if not runs:
        raise FileNotFoundError("No run_*.jsonl found")
    return runs[-1]


def load_run_intents(path: Path) -> list[dict]:
    """加载 bloom_intent 记录，按 input 去重（保留最后一条）。"""
    by_input: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("test") == "bloom_intent":
                by_input[r["input"]] = r
    return list(by_input.values())


def load_old_annotations() -> dict[str, dict]:
    if not ANNOTATIONS_FILE.exists():
        return {}
    data = yaml.safe_load(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    return {a["input"]: a for a in data.get("annotations", [])}


def sample_cases(rows: list[dict]) -> list[dict]:
    """分层抽样：每个 difficulty 取 SAMPLE_PER_DIFFICULTY 条。"""
    by_diff: dict[str, list[dict]] = {}
    for r in rows:
        d = r.get("difficulty", "unknown")
        by_diff.setdefault(d, []).append(r)

    sampled = []
    for diff in ["easy", "medium", "hard"]:
        pool = by_diff.get(diff, [])
        # 优先选 pass/fail 都有的（增加 κ 区分度）
        failed = [r for r in pool if not r.get("passed")]
        passed = [r for r in pool if r.get("passed")]
        # 尽量一半 pass 一半 fail
        n = min(SAMPLE_PER_DIFFICULTY, len(pool))
        n_fail = min(len(failed), n // 2 + 1)
        n_pass = n - n_fail
        selected = failed[:n_fail] + passed[:n_pass]
        sampled.extend(selected[:n])

    return sampled


RUBRIC_HEADER = """\
# 人工标注模板 v3 — 基于最新评测结果重建
# 用途：验证 LLM-as-a-Judge (GEval) 与人类评分的一致性
# 生成方式：scripts/_rebuild_annotations.py 从最新 run 自动抽样
#
# ════════════════════════════════════════════════════
# 评分量表 (Scoring Rubric) — 共 5 个维度，每维度 0.2 分
# ════════════════════════════════════════════════════
#
# 维度 A：动作识别（0.2 分）
#   0.2 = 选对了正确的动作（create_schedule / cancel_schedule / clarify 等）
#   0.1 = 动作部分正确
#   0.0 = 动作完全错误
#
# 维度 B：时间解析（0.2 分）
#   0.2 = 时间理解完全正确
#   0.1 = 时间大致正确但有偏差
#   0.0 = 时间理解错误或完全忽略
#   N/A = 输入中没有时间信息
#
# 维度 C：完整性判断（0.2 分）
#   0.2 = 正确判断信息是否充足
#   0.1 = 判断基本对但有小问题
#   0.0 = 该追问没追问或不该追问却追问了
#
# 维度 D：不编造（0.2 分）
#   0.2 = 没有捏造任何不存在的信息
#   0.1 = 轻微编造（不影响核心判断）
#   0.0 = 严重编造
#
# 维度 E：语用与上下文（0.2 分）
#   0.2 = 考虑了语境、紧急性、常识等
#   0.1 = 部分考虑
#   0.0 = 完全忽略语境因素
#   N/A = 不涉及特殊语用推理
#
# human_score = A + B + C + D + E，满分 1.0
# human_pass = human_score >= 0.7
# ════════════════════════════════════════════════════
"""


def build_annotation(idx: int, run_row: dict, old_ann: dict | None) -> dict:
    ann: dict = {
        "id": f"A{idx:02d}",
        "input": run_row["input"],
        "difficulty": run_row.get("difficulty"),
        "actual_output": run_row.get("actual_output", ""),
        "expected": run_row.get("expected", ""),
        "machine_score": run_row.get("score"),
        "machine_pass": run_row.get("passed"),
    }

    if old_ann and old_ann.get("human_score") is not None:
        # carry forward, but mark as reference — human should re-check
        ann["human_score"] = old_ann["human_score"]
        ann["human_pass"] = old_ann["human_pass"]
        ann["rationale"] = old_ann.get("rationale", "")
        ann["_carried_from_old"] = True
    else:
        ann["human_score"] = None  # ← 待填写
        ann["human_pass"] = None
        ann["rationale"] = ""

    return ann


def main() -> None:
    run_path = find_latest_run()
    print(f"结果文件: {run_path.name}")

    rows = load_run_intents(run_path)
    print(f"去重后 bloom_intent: {len(rows)} 条")

    old_anns = load_old_annotations()
    print(f"旧标注: {len(old_anns)} 条")

    sampled = sample_cases(rows)
    print(f"抽样: {len(sampled)} 条")

    annotations = []
    carried = 0
    for i, row in enumerate(sampled, 1):
        old = old_anns.get(row["input"])
        ann = build_annotation(i, row, old)
        if ann.get("_carried_from_old"):
            carried += 1
            del ann["_carried_from_old"]
        annotations.append(ann)

    # 备份旧文件
    if ANNOTATIONS_FILE.exists():
        bak = ANNOTATIONS_FILE.with_suffix(".yaml.bak")
        shutil.copy2(ANNOTATIONS_FILE, bak)
        print(f"旧标注已备份: {bak.name}")

    # 写新文件
    content = RUBRIC_HEADER + "\nannotations:\n"
    for ann in annotations:
        content += f"\n  - id: \"{ann['id']}\"\n"
        content += f"    input: \"{ann['input']}\"\n"
        content += f"    difficulty: {ann['difficulty']}\n"
        content += f"    actual_output: |\n"
        for line in ann["actual_output"].splitlines():
            content += f"      {line}\n"
        content += f"    expected: \"{ann['expected']}\"\n"
        content += f"    machine_score: {ann['machine_score']}\n"
        content += f"    machine_pass: {'true' if ann['machine_pass'] else 'false'}\n"

        if ann["human_score"] is not None:
            content += f"    human_score: {ann['human_score']}\n"
            content += f"    human_pass: {'true' if ann['human_pass'] else 'false'}\n"
            content += f"    rationale: \"{ann['rationale']}\"\n"
        else:
            content += f"    human_score:   # ← 待填写 (0.0 ~ 1.0)\n"
            content += f"    human_pass:    # ← 待填写 (true/false)\n"
            content += f"    rationale: \"\"  # ← 待填写\n"

    ANNOTATIONS_FILE.write_text(content, encoding="utf-8")
    print(f"\n已生成: {ANNOTATIONS_FILE.name}")
    print(f"  - 总计 {len(annotations)} 条")
    print(f"  - 继承旧分数 {carried} 条（请复核 actual_output 是否变化）")
    print(f"  - 待填写 {len(annotations) - carried} 条")
    print(f"\n下一步：人工填写 human_score / human_pass / rationale，然后运行：")
    print(f"  python scripts/judge_reliability.py")


if __name__ == "__main__":
    main()
