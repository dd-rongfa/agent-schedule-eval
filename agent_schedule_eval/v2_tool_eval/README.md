# v2 — 多工具多轮 Agent Tool-Calling 评测

> v1 测的是"模型会不会描述意图"，v2 测的是"模型在 20 个工具面前能不能完成查询→执行→验证的多轮链路"。
> 当前版本覆盖日程、待办、媒体、应用和系统操作五大类工具，70 个确定性断言 case × 4 模型 × 3 轮。

---

## 这版 v2 在解决什么问题

v1 验证了评测框架（Judge 可信度 + Bloom 分层），但它测的是"模型能不能用自然语言描述正确意图"。这和真实工具执行能力是**不同维度**——v1 最强的 deepseek-chat（78%）在 v2 排名第三（89%），v1 最弱的 mimo（59%）反而在 v2 排名第一（95%）。**语言描述能力无法预测工具执行能力，排名都反了。**

真实的工具调用几乎不是一次请求就完成的。用户说"帮我设个明天的提醒"，正确行为是：先 `get_current_time` 确认今天日期 → 再 `create_schedule` 设提醒 → 可选 `list_schedules` 验证是否创建成功。这条**查询→执行→验证**的多轮链路，加上 tool schema 的结构化约束，是 v1 的单轮文本评测覆盖不到的。

v2 做了三件关键的事：

1. **多轮 tool-calling 框架**：`agent_loop.py` 实现多轮循环（最多 10 轮），模型可以持续发起 tool_calls 直到给出最终回复，支持查询→执行→验证的完整链路。
2. **20 工具的干扰环境**：从 3 个日程工具扩展到 5 大类 20 工具，主动制造相邻工具干扰，逼模型暴露真实路由策略。
3. **确定性断言替代 LLM Judge**：不再依赖打分器，而是直接断言：调没调工具、调了哪个、参数对不对、顺序对不对。

---

## 评测设计

### 1. 三轴分类体系

旧版 Bloom 分层在 Agent 场景里有一个结构性问题：它把"认知层级"和"信息完整度"混在了一起。比如"设个闹钟八点"不一定比"取消明天下午三点的提醒"简单，因为前者信息不完整，合理行为应该是追问。

所以当前 v2 改为三轴分类：

- `operation`：direct / clarify / compound / implicit
- `context`：empty / simple / rich
- `turns`：single / clarify_turn / correct_turn

这套分类更贴近真实 Agent 失效模式：到底是任务类型难，还是背景干扰多，还是多轮状态容易丢。

### 2. 工具空间

当前一共 20 个工具，分成 6 组：

- 日程提醒（6）：`create_schedule`、`cancel_schedule`、`create_recurring`、`list_schedules`、`update_schedule`、`get_current_time`
- 待办事项（4）：`create_todo`、`complete_todo`、`list_todos`、`delete_todo`
- 媒体播放（4）：`play_media`、`pause_media`、`get_play_history`、`list_media_library`
- 应用操作（2）：`open_app`、`list_apps`
- 系统操作（3）：`bash`、`find_program`、`control_window`
- 后台任务（1）：`check_task_status`

这些工具由 [mock_tools.py](./mock_tools.py) 里的 Fake backend 汇总到 `ToolDispatcher`，记录调用轨迹而不产生真实副作用。

### 3. Case 收敛原则

自动化 case 的设计原则只有一句话：**把路堵死，只保留一条可接受答案路径。**

这意味着：

- 能明确断言的 case 才进入回归集。
- 没有唯一正确路径的 case 不硬塞进自动化。
- "建议型""开放型""系统级编排型"场景保留为人工探索，不污染主 benchmark。

因此当前 [schedule_cases.yaml](./schedule_cases.yaml) 一共 85 条样例，其中 70 条进入自动化回归（跳过 complex / manual_test_prompts，以及 boundary 中的 clarify/reject 类型）。

### 4. 当前自动化覆盖

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

## 当前结果

> 数据来源：`results/report.md`（由 `analyze_behavior.py --latest 3 --report` 自动生成）

### 模型通过率对比（3 轮均值）

| 模型 | 通过率 | case 数 | 平均延迟 | 创建前先查 | 创建后验证 |
|------|--------|---------|----------|-----------|-----------|
| mimo-v2-pro | 95.2% ± 1.6% | 70 | 18.2s | 67% | 17% |
| deepseek-reasoner | 93.8% ± 2.2% | 70 | 20.7s | 72% | 13% |
| deepseek-chat | 88.1% ± 2.2% | 70 | 11.4s | 49% | 4% |
| doubao-seed-2-0-pro-260215 | 88.1% ± 2.2% | 70 | 22.3s | 28% | 0% |

### 按 Section 拆分通过率

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

### 怎么读这张表

overall 分数能排出强弱，但 v2 真正有价值的地方在于 section 级别的诊断：

- **boundary / temporal_reasoning 是共性瓶颈**：4 模型均为 50%/80%，指向 case 设计本身的边界条件难度，而非模型差异。
- **rich_context 区分度最高**：deepseek-chat 60%、doubao 73%、reasoner/mimo 80%。长上下文中提取隐含时间线索的能力差异最明显。
- **asr_tolerance 暴露工具路由能力**：不是"能不能容错听错字"，而是"听错之后还能不能选对工具"。"地盘/地图""抖影/抖音"的失败本质是工具路由问题。
- **创建前先查 / 创建后验证**反映模型的谨慎程度：reasoner 和 mimo 在创建提醒前主动调 `get_current_time` / `list_schedules` 的比例远高于其他模型。

---

## 主要发现

### 1. 多轮链路完整性比单步工具选择更重要

4 模型在 `direct`、`compound`、`correct_turn`、`tool_selection` 上通过率均 ≥87%，说明"选对工具"已经接近 commodity。真正拉开差距的是需要多步链路的场景：先查状态再决策（status_aware）、先查时间再推理再设提醒（chain_reasoning）、从长背景中定位目标再操作（rich_context）。

### 2. 20 工具环境的真实风险是相邻工具干扰

最有代表性的失效不是模型卡死，而是走到了相邻工具上：把提醒当待办处理、把"打开应用"绕成 `find_program → bash`、在多个候选项时要求多余澄清或选错对象。

### 3. 主动检查行为与通过率正相关

mimo（67% 先查、17% 验证）和 reasoner（72% 先查、13% 验证）通过率最高；doubao（28% 先查、0% 验证）在 rich_context 和 asr_tolerance 上明显更弱。这提示：模型是否会在执行前后主动查询上下文，是一个有区分度的行为指标。

---

## 文件说明

```
v2_tool_eval/
├── README.md              当前说明文档
├── run.py                 入口：一键多模型评测（并行 + 串行多轮）
├── analyze.py             入口：结果分析（聚合 + Markdown/JSON/report）
├── schedule_cases.yaml    85 条案例定义，70 条进入自动化
├── results/
│   ├── {model}/           按模型分文件夹，每次运行一个 run_{ts}.jsonl
│   └── report.md          analyze.py 自动生成的结论性报告
└── eval/                  内部模块
    ├── agent_loop.py      多轮 tool-calling 执行循环（含 429/5xx 重试）
    ├── mock_tools.py      Fake backend + ToolDispatcher
    ├── test_tool_calling.py  pytest 核心：确定性断言 + JSONL 归档
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
