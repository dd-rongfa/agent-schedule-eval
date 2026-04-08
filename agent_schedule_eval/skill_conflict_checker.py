"""
Skill Conflict Checker（静态冲突检测工具）
==========================================
用 LLM 静态分析一组 skill 文件，找出其中互相矛盾的指令。

使用方式：
  # 检查 skills/ 目录下的所有 skill（两两组合）
  python skill_conflict_checker.py

  # 只检查指定的两个 skill
  python skill_conflict_checker.py skills/schedule_skill.md skills/conflict_skill.md

  # 输出 JSON 格式
  python skill_conflict_checker.py --json

输出：每对 skill 的冲突报告，包含冲突点列表、严重程度和建议操作。
"""

import argparse
import json
import os
import sys
from itertools import combinations
from pathlib import Path

from openai import OpenAI

# ── 环境 ─────────────────────────────────────────────

ENV_FILE = Path(__file__).resolve().parent.parent / "examples" / "starter_judge" / ".env"
SKILLS_DIR = Path(__file__).parent / "skills"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

JUDGE_MODEL = os.getenv("JUDGE_MODEL", os.getenv("TARGET_MODEL", "deepseek-chat"))
API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ── 检测提示词 ────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个 AI Agent 系统的 Skill 质量审计员。
你的职责是分析两个 Skill 文件，找出其中互相矛盾的指令。

冲突定义：当同一个用户意图或同一个场景，两个 Skill 给出的处理方式不同，且不能同时被遵守时，即为冲突。

冲突类型：
- PARAMETER_CONFLICT：两个 Skill 对同一参数（如时间、工具选择）给出不同的默认值或推断规则
- STRATEGY_CONFLICT：两个 Skill 对同一场景（如用户改口、信息不足）给出不同的行动策略
- TOOL_CONFLICT：两个 Skill 对同一意图推荐使用不同的工具

输出格式（JSON，不要有 markdown 代码块）：
{
  "has_conflict": true/false,
  "conflict_count": <整数>,
  "conflicts": [
    {
      "type": "<PARAMETER_CONFLICT|STRATEGY_CONFLICT|TOOL_CONFLICT>",
      "severity": "<HIGH|MEDIUM|LOW>",
      "scene": "<触发该冲突的用户输入示例>",
      "skill_a_instruction": "<Skill A 的处理方式>",
      "skill_b_instruction": "<Skill B 的处理方式>",
      "impact": "<如果两个 Skill 同时存在，模型最可能出现什么行为>",
      "recommendation": "<建议如何解决>"
    }
  ],
  "summary": "<一段总结，说明这两个 Skill 能否安全共存>"
}
"""

USER_TEMPLATE = """\
请分析以下两个 Skill 文件的冲突：

=== Skill A: {name_a} ===
{content_a}

=== Skill B: {name_b} ===
{content_b}
"""


# ── 核心逻辑 ──────────────────────────────────────────

def check_pair(skill_a: Path, skill_b: Path) -> dict:
    """检测两个 skill 文件之间的冲突，返回结构化报告。"""
    content_a = skill_a.read_text(encoding="utf-8").strip()
    content_b = skill_b.read_text(encoding="utf-8").strip()

    user_msg = USER_TEMPLATE.format(
        name_a=skill_a.name,
        content_a=content_a,
        name_b=skill_b.name,
        content_b=content_b,
    )

    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()

    # 尝试解析 JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 模型可能加了 markdown 代码块，尝试提取
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
            except json.JSONDecodeError:
                result = {"has_conflict": None, "raw_response": raw, "parse_error": True}
        else:
            result = {"has_conflict": None, "raw_response": raw, "parse_error": True}

    result["skill_a"] = skill_a.name
    result["skill_b"] = skill_b.name
    return result


def print_report(report: dict) -> None:
    """人类可读格式输出单对报告。"""
    a, b = report["skill_a"], report["skill_b"]
    print(f"\n{'='*60}")
    print(f"  {a}  ×  {b}")
    print(f"{'='*60}")

    if report.get("parse_error"):
        print("  ⚠️  LLM 输出无法解析为 JSON，原始回复：")
        print(report.get("raw_response", ""))
        return

    has = report.get("has_conflict")
    count = report.get("conflict_count", 0)

    if not has:
        print("  ✅  未检测到冲突，两个 Skill 可以安全共存。")
        return

    print(f"  ❌  发现 {count} 处冲突\n")

    for i, c in enumerate(report.get("conflicts", []), 1):
        severity = c.get("severity", "?")
        icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
        print(f"  [{i}] {icon} {c.get('type')}  (严重程度: {severity})")
        print(f"      场景      : {c.get('scene', '')}")
        print(f"      {a[:20]:20s}: {c.get('skill_a_instruction', '')}")
        print(f"      {b[:20]:20s}: {c.get('skill_b_instruction', '')}")
        print(f"      模型行为  : {c.get('impact', '')}")
        print(f"      建议      : {c.get('recommendation', '')}")
        print()

    print(f"  📋  总结: {report.get('summary', '')}")


# ── 入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="检测 Skill 文件之间的指令冲突")
    parser.add_argument(
        "skills", nargs="*",
        help="要检测的 skill 文件路径（不传则检测 skills/ 目录下的所有 .md 文件）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    # 收集 skill 文件
    if args.skills:
        skill_files = [Path(p) for p in args.skills]
        for p in skill_files:
            if not p.exists():
                print(f"错误：文件不存在 {p}", file=sys.stderr)
                sys.exit(1)
    else:
        skill_files = sorted(SKILLS_DIR.glob("*.md"))
        if not skill_files:
            print(f"错误：{SKILLS_DIR} 下没有 .md 文件", file=sys.stderr)
            sys.exit(1)

    pairs = list(combinations(skill_files, 2))
    print(f"检测 {len(skill_files)} 个 Skill，共 {len(pairs)} 对组合...\n")

    all_reports = []
    for skill_a, skill_b in pairs:
        print(f"  分析: {skill_a.name} × {skill_b.name} ...", end=" ", flush=True)
        report = check_pair(skill_a, skill_b)
        all_reports.append(report)
        conflict_count = report.get("conflict_count", 0) if not report.get("parse_error") else "?"
        print(f"{'❌ ' + str(conflict_count) + ' 处冲突' if conflict_count else '✅ 无冲突'}")

    if args.json:
        print(json.dumps(all_reports, ensure_ascii=False, indent=2))
    else:
        for report in all_reports:
            print_report(report)

        # 汇总
        total_conflicts = sum(
            r.get("conflict_count", 0)
            for r in all_reports
            if not r.get("parse_error") and r.get("has_conflict")
        )
        conflicted_pairs = sum(
            1 for r in all_reports
            if not r.get("parse_error") and r.get("has_conflict")
        )
        print(f"\n{'='*60}")
        print(f"  汇总：{len(pairs)} 对中，{conflicted_pairs} 对有冲突，共 {total_conflicts} 处")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
