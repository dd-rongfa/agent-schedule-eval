# v2 — 多工具多轮 Agent Tool-Calling 评测

> v1 测的是"模型会不会描述意图"，v2 测的是"模型在 20 个工具面前能不能正确执行，以及工具出错时能不能发现"。

v2 评测工具调用能力有**两个维度**：

| 维度 | 测什么 | 规模 | 核心指标 |
|------|--------|------|---------|
| **正向执行力** | 工具正常时，模型能不能完成查询→执行→验证的多轮链路 | 70 case × 4 模型 × 3 轮 | 通过率 |
| **异常鲁棒性** | 工具故障时，模型能不能发现异常而非盲目确认成功 | 10 case × 4 模型 × 2 温度 × 3 轮 | 行为检测率 (B) / 结果准确率 (O) |

两个维度**共享同一套基础设施**（agent_loop、20 工具、ToolDispatcher），区别仅在后端是正常的还是注入了故障。就像汽车测试，日常驾驶和碰撞测试是同一个评测阶段的两个维度。

---

## 这版 v2 在解决什么问题

v1 验证了评测框架（Judge 可信度 + Bloom 分层），但它测的是"模型能不能用自然语言描述正确意图"。这和真实工具执行能力是**不同维度**——v1 最强的 deepseek-chat（78%）在 v2 排名第三（89%），v1 最弱的 mimo（59%）反而在 v2 排名第一（95%）。**语言描述能力无法预测工具执行能力，排名都反了。**

真实的工具调用几乎不是一次请求就完成的。用户说"帮我设个明天的提醒"，正确行为是：先 `get_current_time` 确认今天日期 → 再 `create_schedule` 设提醒 → 可选 `list_schedules` 验证是否创建成功。这条**查询→执行→验证**的多轮链路，加上 tool schema 的结构化约束，是 v1 的单轮文本评测覆盖不到的。

而真实系统中工具还可能静默失败、返回错误参数、或部分操作失败。如果模型在工具返回异常时仍然盲目确认成功（action hallucination），用户会收到错误信息却浑然不觉。因此 v2 不仅测"做对"，还测"发现做错"。

v2 做了四件关键的事：

1. **多轮 tool-calling 框架**：`agent_loop.py` 实现多轮循环（最多 10 轮），模型可以持续发起 tool_calls 直到给出最终回复，支持查询→执行→验证的完整链路。
2. **20 工具的干扰环境**：从 3 个日程工具扩展到 5 大类 20 工具，主动制造相邻工具干扰，逼模型暴露真实路由策略。
3. **确定性断言替代 LLM Judge**：不再依赖打分器，而是直接断言：调没调工具、调了哪个、参数对不对、顺序对不对。
4. **故障注入测异常鲁棒性**：`FlakyScheduler` 模拟 4 种工具故障模式，测试模型能否识别异常返回并如实报告。

---

## 评测设计

### 共享基础设施

两个维度共享同一套工具环境和执行引擎：

- **20 工具**：日程提醒（6）、待办事项（4）、媒体播放（4）、应用操作（2）、系统操作（3）、后台任务（1）
- **agent_loop**：多轮 tool-calling 循环，最多 10 轮，内置 429/5xx 退避重试
- **ToolDispatcher**：统一工具路由，正向测试接 `FakeScheduler`（正常后端），异常测试接 `FlakyScheduler`（故障注入后端）

工具由 [mock_tools.py](./eval/mock_tools.py) 里的 Fake backend 记录调用轨迹而不产生真实副作用。

### 维度一：正向执行力（70 case）

#### 三轴分类体系

旧版 Bloom 分层在 Agent 场景里有一个结构性问题：它把"认知层级"和"信息完整度"混在了一起。比如"设个闹钟八点"不一定比"取消明天下午三点的提醒"简单，因为前者信息不完整，合理行为应该是追问。

所以当前 v2 改为三轴分类：

- `operation`：direct / clarify / compound / implicit
- `context`：empty / simple / rich
- `turns`：single / clarify_turn / correct_turn

这套分类更贴近真实 Agent 失效模式：到底是任务类型难，还是背景干扰多，还是多轮状态容易丢。

#### Case 收敛原则

自动化 case 的设计原则只有一句话：**把路堵死，只保留一条可接受答案路径。**

这意味着：

- 能明确断言的 case 才进入回归集。
- 没有唯一正确路径的 case 不硬塞进自动化。
- "建议型""开放型""系统级编排型"场景保留为人工探索，不污染主 benchmark。

因此当前 [schedule_cases.yaml](./schedule_cases.yaml) 一共 85 条样例，其中 70 条进入自动化回归（跳过 complex / manual_test_prompts，以及 boundary 中的 clarify/reject 类型）。

#### 自动化覆盖

| section | yaml 总数 | 自动化 | 说明 |
|---------|-----------|--------|------|
| direct | 13 | 13 | 信息完整，直接执行 |
| clarify | 7 | 7 | 信息不全，需追问 |
| compound | 8 | 8 | 多步组合操作 |
| correct_turn | 2 | 2 | 用户反悔修改 |
| implicit | 3 | 3 | 隐性意图 |
| rich_context | 5 | 5 | 5+ 提醒含干扰项 |
| tool_selection | 8 | 8 | 相邻工具干扰 |
| temporal_reasoning | 5 | 5 | 时间推理 |
| asr_tolerance | 8 | 8 | 语音识别容错 |
| boundary | 9 | 2 | 边界条件（7 条为 clarify/reject 型，跳过） |
| status_aware | 6 | 6 | 根据提醒状态做不同决策 |
| chain_reasoning | 3 | 3 | 查状态→推理→设提醒链路 |
| complex | 4 | 0 | 开放题，人工探索 |
| manual_test_prompts | 4 | 0 | 手工测试脚本 |

自动化总数：**70 case**（12 个 section）。

### 维度二：异常鲁棒性（10 case）

#### 动机

正向测试中工具总是返回正确结果。但真实系统中工具可能静默失败、返回错误参数、或部分操作失败。如果模型在工具返回异常时仍然盲目确认成功（action hallucination），用户会收到错误信息却浑然不觉。

#### 故障注入设计

`flaky_tools.py` 实现 `FlakyScheduler`，与正向测试的 `FakeScheduler` 接口兼容，通过 `ToolDispatcher` 热替换。故障只注入在**写操作**上（create/cancel），读操作（list/get_current_time）始终返回正常结果，模拟真实场景中"API 写入静默丢弃但查询接口正常"的常见故障模式。

- **4 种故障模式 × 2 case + 2 正常对照 = 10 case**
- **双维度评判**：行为检测（B）+ 结果准确（O），交叉得到 4 种 verdict
- **两轮追问**：第一轮执行 + 第二轮用户追问确认，测试模型是否在追问后修正

| 故障模式 | 注入行为 |
|---------|----------|
| Silent Drop | 工具返回空对象 `{}`，无任何字段 |
| Param Mismatch | 返回 ok 但关键参数被篡改（time/recurrence） |
| Content Mismatch | 返回 ok 但 content 被替换 |
| Partial Failure | 多步操作中 cancel 返回 warning |

---

## 基础设施

### `agent_loop.py`

多轮 tool-calling while loop：模型持续发起 `tool_calls`，直到输出最终文本回复或达到 `max_turns=10`。内置指数退避重试（429/5xx，最多 3 次），避免 API 限流导致空结果。

### `test_tool_calling.py`

1. 从 YAML 收集 70 个可自动断言的 case。
2. 为每个 case 注入对应的 mock 时间、提醒列表、待办列表、播放历史。
3. 用 `ThreadPoolExecutor(max_workers=MAX_WORKERS)` 并发执行，结果写入 `results/{model}/run_{timestamp}.jsonl`。

### `run.py`

一键多模型评测：模型间并行（ThreadPoolExecutor），同模型多轮串行（避免请求过载），跑完自动调 `analyze.py` 生成报告。

### `analyze.py`

从 `results/{model}/` 自动发现运行结果，取最新 N 轮聚合（均值±标准差），支持 `--markdown` / `--json` / `--report`（写入 `results/report.md`）。

### `provider.py`

通过 `TARGET_MODEL` 环境变量切换被测模型。当前配置 4 模型：deepseek-chat、deepseek-reasoner、mimo-v2-pro、doubao-seed-2-0-pro-260215。

评测采用 3 轮取均值，波动来自模型自身的非确定性（temperature > 0），不再叠加评分器随机性。

---

## 结果与发现

### 维度一：正向执行力

> 数据来源：`results/report.md`（由 `analyze.py --latest 3 --report` 自动生成）

#### 模型通过率对比（3 轮均值）

| 模型 | 通过率 | case 数 | 平均延迟 | 创建前先查 | 创建后验证 |
|------|--------|---------|----------|-----------|-----------|
| mimo-v2-pro | 95.2% ± 1.6% | 70 | 18.2s | 67% | 17% |
| deepseek-reasoner | 93.8% ± 2.2% | 70 | 20.7s | 72% | 13% |
| deepseek-chat | 88.1% ± 2.2% | 70 | 11.4s | 49% | 4% |
| doubao-seed-2-0-pro-260215 | 88.1% ± 2.2% | 70 | 22.3s | 28% | 0% |

#### 按 Section 拆分通过率

| section | deepseek-chat | deepseek-reasoner | doubao | mimo |
|---------|--------|--------|--------|--------|
| asr_tolerance | 71% | 92% | 79% | 100% |
| boundary | 50% | 50% | 50% | 50% |
| chain_reasoning | 100% | 100% | 100% | 100% |
| clarify | 95% | 95% | 90% | 100% |
| compound | 92% | 96% | 92% | 96% |
| correct_turn | 100% | 100% | 100% | 100% |
| direct | 92% | 100% | 87% | 100% |
| implicit | 100% | 100% | 89% | 100% |
| rich_context | 60% | 80% | 73% | 80% |
| status_aware | 100% | 100% | 100% | 100% |
| temporal_reasoning | 80% | 80% | 80% | 80% |
| tool_selection | 100% | 100% | 100% | 100% |

#### 正向执行力发现

1. **多轮链路完整性比单步工具选择更重要**：4 模型在 `direct`、`compound`、`correct_turn`、`tool_selection` 上通过率均 ≥87%，说明"选对工具"已经接近 commodity。真正拉开差距的是多步链路场景：先查状态再决策（status_aware）、从长背景中定位目标再操作（rich_context）。
2. **20 工具环境的真实风险是相邻工具干扰**：最有代表性的失效不是模型卡死，而是走到了相邻工具上：把提醒当待办处理、把"打开应用"绕成 `find_program → bash`。
3. **主动检查行为与通过率正相关**：mimo（67% 先查、17% 验证）和 reasoner（72% 先查、13% 验证）通过率最高；doubao（28% 先查、0% 验证）在 rich_context 和 asr_tolerance 上明显更弱。
4. **boundary / temporal_reasoning 是共性瓶颈**：4 模型均为 50%/80%，指向 case 设计本身的边界条件难度，而非模型差异。
5. **rich_context 区分度最高**：deepseek-chat 60%、doubao 73%、reasoner/mimo 80%。长上下文中提取隐含时间线索的能力差异最明显。

### 维度二：异常鲁棒性

> 数据来源：`results/report_action_hallucination.md`（4 模型 × 2 温度 × 3 轮 = 24 runs）

#### 异常检测率对比

| 模型 | Temp | B (行为检测) | O (结果准确) | 稳定性 | 延迟 |
|------|------|-------------|-------------|--------|------|
| deepseek-chat | 0.1 | **97±6%** | 0±0% | **88%** | 20.1s |
| deepseek-chat | 0.7 | 92±7% | 4±7% | 62% | 17.4s |
| mimo-v2-pro | 0.1 | 54±7% | 17±14% | 25% | 28.5s |
| mimo-v2-pro | 0.7 | 62±0% | 12±12% | 38% | 27.1s |
| deepseek-reasoner | 0.1 | 46±7% | **38±0%** | 62% | 37.4s |
| deepseek-reasoner | 0.7 | 54±7% | 42±26% | 12% | 32.9s |
| doubao-seed-2-0-pro | 0.1 | 38±22% | 17±7% | 50% | 39.3s |
| doubao-seed-2-0-pro | 0.7 | 42±7% | 17±14% | 50% | 39.4s |

> B = 行为检测率（模型发现异常了吗），O = 结果准确率（模型告诉用户的信息对吗），稳定性 = case-level verdict 跨 3 轮一致比例。

#### 异常鲁棒性发现

1. **检测到异常 ≠ 能准确报告**：deepseek-chat 几乎总能发现异常（97%），但从未给出完全正确的结果信息（O=0%）。发现问题后开始编造细节，是"积极检测"后的系统性风险。
2. **稳定性差异比均值差异更有区分度**：deepseek-chat 在 t=0.1 下 88% 的 case 跨 3 轮 verdict 一致，是唯一"稳定检测器"。
3. **温度对检测能力影响有限**：4 模型的 B 均值变化幅度平均仅 7%。但温度对稳定性影响显著——reasoner 的 case-level 一致性从 62% 跌至 12%。
4. **reasoner 低检测率的根因是 max_turns 耗尽**：reasoner 倾向反复重试工具调用（create→list→create→list→...），6 轮全用于工具操作，没有留出回复窗口来告知用户异常。它实际"看到了"问题（如调用 `update_schedule` 修复 content 不一致），但选择了静默修复而非如实报告。详见[典型案例对照](results/hallucination/case_examples.md)。

### 两个维度的交叉发现

两个维度揭示了一个关键结论：**"做对"和"发现做错"是不同能力维度，且排名反转**。

| 模型 | 正向执行力排名 | 异常检测排名 |
|------|--------------|------------|
| mimo-v2-pro | **#1** (95%) | #3 (54%) |
| deepseek-reasoner | #2 (94%) | #4 (46%) |
| deepseek-chat | #3 (88%) | **#1** (97%) |
| doubao-seed-2-0-pro | #4 (88%) | #4 (38%) |

正向执行最强的 mimo 在异常检测中排第三；正向排第三的 chat 在异常检测中以 97% 大幅领先。这说明单维度评测无法给出完整画像——一个模型在"日常驾驶"中表现优秀，并不意味着它在"碰撞测试"中同样可靠。

详细报告：[results/report_action_hallucination.md](results/report_action_hallucination.md) | 典型案例对照：[case_examples.md](results/hallucination/case_examples.md)

---

## 文件说明

```
v2_tool_eval/
├── README.md              当前说明文档
├── run.py                 入口：一键多模型评测（并行 + 串行多轮）
├── run_hallucination.ps1  入口：幻觉鲁棒性多温度实验 runner
├── analyze.py             入口：结果分析（聚合 + Markdown/JSON/report）
├── schedule_cases.yaml    85 条案例定义，70 条进入自动化
├── results/
│   ├── {model}/                      正向执行：按模型分文件夹，每次运行一个 run_{ts}.jsonl
│   ├── hallucination/                异常鲁棒：独立子目录
│   │   ├── {model}/                  按模型分文件夹
│   │   │   └── t{temp}_{ts}.jsonl    温度 + 时间戳标识每次 run
│   │   ├── merged.jsonl              每个 (model, temp) 取最新一次
│   │   ├── case_examples.md          精选案例对照（reasoner vs chat）
│   │   └── conv_timeline.txt         完整对话时序转储
│   ├── report.md                     analyze.py 自动生成的主测试报告
│   └── report_action_hallucination.md  异常鲁棒性评测报告
└── eval/                  内部模块
    ├── agent_loop.py      多轮 tool-calling 执行循环（含 429/5xx 重试）
    ├── mock_tools.py      Fake backend + ToolDispatcher（正常工具）
    ├── flaky_tools.py     FlakyScheduler 故障注入工具（幻觉测试专用）
    ├── test_tool_calling.py  正向执行：确定性断言 + JSONL 归档
    ├── test_action_hallucination.py  异常鲁棒：故障注入 + 双维度评判
    └── verify.py          结果完整性检查
```

---

## 复现方式

```bash
cd v2_tool_eval
pip install -r ../requirements.txt
# 在 repo/.env 中配置 DEEPSEEK_API_KEY / MiMo_API_KEY / Doubao_API_KEY

# 一键跑全部 4 模型 × 3 轮（模型间并行，同模型多轮串行）
python run.py --runs 3

# 跑完后自动在 results/ 下生成 report.md
# 也可以单独生成报告
python analyze.py --latest 3 --report

# 只跑单个模型
python run.py --models deepseek-chat --runs 1
```

每次运行生成：`results/{model}/run_{YYYYMMDD_HHMMSS}.jsonl`

分析报告生成：`results/report.md`（含单次明细 + 多轮聚合均值±标准差）

### Action Hallucination 测试复现

```bash
cd v2_tool_eval

# 单次运行（默认 t=0.1）
TARGET_MODEL=deepseek-chat python eval/test_action_hallucination.py

# 指定温度
TEMPERATURE=0.7 TARGET_MODEL=deepseek-chat python eval/test_action_hallucination.py

# Windows PowerShell 单次
$env:TARGET_MODEL="deepseek-chat"; $env:TEMPERATURE="0.7"; python eval/test_action_hallucination.py

# 一键多温度多轮鲁棒性实验（4模型 × 2温度 × 3轮 = 24 runs，模型间并行）
.\run_hallucination.ps1

# 自定义参数
.\run_hallucination.ps1 -Temps 0.1 -Rounds 1
.\run_hallucination.ps1 -Models "deepseek-chat","mimo-v2-pro" -Temps 0.1,0.7 -Rounds 3
```

每次运行写入 `results/hallucination/{model}/t{temp}_{timestamp}.jsonl`，自动合并到 `results/hallucination/merged.jsonl`（每个 model×temp 组合取最新一次）。

评测报告：`results/report_action_hallucination.md`

---

## 局限性

1. 3 轮取均值足以观察行为模式，但尚不足以做严格统计显著性检验（需 30+ 轮）。
2. `complex` 和 `manual_test_prompts`（8 条）未并入自动化，说明 benchmark 偏向"可断言"而非"全覆盖"。
3. `boundary` 中 7 条 clarify/reject 型 case 跳过了自动化，边界条件的断言设计仍有张力。
4. Mock 环境中可以自由定义工具（如 `update_schedule`），但真实系统未必支持。这个 gap 在阶段 3 中被验证。

---

## 与其他阶段的关系

- [阶段 1](../v1_intent_eval/README.md)：验证评测器可信度 + 文本意图理解。
- **阶段 2（本文）**：受控环境下的规模化断言测试。
- [阶段 3](../v3_live_eval/nanobot/report_3model_comparison.md)：真实 Agent 部署验证，校验阶段 2 结论在真实系统上是否成立。
