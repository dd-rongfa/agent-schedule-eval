# 项目演进路线图

> 核心目标：构建 AI 评测领域的个人作品集项目，展示"能设计评测方案 + 能验证评测方法可信度"的能力
> 
> 背景：物理/师范/教育心理学 + 编程 + AI 使用经验 → 转型 AI 评测岗位

---

## 当前状态（2026-04-08 全部完成 ✅）

- ✅ DeepEval 框架掌握（4 个渐进式 example）
- ✅ Bloom × Agent 定时任务评测框架成型（24 个分层 case + JSONL 记录）
- ✅ 学术调研完成（RESEARCH.md，6 篇相关论文定位）
- ✅ LLM judge 可信度已验证（15 个人工标注样本，κ=0.73，ρ=0.63）
- ✅ 提示词和标注标准完成一轮校准（修复 clarify / execute 歧义）
- ✅ 多模型 Baseline 对照完成（DeepSeek 67% vs MiMo 50%）
- ✅ 热力图和对比表生成（bloom_heatmap.png）
- ✅ Function Calling 评测完成（DeepSeek 19% vs MiMo 25%）
- ✅ Skill Loading 5 组对照 + 跨模型冲突实验完成
- ✅ README 输出完成 + GitHub 推送（agent-schedule-eval）
- ✅ promptfoo 定时任务 demo 补充（两套框架选型说明）

---

## Phase 1：验证裁判（已完成 ✅）

**目标：** 让 GEval 的分数"有据可查"，而不是"黑箱输出"

**为什么最重要：** 做评测的人，第一件事应该是验证自己的评测工具。一个有裁判验证的 15-case 项目 > 没验证的 100-case 项目。

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 1.1 | 从 results.jsonl 里选 15 个 case（每个 Bloom 层级 2-3 个，覆盖 pass 和 fail） | `human_annotations.yaml` |
| 1.2 | 自己给每个 case 打分（0/0.2/0.4/0.6/0.8/1.0 六档），写一句话理由 | 同上 |
| 1.3 | 写 `judge_reliability.py`：读 results.jsonl + human_annotations.yaml，算 Spearman ρ 和 Cohen's κ | 一张对比表 + 两个统计量 |
| 1.4 | 同一 case 让 GEval 跑 3 次看分数标准差（重测信度） | 标准差数据 |
| 1.5 | 基于人工标注，用数据确定最佳阈值 | 有数据支撑的 threshold |

**实际结果：**

- 已完成 15 个样本的人类标注
- 已完成 `judge_reliability.py`
- 已完成 3 次重复运行检查 judge 稳定性
- 已完成 prompt / expected_summary / human annotation 的一次完整校准
- 当前结果：`κ=0.73`，`ρ=0.63`

**结论：** 当前 judge 已达到可接受的一致性水平，可作为后续 baseline 对照和真实 Agent 测试的评测器使用。

---

## Phase 2：多模型 Baseline（已完成 ✅）

**目标：** "Bloom 层级越高通过率越低" 要有比较才有意义

**为什么现在做：**

- judge 可信度已经验证完成
- 现阶段最缺的是"对照组"
- 有 baseline 后，项目才能回答"这个现象是模型共性，还是 DeepSeek 特性？"

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 2.1 | 固定同一套 case、同一 judge、同一 threshold，跑第二个模型（优先 GPT-4o-mini；备选 Qwen） | 第二份 results JSONL |
| 2.2 | 统一汇总为 model-level 结果表（每层通过率、平均分、失败 case） | `baseline_compare.py` 或聚合脚本 |
| 2.3 | 做 Bloom Level × Model 通过率热力图 | matplotlib/seaborn 图 |
| 2.4 | 分析差异拐点：哪个 Bloom 层级开始拉开差距 | 分析段落 |
| 2.5 | 标记典型分歧 case：一个模型过、另一个不过 | 2-4 个案例分析 |

**完成标准：** 一张热力图 + 一句核心 finding + 至少 2 个模型的并排结果

**实际结果：**
- DeepSeek 67% (16/24) vs MiMo 50% (12/24)
- MiMo 在 L4 Analyze 完全崩溃（0%），但 L5 Evaluate 反超（80% vs 60%）
- 热力图已生成：bloom_heatmap.png

---

## Phase 3：真 Agent 评测（已完成 ✅）

**目标：** 从"测 Prompt 理解力"升级到"测 Agent 执行力"

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 3.1 | ✅ 用 mock_tools.py + OpenAI tools API 搭建 function calling 流程 | `test_tool_calling.py` |
| 3.2 | ✅ 复用 L1-L4 共 16 个有明确 expected_action 的用例 | 同上 |
| 3.3 | ✅ 断言 tool_call 参数（action + delay_minutes + time + days） | 确定性断言 |
| 3.4 | ⬜ 多轮交互测试（未做，标记为局限性） | — |

**完成标准：** 能对比"Prompt level 通过但 tool call level 失败"的案例

**实际结果：**
- DeepSeek: Phase 2 67% → Phase 3 **19%**（断崖下降）
- MiMo: Phase 2 50% → Phase 3 **25%**
- 核心发现：模型在有工具可用时反而过度追问——说到做不到

---

## Phase 4：整理输出（已完成 ✅）

**目标：** 面试官 5 分钟看懂你做了什么

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 4.1 | ✅ README 重写：动机→方法→结果→局限 | README.md |
| 4.2 | ✅ 方法论说明集成到 README + CONCEPTS.md | — |
| 4.3 | ✅ 热力图嵌入 README | bloom_heatmap.png |

---

## 验收清单

### 可信度层（必须有 ✅）
- [x] 有人工标注数据（≥15 个 case，含分数和理由）
- [x] 能报告 LLM judge 与人工标注的一致性数字（κ 或 ρ）
- [x] 阈值已有初步数据支撑，不再完全拍脑袋
- [x] 同一 case 重跑 3 次，分数标准差 < 0.15

### 结论层（应该有 📊）
- [x] 至少 2 个模型的对比数据（DeepSeek + MiMo）
- [x] 一张 Bloom × Model 可视化图（bloom_heatmap.png）
- [x] 能一句话说清核心发现（Phase 2 vs Phase 3 的"说到做不到"鸿沟）

### 真实性层（加分项 🎯）
- [ ] 至少 5 个 case 来自真实 Agent 测试中发现的 bug
- [x] 有 function calling 级别的断言
- [ ] 有至少 1 个多轮交互测试

### 表达层（必须有 📝）
- [x] README 里有"动机→方法→结果→局限"
- [x] 面试官不看代码只看 README 就能理解
- [x] 能回答"为什么 LLM judge 可信"（用数据）

### 自我质疑层（面试防御 🛡️）
- [x] 能说出 3 个局限
- [x] 能解释 Bloom 在这里是"借用"而非严格 apply
- [x] 能解释"用 AI 辅助做 AI evaluation"为什么不是循环论证（因为有人工标注锚定）

---

## Phase 5：Skill Loading 评测（已完成 ✅）

**目标：** 评测"向 Agent 注入 Skill 文档"这一机制是否真正有效，以及有效性的边界

**背景：**
- Skill = 按需注入 system prompt 的结构化 SOP，是 Agent 系统中常见的上下文工程手段
- 研究问题：正确 skill / 错误 skill / 多 skill 注入，对模型行为各有什么影响？

### 实验设计（5 组对照）

| 组 | 描述 | System Prompt |
|---|---|---|
| A | 无 Skill（基线） | 仅工具定义 |
| B | 正确 Skill | + schedule_skill.md |
| C | 错误 Skill | + email_skill.md（与任务无关）|
| D | 3 Skill（含1正确） | + schedule + email + note |
| E | 矛盾 Skill | + schedule_skill.md + conflict_skill.md |

用例：复用 L1-L4 共 16 个有工具调用断言的 case（test_tool_calling.py 的用例集）

### 实验结果：skill 迭代演化数据（DeepSeek，B 组）

**4 组基线对照（2026-04-07，skill v1 — API 文档型）**

| 组 | 通过数 | 通过率 | vs 基线 |
|---|---|---|---|
| A — 无 Skill | 2/16 | 12.5% | — |
| B — 正确 Skill v1 | 4/16 | 25% | ↑ +12.5% |
| C — 错误 Skill | 2/16 | 12.5% | 持平 |
| D — 3 Skill | 4/16 | 25% | ↑ +12.5% |

**skill 质量迭代对比（仅 B 组，2026-04-08）**

| skill 版本 | 新增内容 | B 组通过率 | 变化 |
|---|---|---|---|
| v1 — API 文档 | 工具参数说明 + 5条路由规则 | 25% (4/16) | 基线 |
| v2 — + few-shot | 5 个完整 Input→ToolCall 示例 | 56% (9/16) | ↑ +31% |
| v3 — + 时间默认值 | 模糊时段映射表（明早=08:00 等） | **75% (12/16)** | ↑ +50% |

**skill 冲突实验结果（2026-04-08，E 组 = schedule_skill v3 + conflict_skill）**

| 组 | 说明 | 通过率 |
|---|---|---|
| B — 正确 Skill v3 | schedule_skill 单独注入 | **75% (12/16)** |
| E — 冲突 Skill | schedule_skill + conflict_skill 同时注入 | **6% (1/16)** |

冲突的具体矛盾点（conflict_skill 的指令）：
- 「模糊时段必须追问，不得使用默认值」← 直接推翻 schedule_skill 的时间默认值映射
- 「用户改口时停止操作，等待确认」← 直接推翻 schedule_skill 的「取最后一次为准」规则
- 「多步操作分两次交互」← 直接推翻 schedule_skill 的「连续双 tool call」示例

**关键发现（已验证）**
- **冲突 skill 造成灾难性退化**：E 组从 75% 跌至 6%，等同于比无 skill 的 A 组（12.5%）还差
- **冲突方向可预测**：conflict_skill 的每条矛盾规则都指向"先追问用户"，模型在矛盾时倾向于保守策略（追问），而非执行策略
- **冲突的威胁比缺失更严重**：错误 skill（C 组，12.5%）不影响结果，但冲突 skill（E 组）主动拉低性能

### 跨模型对比（2026-04-08，DeepSeek vs MiMo v2-pro）

| 组 | 条件 | DeepSeek | MiMo |
|---|---|---|---|
| A | 无 Skill（基线） | 12.5% (2/16) | 31% (5/16) |
| B | 正确 Skill v3 | **75% (12/16)** | **75% (12/16)** |
| E | 矛盾 Skill | **6% (1/16)** | **88% (14/16)** |

跨模型关键发现：
- **A 组**：MiMo 裸跑能力更强（31% vs 12.5%），与 Phase 3 趋势一致
- **B 组**：两模型收敛到同一水平（均 75%）——skill 补的是短板，弱模型收益更大（+62.5% vs +44%）
- **E 组（最关键）**：DeepSeek 被冲突 skill 摧毁（75%→6%），MiMo 不受影响反而提升（31%→88%）——**冲突决策策略是模型特异性的，DeepSeek 面对矛盾选择保守追问，MiMo 倾向于执行最大胆的规则**

### 核心发现（已验证）
1. **skill 写法质量 >> skill 是否存在**：v1→v3 提升 50%，而有/无 skill 的差异仅 12.5%
2. **few-shot 示例是最有效的单项改进**：解决了「改口取最终值」和 L3 复杂参数两类问题
3. **时间默认值映射直接解锁 L2**：「明早」「后天中午」等模糊时段，默认值比追问更实用
4. **错误 skill 不产生干扰**：C 与 A 持平，模型能识别并忽略不相关内容
5. **多 skill 注入不稀释效果**：D 与 B 持平
6. **冲突 skill 的影响是模型特异性的**：对 DeepSeek 灾难性（-69%），对 MiMo 无害甚至有益（+57%）
7. **L4 双 tool call 是共同边界**：两模型均无法完成串行两次工具调用

### 仍未解决的失败模式
- L1 欠规格：「设个闹钟」无时间、「取消那个提醒」无对象 → 追问是合理行为
- L4 串行双调用：模型只发第一个 tool call，连续规划超出当前模型能力

### 下一步计划

**近期：**
- [x] 设计 skill conflict 测试：造一个与 schedule_skill 矛盾的 conflict_skill.md，观察模型行为
- [x] 静态冲突检测：用 LLM 读两个 skill 文件，输出冲突报告（`skill_conflict_checker.py`）

**中期：**
- [ ] skill 长度 vs passrate 曲线：找 token 效率帕累托最优点
- [ ] User Profile Skill：把用户习惯（「明早」「下班后」）写进独立 skill，测试注入效果

**长期（换域）：**
- [ ] 换到高复杂度域（客服退款 SOP、代码 review 流程），做 skill writing style 比较

---

## Phase 6：端到端实测（计划中 📋）

**目标：** 从 API 级 benchmark 延伸到真实 Agent 产品验证，形成闭环

**背景：**
- 本项目的起点就是部署 [nanobot](https://github.com/HKUDS/nanobot)（OpenClaw 简化版）后发现定时任务几乎全部提前触发
- Phase 1-5 在 API 级别量化了问题，Phase 6 回到真实产品做端到端验证
- OpenClaw 生态相关项目：
  - [OpenClaw](https://github.com/openclaw/openclaw)（351k stars）— 完整版，TypeScript，有 cron 模块
  - [nanobot](https://github.com/HKUDS/nanobot)（38.4k stars）— Python 轻量版，适合快速部署和测试

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 6.1 | 部署 nanobot，用本框架的 L1-L4 case 手动测试实际调度准确率 | 真实 Agent 通过率数据 |
| 6.2 | 对比 API 评测结果与端到端实测结果——偏差有多大？ | 偏差分析报告 |
| 6.3 | 向 nanobot 注入本项目的 schedule_skill.md，验证 Skill 在真实环境中的收益 | Skill 实测效果 |
| 6.4 | 对比 OpenClaw 主项目的 cron 模块表现（如条件允许） | 跨产品对照 |

**完成标准：** API 评测预测 vs 真实 Agent 表现的一致性分析，至少覆盖 1 个 OpenClaw 生态 Agent

---

## 框架选型说明

本项目同时使用了两套评测框架，各有分工：

| 框架 | 用途 | 优势场景 |
|------|------|---------|
| **pytest**（主力） | agent_schedule_eval/ 全部 Phase | Function Calling 断言、mock 工具、Bloom 分层聚合、JSONL 结果记录 |
| **promptfoo**（辅助） | examples/ 中的快速验证 | 改 prompt 后一行命令看效果、零代码 assert、结果可视化（promptfoo view） |

选择 pytest 作为主力的原因：
1. Phase 3/5 需要解析 `tool_calls` 结构体，promptfoo 的内置 assert（contains / is-json）不够灵活
2. 需要 `conftest.py` + `mock_tools.py` 的 fixture 支持多轮对话和工具注入
3. 结果需要按 Bloom 层级聚合分析，pytest 的参数化 + JSONL 更方便

promptfoo 保留在 examples/ 中的原因：
1. 展示对行业标准评测框架的掌握
2. 做 prompt 快速 A/B 测试时比 pytest 效率更高
3. `examples/promptfoo/schedule-eval.yaml` 用同一场景演示了两套框架的差异
- [ ] 构建 "Skill Quality Benchmark" 框架：给定标准任务集，量化不同 skill 写法的效果差异

### 产出文件
| 文件 | 定位 |
|------|------|
| `test_skill_loading.py` | Phase 5 评测代码，5 组对照设计 |
| `results_skill_loading.jsonl` | 结果记录（DeepSeek，滚动追加） |
| `skills/schedule_skill.md` | 正确 skill（当前：v3，含 few-shot + 时间默认值） |
| `skill_conflict_checker.py` | 静态冲突检测工具，LLM 分析 skill 文件对，输出结构化冲突报告 |
| `skills/conflict_skill.md` | 专门设计的矛盾 skill（E 组用） |
