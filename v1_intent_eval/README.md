# v1 — 意图理解评测

> 不给工具、不给多轮——纯靠语言理解，模型能把定时任务的意图说对吗？
> 用 DeepEval/GEval (LLM Judge) + 确定性 JSON 断言，4 模型 × 3 轮。

---

## 这版 v1 在测什么

给模型一个 system prompt（描述 5 个可用动作）和一条用户消息，让它用自然语言说出"我会调用什么动作、时间参数是什么、提醒内容是什么"。**没有 tool schema，没有多轮对话，没有 mock 环境**——纯测语言层面的意图理解和常识推断。

23 条 intent case 覆盖 7 个类别（简单定时 / 周期任务 / 取消 / 创建+取消 / 动态修改 / 模糊时间 / 边界异常），另有 3 条 JSON 结构化输出断言。

5 个可用动作：`create_schedule` / `create_recurring` / `cancel_schedule` / `clarify` / `reject`

## 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 意图评分 | DeepEval GEval (LLM Judge) | 自由文本输出无法确定性断言 |
| 结构评分 | JSON 字段断言 | action/delay/time 可精确匹配 |
| 认知分层 | Bloom's Taxonomy L1-L6 | 区分记忆/理解/应用/分析/评价/创造 |
| Judge 校准 | Cohen's κ + Spearman ρ | 量化 LLM Judge 与人类一致性 |
| 并发 | ThreadPoolExecutor | I/O 密集型 API 调用 |

## Judge 可信度验证

使用 LLM Judge 前必须先验证 Judge 本身是否可靠：

- 15 个人工标注样本（3 维度：动作识别 / 参数正确 / 行为合理，各 0/0.5/1）
- **Cohen's κ = 0.84**（"几乎完全一致"，>0.8）
- **Spearman ρ = 0.87**（排名高度相关）
- 唯一分歧点："昨天下午3点提醒我开会"——GEval 对"先说 create 再补救 reject"偏宽容（给 0.8 pass），人类判 fail

→ 结论：Judge 一致性优秀，已知偏差为 GEval 对补救行为偏宽容。

## 评测结果

### 模型通过率对比（4 模型 × 3 轮均值）

| 模型 | 意图理解通过率 | case 数 | 平均延迟 | 结构化输出 |
|------|---------------|---------|----------|-----------|
| deepseek-chat | **78.3%** | 23 | 2.6s | 100% |
| doubao-seed-2-0-pro | 72.5% ± 2.5% | 23 | 14.1s | 100% |
| deepseek-reasoner | 60.9% ± 4.3% | 23 | 23.1s | 88.9% |
| mimo-v2-pro | 59.4% ± 5.0% | 23 | 15.7s | 100% |

### 核心意图 vs 边界异常 拆分

| 模型 | 核心意图 (16 cases) | 边界异常 (7 cases) | 说明 |
|------|--------------------|--------------------|------|
| deepseek-chat | **93.8%** | 42.9% | 核心极强，但从不 reject |
| doubao | 66.7% | **85.7%** | 边界判断最好 |
| deepseek-reasoner | 60.4% | 61.9% | 过度谨慎，什么都 clarify |
| mimo | 60.4% | 57.1% | 整体偏弱 |

**这是 v1 最有价值的发现**——混合通过率（78% / 72% / 60% / 59%）掩盖了截然不同的失败模式：

### 发现 1：对话模型 vs 推理模型的行为差异

deepseek-chat（对话模型）核心意图 93.8%，deepseek-reasoner（推理模型）只有 60.4%。

原因不是推理能力不足，而是 **reasoner 过度谨慎**：用户说"帮我设个 10 分钟后的提醒，不对改成 20 分钟，算了还是 30 分钟"，chat 直接创建 30 分钟提醒（正确），reasoner 说"提醒内容没说，我需要追问"（错误）。推理模型把"缺任何一个参数"都当作必须追问的理由，而对话模型擅长常识补全。

→ **v1 测的是"对话理解 + 常识推断"能力，推理模型在这个场景反而是劣势。**

### 发现 2：reject 能力是真正的区分度

| 边界 case | 期望 | deepseek-chat | doubao | reasoner | mimo |
|---|---|---|---|---|---|
| 昨天下午3点 | reject | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ | 3/3 ✓ |
| 如果下雨提醒我 | reject | **0/3** | 3/3 ✓ | — | 3/3 ✓ |
| 100个每秒1个 | reject | **0/3** | 3/3 ✓ | 3/3 ✓ | 1/3 |
| 3000年1月1日 | reject | **0/3** | 2/3 | **0/3** | **0/3** |
| 0分钟后 | reject | **0/3** | **0/3** | **0/3** | **0/3** |

deepseek-chat 核心能力最强但**几乎从不拒绝**——"3000年1月1日提醒我"它也照做。doubao 在 reject 判断上表现最好。"0分钟后"所有模型全军覆没，说明当前模型普遍缺乏对无意义参数的判断力。

### 发现 3：为什么需要 v2

v1 测的是"模型能不能用自然语言描述正确意图"，但即使描述正确，也不代表在真实工具调用场景下能正确执行。v1 的核心局限：

1. **单轮测试**：无法测"查询时间→创建提醒→验证结果"这种多步链路
2. **无工具 Schema**：模型没有参数约束，可以编造任何格式的回答
3. **GEval 评分有模糊性**：对"先说错再补救"的模式偏宽容

→ **v2 用 20 工具 + 多轮 agent_loop + 确定性断言，直接验证"做没做对"而非"说没说对"。**

### Difficulty × Model 通过率

| Difficulty | deepseek-chat | deepseek-reasoner | doubao | mimo |
|-----------|--------|--------|--------|--------|
| easy | 85.7% | 71.4% | 71.4% | 71.4% |
| medium | 71.4% | 71.4%±14.3% | **100.0%** | 81.0%±8.2% |
| hard | **77.8%** | 44.4% | 51.9%±6.4% | 33.3%±11.1% |

### Bloom Level × Model 通过率

| Bloom | deepseek-chat | deepseek-reasoner | doubao | mimo |
|-------|--------|--------|--------|--------|
| L1 Remember | **100%** | 50% | 50% | 50% |
| L2 Understand | 100% | 100% | 100% | 100% |
| L3 Apply | **100%** | 83%±14% | 100% | 92%±14% |
| L4 Analyze | **80%** | 27%±12% | 53%±12% | 20% |
| L5 Evaluate | 63% | 58%±19% | 63% | 63%±13% |
| L6 Create | 0% | 67%±58% | **100%** | 0% |

---

## 文件说明

```
v1_intent_eval/
├── README.md              当前说明文档
├── run.py                 入口：两阶段批量评测（collect → judge → analyze）
├── analyze.py             入口：结果分析（聚合 + Markdown/JSON/report/heatmap）
├── judge_reliability.py   入口：Judge 可信度验证（Cohen's κ + Spearman ρ）
├── schedule_cases.yaml    26 条案例定义（23 intent + 3 struct）
├── human_annotations.yaml 15 个人工标注金标准（Judge 校准用）
├── results/
│   ├── {model}/           按模型分文件夹
│   │   ├── raw_{ts}.jsonl     Phase 1 收集的原始模型响应
│   │   └── run_{ts}.jsonl     Phase 2 评分后的结果（与 analyze 兼容）
│   ├── archive/           冻结历史快照（早期产出，仅作参考）
│   └── report.md          analyze.py 自动生成的结论性报告
└── eval/                  内部模块（不直接调用）
    ├── collect.py         Phase 1：调用目标模型 API，保存原始响应
    ├── judge.py           Phase 2：GEval 评分 + JSON 确定性断言
    ├── test_schedule_eval.py  pytest 薄封装：读取 scored results 做参数化断言
    └── mock_tools.py      FakeScheduler（记录工具调用轨迹）
```

## 架构：两阶段流水线

```
Phase 1 (collect)               Phase 2 (judge)              分析
目标模型 API 调用 ──────→ GEval / JSON 断言 ──────→ analyze.py
  └→ raw_{ts}.jsonl             └→ run_{ts}.jsonl            └→ report.md
```

**设计理念**：数据收集（collect）与评价（judge）分离。
- **collect** 只调目标模型 API，保存原始响应（可重放）
- **judge** 读取 raw 文件，调 GEval（Judge 模型）打分 + JSON 确定性断言
- 多轮策略：**collect ×N, judge ×1**（度量的是目标模型方差，不是 Judge 方差）
- 并发模型：ThreadPoolExecutor（I/O 密集型，API 为主要开销）

## 复现指南

```bash
# 0. 环境准备
pip install deepeval pyyaml seaborn matplotlib numpy
# 配置 .env: DEEPSEEK_API_KEY, MiMo_API_KEY, Doubao_API_KEY

# 1. 正式评测：4 模型 × 3 轮
cd v1_intent_eval
python run.py --runs 3

# 2. 单模型快速调试
python run.py --models deepseek-chat --runs 1 --workers 8

# 3. 分阶段执行
python run.py --models deepseek-chat --phase collect   # 只收集
python run.py --models deepseek-chat --phase judge     # 只评分

# 4. 单独生成分析报告
python analyze.py --latest 3 --report

# 5. Judge 校准
python judge_reliability.py
# → Cohen's κ = 0.84, Spearman ρ = 0.87
```

### run.py 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--models` | 全部 4 个 | 要跑的模型列表 |
| `--runs` | 1 | 每模型跑几轮 |
| `--workers` | 8 | 每阶段并发线程数 |
| `--phase` | all | `all` / `collect` / `judge` |
| `--no-analyze` | false | 跑完不自动分析 |
