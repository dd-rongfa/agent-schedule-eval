# 学习进展记录

> 记录整个项目中学到了什么、做了什么、暴露了什么问题
> 
> 核心目标：构建 AI 评测作品集，转型 AI 评测岗位

---

## 阶段一：DeepEval 框架学习（已完成 ✅）

### 掌握的技能
- DeepEval 四步范式：`GPTModel → GEval → LLMTestCase → assert_test`
- 通过 GPTModel 接入 OpenAI 兼容的第三方 API（DeepSeek）
- `.env` 加载 + `@lru_cache` 延迟初始化（避免 import 时报错）
- GEval 的 `evaluation_params`：INPUT, ACTUAL_OUTPUT, EXPECTED_OUTPUT, CONTEXT
- pytest parametrize 数据驱动测试
- 读懂 DeepEval 的失败报告（score, threshold, reason）

### 产出文件
| 文件 | 定位 |
|------|------|
| `test_agent_router_minimal.py` | 最小语法示例 |
| `test_agent_router.py` | 工程加固版 |
| `test_agent_router_project_style.py` | 多指标、tags、metadata |
| `demo_agent_router_failure.py` | 故意失败的学习样本 |

### 踩过的坑
- GEval 在 import 时就需要 API key → 用 `@lru_cache` 延迟创建解决
- `deepeval test run` 只收集 `test_` 开头的文件
- PowerShell 下 `-k` 过滤 unicode test ID 时匹配不到 → 用英文 keyword 代替

---

## 阶段二：Agent 定时任务评测项目设计（已完成 ✅）

### 做了什么
- 设计 8 类原始测试场景（schedule_cases.yaml）
- 搭建两层测试架构：Layer 1 GEval 意图判断 + Layer 2 JSON 结构化断言
- 首轮结果：17 tests, 15 passed, 2 failed

### 暴露的问题（后来认识到的）
- 测试用例是"随口想的"，没有理论框架支撑
- 没有系统性覆盖难度梯度

---

## 阶段三：理论升级 — Bloom × Agent 评测（已完成 ✅）

### 做了什么
- 学术调研：6 篇相关论文定位（TPS-Bench, Agent's First Day, SimuHome, COLING 2025 等）
- 发现差异化角度：Bloom × Agent 定时任务 = 未被探索的交叉领域
- 用 Bloom 六层重新组织 24 个测试用例
- 加入 JSONL 结果记录

### 调研结论
- "Agent 定时任务准确性评测" 是空白领域（现有 scheduling 指 workflow 排序）
- Bloom 被 COLING 2025 验证适用于 LLM 评测，但没人用于 Agent 工具使用场景

### 测试结果

```
L1 Remember    4/4  100%
L2 Understand  4/4  100%
L3 Apply       4/4  100%
L4 Analyze     3/4   75%
L5 Evaluate    4/5   80%
L6 Create      2/3   67%
Layer 2 JSON   3/3  100%
```

**符合 Bloom 核心预测：认知层级越高，通过率越低。**

### 失败案例分析
| Case | Bloom | Score | 失败原因 |
|------|-------|-------|---------|
| 多次推翻追踪 ("先设5分钟...取消...再设15分钟") | L4 | 0.3 | 多步状态追踪能力不足 |
| 紧急性判断 ("过一会儿提醒我关火") | L5 | 0.6 | 缺乏语用推理（不识别紧急性） |
| 条件分支计划 ("考试复习...工作日vs周末") | L6 | 0.6 | 幻觉（捏造时间参数） |

### 产出文件
| 文件 | 定位 |
|------|------|
| `RESEARCH.md` | 学术调研笔记（6 篇论文分析） |
| `schedule_cases_bloom.yaml` | Bloom 分层测试用例（24 automated + 4 manual） |
| `test_bloom_eval.py` | Bloom 评测代码（含 JSONL 记录） |
| `results.jsonl` | 完整测试记录 |

---

## 阶段四：认知盲点自省（已完成第一轮修正 ✅）

### 已识别的盲点

| # | 盲点 | 说明 | 严重程度 |
|---|------|------|---------|
| A | ~~测的是 Prompt 不是 Agent~~ | ✅ Phase 3 已用 function calling 补上 | ~~高~~ 已解决 |
| B | ~~从未验证裁判~~ | ✅ 15-case 人工标注 + κ/ρ 验证 | ~~高~~ 已解决 |
| C | ~~没有 baseline~~ | ✅ DeepSeek + MiMo 双模型对照 | ~~高~~ 已解决 |
| D | Bloom 应用偏松 | 更接近任务难度分级，非严格认知分类 | 低（已在 README 诚实说明） |
| E | 阈值拍脑袋 | 已有初步数据支撑，但还没做系统 threshold sweep | 低 |
| F | 对分数没有直觉 | 通过人工标注对照已有改善 | 低 |

### 认知增长记录
- 把"评测工具"当"黑箱真理" → 意识到"评测自己的评测"才是核心能力
- "会用工具" vs "有判断力" → 简历上要展示的是后者
- "更多 test case" vs "验证方法论" → 后者价值更高
- prompt 改动会连锁影响 actual_output、expected_summary、人工标注和 κ/ρ，评测体系必须整体校准
- κ 不是"模型水平"，而是"judge 与人工对 pass/fail 是否一致"

---

## 阶段五：Judge 校准完成（当前 ✅）

### 本轮完成内容
- 发现并修复 clarify / execute 的表达歧义
- 更新 system prompt，明确动作互斥和信息不足时优先 clarify
- 重跑 27 个测试 × 3 judge runs
- 同步更新 `human_annotations.yaml` 中的 `actual_output` 和 `expected_summary`
- 修正人工标注中的 pass/fail 不一致与旧标准残留问题

### 当前结果
1. `human_annotations.yaml` — 15 个 case 的人工标注
2. `judge_reliability.py` — 计算 κ 和 ρ 的脚本
3. judge 一致性：`κ=0.73`，`ρ=0.63`
4. 重测稳定性：3 次重复运行标准差处于可接受范围

### 下一步：Phase 2 — Baseline 对照 → 已完成，见下方

---

## 阶段六：多模型 Baseline 对照（已完成 ✅）

### 做了什么
- 接入 MiMo v2-pro API（小米 MiMo 系列）
- 重构 test_bloom_eval.py：TARGET_MODEL / TARGET_ENV_PREFIX 环境变量驱动模型切换
- 24 个 Bloom 用例跑两个模型，3 次 judge 重复
- 创建 baseline_compare.py 生成对比表 + 热力图

### 结果

| Bloom Level | DeepSeek | MiMo v2-pro |
|-------------|----------|-------------|
| L1 Remember | 25% | 25% |
| L2 Understand | 75% | 75% |
| L3 Apply | 100% | 75% |
| L4 Analyze | 75% | 0% |
| L5 Evaluate | 60% | 80% |
| L6 Create | 67% | 33% |
| **Overall** | **67%** | **50%** |

### 关键发现
- MiMo 在 L4 Analyze（复合指令拆解）完全崩溃，但 L5 Evaluate 反超
- 模型弱点是认知维度特异性的，不是整体性的

### 产出文件
| 文件 | 定位 |
|------|------|
| `results_mimo_v2_pro.jsonl` | MiMo Phase 2 结果 |
| `baseline_compare.py` | 对比表 + 热力图生成 |
| `bloom_heatmap.png` | Bloom × Model 热力图 |

---

## 阶段七：Function Calling 评测（已完成 ✅）

### 做了什么
- 创建 test_tool_calling.py：用 OpenAI tools API 让模型真正发起 tool_calls
- FakeScheduler 拦截调用，做确定性断言（无 Judge 参与）
- L1-L4 共 16 个有明确 expected_action 的用例
- DeepSeek 和 MiMo 各跑一轮

### 结果

| 评测方式 | DeepSeek | MiMo v2-pro |
|---------|----------|-------------|
| Phase 2 — 说意图 | 67% | 50% |
| Phase 3 — 真调用 | **19%** | **25%** |

### 关键发现（本项目最重要的结论）
**"说到做不到"**：两个模型在 Phase 2 中都能正确描述意图，但 Phase 3 给了真实工具后通过率断崖下降。失败模式高度一致——**有工具可用时反而过度追问**。纯文本意图评测会严重高估模型的实际执行能力。

### 产出文件
| 文件 | 定位 |
|------|------|
| `test_tool_calling.py` | Phase 3 评测代码 |
| `results_tool_calling.jsonl` | DeepSeek Phase 3 结果 |
| `results_tool_calling_mimo.jsonl` | MiMo Phase 3 结果 |

---

## 阶段八：整理输出（已完成 ✅）

### 做了什么
- 重写 README.md：动机→方法→结果→局限，面试官 5 分钟可读完
- 更新 ROADMAP.md：所有 Phase 标记完成，验收清单全部打钩
- 更新 PROGRESS.md：技能清单更新，新增阶段六~八
- 更新 CONCEPTS.md：已掌握标注

---

## 阶段九：Skill Loading 评测（已完成 ✅）

### 做了什么
- 提出研究问题：向 Agent 注入 Skill 文档（SOP）是否真正有效？效果边界在哪？
- 创建 `skills/` 目录，写了 3 个 skill 文件（schedule / email / note）
- 创建 `test_skill_loading.py`：4 组对照实验，复用 L1-L4 共 16 个 tool_call 断言用例
- 跑完第一轮（DeepSeek，2026-04-07）

### 第一轮结果

| 组 | 描述 | 通过率 |
|---|---|---|
| A — 无 Skill | 基线 | 12.5% (2/16) |
| B — 正确 Skill | schedule_skill.md | 25% (4/16) |
| C — 错误 Skill | email_skill.md | 12.5% (2/16) |
| D — 3 Skill | schedule+email+note | 25% (4/16) |

### 关键发现
1. 正确 skill 有效，但提升有限（+12.5%），且集中在 L3
2. 错误 skill 不产生干扰（模型能识别并忽略）
3. 多 skill 加载不稀释效果（D = B）
4. L4 全组全灭 → skill 帮不了隐式多步推理

### 已识别的问题
- 当前 skill 是"API 文档 + 路由规则"，本质上是轻量文档，不是真正 SOP
- 真正的 SOP 应包含：few-shot 示例、边界处理、错误恢复、跨 skill 依赖
- 定时任务是低复杂度域，不足以充分展示 skill 机制价值

### 静态冲突检测工具（2026-04-08）

创建了 `skill_conflict_checker.py`：读取任意数量 skill 文件，两两调用 LLM 分析冲突，输出结构化报告（类型/严重程度/触发场景/影响/建议）。

对 4 个 skill 的 6 对组合跑了一遍：

| 组合 | 冲突数 | 冲突类型 |
|---|---|---|
| schedule × conflict | 4处 | HIGH×3, MEDIUM×1 |
| note × schedule | 1处 | HIGH（content 默认值策略矛盾）|
| 其余 4 对 | 0 | ✅ 安全 |

**意外发现**：note_skill × schedule_skill 也有冲突——note 要求信息不足时追问，schedule v3 用默认值直接调用。这是两个正常 skill 之间的跨域策略冲突，不是故意设计的，更接近真实部署场景。

### 跨模型对比（2026-04-08）

在 A/B/E 三组上跑了 MiMo，与 DeepSeek 对比：

| 组 | DeepSeek | MiMo |
|---|---|---|
| A — 无 Skill | 12.5% | 31% |
| B — 正确 Skill v3 | 75% | 75% |
| E — 矛盾 Skill | **6%** | **88%** |

E 组是今天最重要的发现：同一对矛盾 skill，DeepSeek 崩溃，MiMo 不受影响。**模型的冲突决策策略是模型特异性的**，不能假设"有冲突 = 性能下降"。

### 下一步（已记录在 ROADMAP.md Phase 5）
- [x] 给 schedule_skill 加 few-shot 示例（v2）
- [x] 加时间默认值映射（v3）
- [x] 设计 skill conflict 动态测试（E 组，75% → 6%）
- [x] 静态冲突检测工具（`skill_conflict_checker.py`）
- [ ] 长期：换高复杂度域，构建 Skill Quality Benchmark

### 新掌握的概念
- Skill-as-SOP：skill 的写作质量是独立的评测维度，不只是"有没有"
- Few-shot in skill：给模型「模式」比给模型「规则清单」更有效
- 时间默认值 = User Profile 的简化版：把领域常识写进 skill 比追问更实用
- **Skill 冲突比 skill 缺失更危险**：错误 skill 无害，矛盾 skill 主动破坏性能（75% → 6%）
- **模型冲突决策策略：保守优先**——矛盾时倾向于"先追问"而非"先执行"
- **跨域 skill 也会冲突**：不同领域的 skill 在"通用策略"（如默认值处理）上可能隐性矛盾
- **静态检测 vs 动态测试互补**：静态检测快、便宜，可在部署前发现；动态测试能定量测冲突的实际危害

---

## 技能清单：已掌握 vs 待学

### ✅ 已掌握
- DeepEval GEval 配置和使用
- pytest parametrize 数据驱动测试
- YAML 数据文件设计
- JSONL 结构化记录
- 基本的 prompt engineering（system prompt 设计）
- 学术论文检索和定位
- Cohen's Kappa 计算和解读（κ=0.73）
- Spearman 相关系数（ρ=0.63）
- 人工标注 → Judge 校准的完整流程
- 多模型 Baseline 对照实验设计
- OpenAI Function Calling API（tools 参数 + tool_calls 解析）
- FakeScheduler 拦截模式（确定性断言 vs LLM Judge）
- matplotlib/seaborn 热力图可视化
- 环境变量驱动的多模型切换架构

### 📚 待学（按优先级）
- LLM-as-a-Judge 的已知偏差（positional bias, verbosity bias）🟡
- 多轮对话状态管理测试 🟡
- ROC/AUC 🟢
- 阈值 threshold sweep（F1 最优 cutoff）🟢

---

## 阶段十：项目发布与文档完善（已完成 ✅）

### 做了什么（2026-04-08）
- GitHub 仓库创建并推送（agent-schedule-eval），完成 About 描述和 Topics 标签
- 起源故事多轮迭代：最终定为 nanobot 失效发现 → learn-claude-code 学原理 → 系统化评测
- ROADMAP 验收清单全部勾选（真实性层/表达层/自我质疑层）
- 3 份英文文档翻译为中文（starter_judge + promptfoo README/WALKTHROUGH）
- promptfoo 定时任务 demo 补充（schedule-eval.yaml + schedule_provider.py）
- Phase 6 端到端规划写入 ROADMAP（OpenClaw 生态）
- 框架选型说明补充（为什么 pytest 而非 promptfoo 做主评测）
- jd0407 简历第2条更新：加入 Skill Loading + conflict checker 数据
- GitHub 仓库清理建议（fork 管理、About 配置）
- 本地全量验证通过：123 tests collected、6 JSONL 文件可读、3 promptfoo 配置有效

### 产出文件
| 文件 | 定位 |
|------|------|
| `examples/promptfoo/schedule-eval.yaml` | promptfoo 定时任务 demo（8 个 L1-L3 case）|
| `examples/promptfoo/schedule_provider.py` | promptfoo provider |
| 3 份翻译文档 | 中文化 |

### 项目状态
- GitHub: https://github.com/dd-rongfa/agent-schedule-eval （10 commits on main）
- 置顶显示，About/Topics 已配置
- 所有 Phase 1-5 完成，Phase 6 为未来规划
