# Agent 定时任务能力评测

> Bloom 认知分层 × LLM Judge × Function Calling × Skill 注入 — 四层评测量化模型"说到做不到"的鸿沟。

**设计思路**：不信任评测工具本身 → 先用 15 个人工标注验证 Judge 可信度（κ=0.73），再用可信的 Judge 跑 288+ 条自动化评测，最后用对照实验验证 Skill 注入的真实收益。

**项目起源**：2026 年初部署开源 Agent 项目 [nanobot](https://github.com/HKUDS/nanobot)（OpenClaw 简化版），手动测试发现其定时任务几乎全部提前触发。这不是个别 bug，而是模型在"自然语言→时间参数→工具调用"链路上的系统性短板。随后通过 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 系统学习 Agent 架构原理，并将这些失效观察系统化为本评测框架。

**项目定位**：这是一个小而完整的 Agent 评测原型 —— 效果不满意可以换模型，方法是可复用的。clone 后 30 分钟即可跑通全流程，也可以直接复用评测框架换成你自己的场景。

## 核心发现

1. **说到做不到** — 模型用自然语言描述意图时通过率 67%，给了真实工具后骤降至 19%。纯文本评测严重高估执行能力。
2. **弱点是维度特异的** — MiMo 在"分析"层全灭（0%），但在"评价"层反超 DeepSeek（80% vs 60%）。整体分数掩盖了认知短板。
3. **Skill 写法质量 >> 有无 Skill** — 三轮迭代将通过率从 12.5% 提升到 75%（+62.5%），而仅"有 skill"只提升 12.5%。
4. **矛盾 Skill 比缺失 Skill 更危险** — 同一组矛盾 Skill 让 DeepSeek 从 75% 崩到 6%，MiMo 却升到 88%。冲突容忍度是模型特异的。

## 仓库结构

```
├── agent_schedule_eval/         ← 核心：5 个 Phase 的完整评测
│   ├── test_bloom_eval.py       Phase 2: Bloom×意图理解 (LLM Judge)
│   ├── test_tool_calling.py     Phase 3: Function Calling 断言
│   ├── test_skill_loading.py    Phase 5: Skill 注入 5 组对照
│   ├── judge_reliability.py     Phase 1: Judge 可信度 (κ=0.73)
│   ├── skill_conflict_checker.py  静态 Skill 冲突检测工具
│   ├── baseline_compare.py      多模型对比 + 热力图
│   ├── skills/                  4 个 Skill 文件（正确/错误/矛盾）
│   └── results/                 6 份 JSONL 结果 (288+ 条) + 热力图
│
├── examples/                    ← 附录：LLM Judge + promptfoo 独立 demo + 定时任务 promptfoo 版
├── .env.example                 环境变量模板
└── requirements.txt             Python 依赖
```

## 评测方法

### 三层架构

| 层级 | 评测方式 | 判定方法 | 发现 |
|------|---------|---------|------|
| 意图理解 | 模型输出自然语言 | LLM Judge 打分 | DeepSeek 67%, MiMo 50% |
| 工具调用 | 模型发起 tool_calls | 确定性断言 | DeepSeek 19%, MiMo 25% |
| Skill 注入 | 5 组对照实验 | 确定性断言 | 无→12.5%, v3→75%, 矛盾→6% |

### Bloom 认知分层

24 个测试用例按 Bloom's Taxonomy 六层组织（Remember → Create），验证认知层级越高通过率越低的核心预测。

### Judge 可信度

使用 LLM Judge 前先验证其可靠性：15 个人工标注样本，Cohen's κ = 0.73，Spearman ρ = 0.63，3 次重测 σ < 0.1。

## 快速开始

```bash
# 克隆
git clone https://github.com/dd-rongfa/llm_as_a_judge.git
cd llm_as_a_judge

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
cp .env.example examples/starter_judge/.env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY

# Phase 1: 验证 Judge 可信度
python agent_schedule_eval/judge_reliability.py

# Phase 2: Bloom × 意图理解评测
python -m pytest agent_schedule_eval/test_bloom_eval.py -v

# Phase 3: Function Calling 评测
python -m pytest agent_schedule_eval/test_tool_calling.py -v

# Phase 5: Skill Loading 对照实验
python -m pytest agent_schedule_eval/test_skill_loading.py -v

# 生成 Bloom × Model 热力图
python agent_schedule_eval/baseline_compare.py

# Skill 冲突检测
python agent_schedule_eval/skill_conflict_checker.py agent_schedule_eval/skills/schedule_skill.md agent_schedule_eval/skills/conflict_skill.md
```

### 切换目标模型

```bash
# 默认测 DeepSeek，切换到 MiMo:
export TARGET_MODEL=mimo-v2-pro
export TARGET_ENV_PREFIX=MiMo
export RESULTS_FILE=agent_schedule_eval/results_mimo_v2_pro.jsonl
python -m pytest agent_schedule_eval/test_bloom_eval.py -v
```

## 结果数据

所有评测结果以 JSONL 格式保存，每条记录包含：

```json
{
  "timestamp": "2026-04-07T10:23:45Z",
  "test": "bloom_intent",
  "bloom_level": "L3_Apply",
  "input": "每天早上9点提醒我打卡",
  "actual_output": "...",
  "expected_output": "...",
  "passed": true,
  "score": 0.85,
  "model": "deepseek-chat",
  "latency_ms": 1234
}
```

| 文件 | Phase | 模型 | 记录数 |
|------|-------|------|--------|
| `results/results.jsonl` | 2 | DeepSeek | 72 |
| `results/results_mimo_v2_pro.jsonl` | 2 | MiMo | 72 |
| `results/results_tool_calling.jsonl` | 3 | DeepSeek | 16 |
| `results/results_tool_calling_mimo.jsonl` | 3 | MiMo | 16 |
| `results/results_skill_loading.jsonl` | 5 | DeepSeek | 80 |
| `results/results_skill_loading_mimo.jsonl` | 5 | MiMo | 48 |

## 已知局限与设计取舍

本项目有意控制在小规模，以保证每一层都可验证、可复现：

- **样本量小**：每层 4-5 题，统计波动大 — 但已足够暴露"说到做不到"、"冲突崩溃"等结构性问题
- **双模型**：仅 DeepSeek + MiMo，结论不可直接泛化 — 但框架支持一行环境变量切换模型
- **单轮测试**：未覆盖多轮对话状态管理
- **Judge 局限**：κ=0.73 属"较好"但非"很好"，模糊场景仍有偏差
- **低复杂度域**：定时任务相对简单，高复杂度 SOP 场景待验证

### 本项目有意不覆盖

- 大规模 benchmark 排行榜（不是目标，做可复现的方法论原型才是）
- 多轮对话状态管理（属于下一阶段课题）
- 生产部署与 CI 集成（评测逻辑和工程化是两件事）

## 读完这个项目你能回答什么

**怎样验证一个 LLM Judge 是否值得信任？**
> 构建人工标注金标准，计算 Cohen's κ（分类一致性）和 Spearman ρ（排名相关性），再用多次重测检查稳定性。κ ≥ 0.6 才可用于自动化评测。

**模型"说自己会做什么"和"真正调用工具去做"之间差距有多大？**
> 本项目实测差距巨大：意图理解 67%，工具调用仅 19%。主要失败模式是"信息已充分仍过度追问"——模型在有真实工具时反而更保守。纯文本评测会严重高估执行能力。

**给 Agent 注入 Skill 文档，效果取决于什么？有没有比"没有 Skill"更危险的情况？**
> 效果取决于写法质量（few-shot + 领域默认值），而非有没有。错误 Skill 无害（模型能忽略），但矛盾 Skill 会主动破坏性能（75%→6%），且冲突容忍度因模型而异。

**怎样用 Bloom 认知分层定位模型的维度特异性短板？**
> 将测试用例按 Bloom 六层组织，分层统计通过率。本项目发现 MiMo 在 L4 Analyze 全灭但 L5 Evaluate 反超，说明模型短板不是整体性的，整体分数会掩盖认知维度上的结构性缺陷。

如果你对这些问题有了自己的理解，这个项目就完成了它的使命。

## 适用对象

- **想入门 Agent 评测的开发者**：`examples/` 提供从最简 Judge 到 promptfoo 的渐进式示例
- **想建立自己评测体系的团队**：`agent_schedule_eval/` 是完整可复用的框架，换场景只需改 YAML 用例和 Skill 文件
- **想快速复现结果的研究者**：所有 288+ 条记录以 JSONL 格式保存，可直接分析

### 如何扩展到你自己的场景

1. **换模型**：修改 `TARGET_MODEL` 环境变量，指向任何 OpenAI 兼容 API
2. **换场景**：编写新的 `schedule_cases_bloom.yaml`，替换测试用例
3. **换 Skill**：在 `skills/` 下新建你的领域 SOP，对照实验框架直接复用
4. **加模型**：更多模型对比只需新增 JSONL 结果文件，`baseline_compare.py` 自动生成热力图

## 技术栈

Python · OpenAI API · DeepEval · pytest · Function Calling · promptfoo · matplotlib
