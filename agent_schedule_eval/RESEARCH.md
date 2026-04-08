# Agent 定时任务评测 — 调研笔记

> 时间：2026-07  
> 目的：定位本项目在学术和工业界中的位置，找到差异化角度

---

## 1. 现有 Agent 评测中与"调度/定时"相关的工作

### 1.1 TPS-Bench（arXiv:2511.01527, 2025-11）
- **标题:** Evaluating AI Agents' Tool Planning & Scheduling Abilities in Compounding Tasks
- **做了什么:** 200 个复合任务，测试 Agent 从 MCP 工具库中选工具 + 决定执行顺序
- **"Scheduling" 指的是:** 工具的执行顺序调度（并行 vs 串行），不是日历/定时
- **与我们的区别:** 他们测的是 "先搜索再发邮件" 这种 **workflow 顺序规划**，我们测的是 **自然语言→时间参数→定时动作** 的解析准确性

### 1.2 The Agent's First Day（arXiv:2601.08173, 2026-01）
- **标题:** Benchmarking Learning, Exploration, and Scheduling in the Workplace Scenarios
- **做了什么:** 模拟新员工在动态工作环境中处理流式任务
- **三个评测维度:** 上下文感知调度 / 主动探索 / 持续学习
- **与我们的区别:** 他们的 "scheduling" 是宏观层面的任务优先级排序，不涉及具体时间解析（"5分钟后提醒我"这种）

### 1.3 SimuHome（arXiv:2509.24282, ICLR 2026 Oral）
- **标题:** Temporal- and Environment-Aware Benchmark for Smart Home LLM Agents
- **做了什么:** 600 个智能家居场景，有时间相关的设备控制
- **与我们的区别:** 关注设备控制（开灯/关空调），不是纯粹的 "定时提醒" 场景

### 1.4 其他 Agent 评测框架
| 项目 | 关注点 | 与我们的关系 |
|------|--------|-------------|
| AgentBench | 代码/网页/游戏/数据库 | 无定时场景 |
| ToolBench | 大规模 API 调用 | 无时间解析 |
| ReliabilityBench | Agent 在压力下的可靠性 | 方法论有参考价值 |
| ToolMisuseBench | 工具误用检测与恢复 | 错误处理思路可参考 |

### 1.5 结论
**"Agent 定时任务准确性评测" 是一个空白领域。** 现有工作中 "scheduling" 都指 workflow 顺序或任务优先级，没有针对 NL→时间参数→定时动作 这个垂直能力的系统性评测。

---

## 2. Bloom's Taxonomy × LLM/Agent 评测

### 2.1 核心论文：LLMs meet Bloom's Taxonomy（COLING 2025，被引 28 次）
- **作者:** Huber & Niklaus
- **核心发现:** LLM 在 Bloom 低层级（Remember/Understand）表现好，高层级（Evaluate/Create）有显著差距
- **做法:** 把现有 benchmark 按 Bloom 分层归类，发现覆盖不均匀
- **启示:** 我们可以用同样的方法论，但聚焦在 Agent 定时任务这个垂直场景

### 2.2 其他 Bloom + LLM 论文
| 论文 | 做了什么 | 与我们的关系 |
|------|---------|-------------|
| BloomAPR (arXiv:2509.25465) | 用 Bloom 评估 LLM 自动程序修复能力 | 方法论可参考（分层评测框架） |
| EduEval (arXiv:2512.00290) | 中文教育场景下的认知层次评测 | 中文场景 + Bloom，最接近我们的定位 |
| SpeechIQ (arXiv:2507.19361, ACL 2025) | 用 Bloom 评估语音理解能力 | 理解类任务的分层思路 |
| BloomWise | 用 Bloom 分层 prompt 提升推理 | 逆向思路（我们是评测，他们是提升） |

### 2.3 结论
**Bloom × Agent 工具使用评测 = 未被探索的交叉领域。** 现有工作要么是 Bloom × 通用 LLM benchmark，要么是 Bloom × 教育/编程。没有人将 Bloom 应用于 Agent 定时任务这种具体的工具使用能力评测。

---

## 3. 我们的差异化角度

```
独特定位 = Bloom's Taxonomy × Agent 定时任务能力
                ↑                    ↑
           教育心理学理论         未被覆盖的垂直场景
```

### 3.1 Bloom 六层 → Agent 定时任务能力映射

| Bloom 层级 | 认知动词 | Agent 能力 | 典型测试用例 |
|-----------|---------|-----------|------------|
| L1 记忆 (Remember) | 识别、回忆 | 识别工具名称和基本参数格式 | "5分钟后提醒我喝水" → 知道要用 create_schedule |
| L2 理解 (Understand) | 解释、推断 | 正确解析口语化/模糊时间表达 | "明早" → 合理推断 07:00-08:00 |
| L3 应用 (Apply) | 执行、实施 | 将标准请求正确转化为结构化动作 | "每天早上9点提醒我打卡" → create_recurring(daily, 09:00) |
| L4 分析 (Analyze) | 分解、区分 | 从一条复杂指令中拆解出多个动作 | "取消8点的，改成9点" → [cancel, create] |
| L5 评价 (Evaluate) | 判断、决策 | 决定是执行、拒绝还是追问 | "昨天下午3点提醒我" → reject（过去时间） |
| L6 创造 (Create) | 设计、规划 | 处理开放式复杂场景，自主设计方案 | "工作时间每两小时提醒，午休跳过" → 自组织输出 |

### 3.2 为什么这个角度有价值

1. **理论支撑：** Bloom's Taxonomy 是教育评估最经典的框架（60年历史），被 COLING 2025 论文验证适用于 LLM 评测
2. **实践对齐：** 定时任务从 L1→L6 的难度递增，天然匹配 Bloom 的层级结构
3. **跨学科背景：** 物理+师范+编程的背景让这个交叉成为自然延伸，而非生硬嫁接
4. **空白填补：** 没有人做过 Bloom × Agent 工具使用的评测

---

## 4. 参考文献

```
[1] Huber & Niklaus. "LLMs meet Bloom's Taxonomy: A Cognitive View on 
    Large Language Model Evaluations." COLING 2025.
[2] Xu et al. "TPS-Bench: Evaluating AI Agents' Tool Planning & 
    Scheduling Abilities." arXiv:2511.01527, 2025.
[3] Fu et al. "The Agent's First Day: Benchmarking Learning, 
    Exploration, and Scheduling." arXiv:2601.08173, 2026.
[4] Seo et al. "SimuHome: A Temporal- and Environment-Aware Benchmark 
    for Smart Home LLM Agents." ICLR 2026 Oral.
[5] Ma et al. "BloomAPR: A Bloom's Taxonomy-based Framework for 
    LLM-Powered APR Solutions." arXiv:2509.25465, 2025.
[6] Ma et al. "EduEval: A Hierarchical Cognitive Benchmark for 
    Evaluating LLMs in Chinese Education." arXiv:2512.00290, 2025.
```
