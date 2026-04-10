# Agent 定时任务能力评测

> Bloom 认知分层 × LLM Judge × Function Calling × Skill 注入 × Action Hallucination — 五层评测量化模型"说到做不到"的鸿沟。

**设计思路**：不信任评测工具本身 → 先用 15 个人工标注验证 Judge 可信度（κ=0.73），再用可信的 Judge 跑 218 条自动化评测，最后用对照实验验证 Skill 注入的真实收益。

**项目起源**：2026 年初部署开源 Agent 项目 [nanobot](https://github.com/HKUDS/nanobot)（OpenClaw 简化版），手动测试发现其定时任务几乎全部提前触发。这不是个别 bug，而是模型在"自然语言→时间参数→工具调用"链路上的系统性短板。随后通过 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 系统学习 Agent 架构原理，并将这些失效观察系统化为本评测框架。

**项目定位**：这是一个小而完整的 Agent 评测原型 —— 效果不满意可以换模型，方法是可复用的。clone 后 30 分钟即可跑通全流程，也可以直接复用评测框架换成你自己的场景。

## 核心发现

1. **说到做不到** — 模型用自然语言描述意图时通过率 65%，给了真实工具后骤降至 13%。纯文本评测严重高估执行能力。
2. **弱点是维度特异的** — MiMo 在"分析"层全灭（0%），但在"评价"层反超 DeepSeek（80% vs 60%）。整体分数掩盖了认知短板。
3. **Skill 写法质量 >> 有无 Skill** — 无 Skill 通过率 7%，错误 Skill 同样 7%（模型能忽略），正确 Skill 经三轮迭代达到 73%。效果取决于写法质量而非有没有。
4. **矛盾 Skill 比缺失 Skill 更危险** — 同一组矛盾 Skill 让 DeepSeek 从 73% 崩到 7%，MiMo 却升到 87%。冲突容忍度是模型特异的。
5. **行动幻觉：做了但做错了 vs 压根没做** — DeepSeek 4/6 故障场景根本不调用工具（L0 缺失），MiMo 6/6 都调用但仅 33% 检测到异常，17% 结果属实。两种失败模式完全不同，传统评测无法区分。

## 仓库结构

```
├── agent_schedule_eval/         ← 核心：5 个 Phase 的完整评测
│   ├── test_bloom_eval.py       Phase 2: Bloom×意图理解 (LLM Judge)
│   ├── test_tool_calling.py     Phase 3: Function Calling 断言
│   ├── test_skill_loading.py    Phase 5: Skill 注入 5 组对照
│   ├── judge_reliability.py     Phase 1: Judge 可信度 (κ=0.73)
│   ├── test_action_hallucination.py  Phase 6: 行动幻觉双维度检测
│   ├── flaky_tools.py           FlakyScheduler 故障注入模拟器
│   ├── verify_results.py        数据自检：7 项确定性校验（无 LLM 调用）
│   ├── skill_conflict_checker.py  静态 Skill 冲突检测工具
│   ├── baseline_compare.py      多模型对比 + 热力图
│   ├── skills/                  4 个 Skill 文件（正确/错误/矛盾）
│   └── results/                 7 份 JSONL 结果 (218 条) + 热力图
│
├── examples/                    ← 附录：LLM Judge + promptfoo 独立 demo + 定时任务 promptfoo 版
├── .env.example                 环境变量模板
└── requirements.txt             Python 依赖
```

## 评测方法

### 三层架构

| 层级 | 评测方式 | 判定方法 | 发现 |
|------|---------|---------|------|
| 意图理解 | 模型输出自然语言 | LLM Judge 打分 | DeepSeek 65%, MiMo 48% |
| 工具调用 | 模型发起 tool_calls | 确定性断言 | DeepSeek 13%, MiMo 20% |
| Skill 注入 | 5 组对照实验 | 确定性断言 | 无→7%, v3→73%, 矛盾→7% |
| 行动幻觉 | 故障注入 + 双维度判定 | 关键词 + 事实核验 | DeepSeek B:50%/O:0%, MiMo B:33%/O:17% |

### Bloom 认知分层

24 个测试用例按 Bloom's Taxonomy 六层组织（Remember → Create），验证认知层级越高通过率越低的核心预测。

### Judge 可信度

使用 LLM Judge 前先验证其可靠性：15 个人工标注样本，Cohen's κ = 0.73，Spearman ρ = 0.63，3 次重测 σ < 0.1。

## 快速开始

```bash
# 克隆
git clone https://github.com/dd-rongfa/agent-schedule-eval.git
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

# Phase 6: Action Hallucination (故障注入 + 双维度检测)
python agent_schedule_eval/test_action_hallucination.py
# 切换到 MiMo:
TARGET_MODEL=mimo-v2-pro TARGET_API_KEY=xxx TARGET_BASE_URL=xxx python agent_schedule_eval/test_action_hallucination.py
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
| `results/results.jsonl` | 2 | DeepSeek | 26 |
| `results/results_mimo_v2_pro.jsonl` | 2 | MiMo | 26 |
| `results/results_tool_calling.jsonl` | 3 | DeepSeek | 15 |
| `results/results_tool_calling_mimo.jsonl` | 3 | MiMo | 15 |
| `results/results_skill_loading.jsonl` | 5 | DeepSeek | 75 |
| `results/results_skill_loading_mimo.jsonl` | 5 | MiMo | 45 |
| `results/results_action_hallucination.jsonl` | 6 | DeepSeek + MiMo | 16 |

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

## 数据自检：谁来检测评测本身的幻觉？

本项目由人和 AI 协作开发。AI 写评测代码、跑评测、分析结果 —— 这条链路本身就是幻觉高发区。我们在开发过程中确实遇到了：

| 实际发生的问题 | 根因 | 后果 |
|--------------|------|------|
| MiMo Phase 6 数据被覆盖丢失 | 环境变量污染 + 盲写 append 模式 | 结果文件只有 DeepSeek，MiMo 数据全丢 |
| Phase 2/3/5 存在重复记录 | 多次 pytest 运行叠加 append | 144 条中有 69 条重复 |
| results.jsonl 缺少 model 字段 | 早期代码未写入模型标记 | 无法确认数据来源 |
| README 声称的记录数与实际不符 | 手动填写，更新滞后 | 72 vs 27，误差 167% |

这些问题不是假设，是真实发生的。首次运行 `verify_results.py` 检出 **40 errors + 28 warnings**：

```
首次自检结果（修复前）:
  - results.jsonl: 27 条记录缺少 model 字段 → 无法确认数据来源
  - results_skill_loading.jsonl: 69 条重复（同一用例被多次 pytest 运行叠加）
  - results_action_hallucination.jsonl: MiMo 数据全丢（仅剩 DeepSeek 8 条 + 重复）
  - README 声称 72 条，实际 27 条（误差 167%）

修复后再跑: ALL 7 CHECKS PASSED, 0 errors, 0 warnings
```

我们选择在 README 中保留这段错误记录，而不是只展示修好后的结果。原因：**知道哪里会出错、出过错、怎么发现的 —— 这本身就是 Bloom 元认知维度的体现**。评测项目的可信度不来自"从未出过错"，而来自"出了错能被自己的机制捕获"。

修复方式：

1. **`verify_results.py` 七项自检** — 每次 push 前运行，检查 JSONL 格式、模型标记、重复记录、verdict 可复现性、FlakyScheduler 正确性、README 数字一致性、追溯字段完整性
2. **原子写入 + 去重** — Phase 6 起改用"读取 → 保留其他模型 → 替换当前模型"的原子合并写入，避免 append 叠加
3. **run_id 追溯** — 每次运行生成 `{model}_{timestamp}_{uuid}` 唯一标识，可追溯每条记录来源
4. **inline 自检** — 写入后立即重跑判定逻辑，对比存储的 verdict 和重算结果

```bash
# push 前跑一遍，0 errors 才安全
python agent_schedule_eval/verify_results.py
```

> **设计原则**：如果你用 AI 写评测代码来评测 AI，那评测数据本身就需要一层不依赖 AI 判断的确定性校验。`verify_results.py` 里没有任何 LLM 调用 —— 全部是 JSON 解析、字符串匹配、计数比对。这是三层元认知的区别：让 LLM 在 prompt 里"自我反思"是最弱的（它的反思本身可以幻觉）；用确定性代码校验 LLM 输出是更强的；而把校验过程中发现的错误也记录下来，让"系统知道自己哪里会错"，才是 Bloom 元认知维度的完整实践。

## 读完这个项目你能回答什么

**怎样验证一个 LLM Judge 是否值得信任？**
> 构建人工标注金标准，计算 Cohen's κ（分类一致性）和 Spearman ρ（排名相关性），再用多次重测检查稳定性。κ ≥ 0.6 才可用于自动化评测。

**模型"说自己会做什么"和"真正调用工具去做"之间差距有多大？**
> 本项目实测差距巨大：意图理解 65%，工具调用仅 13%。主要失败模式是"信息已充分仍过度追问"——模型在有真实工具时反而更保守。纯文本评测会严重高估执行能力。

**给 Agent 注入 Skill 文档，效果取决于什么？有没有比"没有 Skill"更危险的情况？**
> 效果取决于写法质量（few-shot + 领域默认值），而非有没有。错误 Skill 无害（模型能忽略），但矛盾 Skill 会主动破坏性能（73%→7%），且冲突容忍度因模型而异。

**怎样用 Bloom 认知分层定位模型的维度特异性短板？**
> 将测试用例按 Bloom 六层组织，分层统计通过率。本项目发现 MiMo 在 L4 Analyze 全灭但 L5 Evaluate 反超，说明模型短板不是整体性的，整体分数会掩盖认知维度上的结构性缺陷。

**模型在工具"表面成功、实际失败"时会怎样？**
> 用 FlakyScheduler 注入三类隐性故障（静默丢弃、参数错配、部分失败），双维度检测模型反应：行为检测（有没有说"有问题"）和结果核实（汇报的细节是否属实）。DeepSeek 的主要问题是根本不调用工具（4/6 L0 缺失），MiMo 则全部调用但盲目确认虚构细节（3/6 fabricated）。两类失败结构性不同，单一指标无法区分。

**用 AI 协作开发评测项目，怎样防止评测数据本身出现幻觉？**
> 加一层不依赖 LLM 的确定性自检：JSONL 格式校验、重复检测、verdict 可复现验证、README 数字交叉核对。我们在本项目中实际遇到了环境变量污染导致数据丢失、append 叠加产生重复、README 数字与实际偏差 167% 等问题，全部由 `verify_results.py` 发现并修复。关键区分：让 AI 在 prompt 里"反思"是最弱的元认知（反思本身可以幻觉）；用确定性代码校验是更强的；把错误历史也保留下来，让系统"知道自己哪里会错"，才是完整的过程级元认知。

如果你对这些问题有了自己的理解，这个项目就完成了它的使命。

## 适用对象

- **想入门 Agent 评测的开发者**：`examples/` 提供从最简 Judge 到 promptfoo 的渐进式示例
- **想建立自己评测体系的团队**：`agent_schedule_eval/` 是完整可复用的框架，换场景只需改 YAML 用例和 Skill 文件
- **想快速复现结果的研究者**：所有 218 条记录以 JSONL 格式保存，可直接分析

### 如何扩展到你自己的场景

1. **换模型**：修改 `TARGET_MODEL` 环境变量，指向任何 OpenAI 兼容 API
2. **换场景**：编写新的 `schedule_cases_bloom.yaml`，替换测试用例
3. **换 Skill**：在 `skills/` 下新建你的领域 SOP，对照实验框架直接复用
4. **加模型**：更多模型对比只需新增 JSONL 结果文件，`baseline_compare.py` 自动生成热力图

## 技术栈

Python · OpenAI API · DeepEval · pytest · Function Calling · promptfoo · matplotlib
