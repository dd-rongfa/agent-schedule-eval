# Agent 定时任务能力评测框架

> 三阶段递进评估：意图理解（v1）→ 工具调用执行（v2）→ 真实 Agent 部署（v3）。
> 从"说没说对"到"做没做对"再到"上线能不能用"，4 模型全链路覆盖。

---

## 项目演进

```
v1 意图理解        纯语言理解——模型说对了吗？
     ↓             → 发现：对话模型 93% 核心意图，但从不拒绝无效请求
v2 工具调用        给 20 工具 + 多轮——模型做对了吗？
     ↓             → 发现：工具约束下执行力跳到 89-95%，边界仍是瓶颈
v3 真实部署        Telegram 实测——Mock 结论上线还成立吗？
                   → 发现：基本成立，但工具集差异与 real-time time grounding 暴露新的系统级 gap
```

| 阶段 | 目录 | 核心问题 | 方法 | 数据量 | 状态 |
|------|------|---------|------|--------|------|
| [v1](v1_intent_eval/README.md) | v1_intent_eval/ | 纯语言理解能力天花板在哪？ | GEval (LLM Judge) + JSON 断言 | 26 case × 4 模型 × 3 轮 | ✅ |
| [v2](v2_tool_eval/README.md) | v2_tool_eval/ | 有工具约束后执行力如何？ | 确定性断言（无 LLM Judge） | 70 case × 4 模型 × 3 轮 | ✅ |
| [v3](v3_live_eval/nanobot/README.md) | v3_live_eval/nanobot/ | Mock 结论在真实 Agent 上是否成立？ | Telegram 实测 + 人工复核 | 10 case × 3 模型 | ✅ |

## 核心发现

### v1：意图理解（4 模型，GEval + 人工校准 κ=0.84）

| 模型 | 整体通过率 | 核心意图 (16) | 边界异常 (7) | 延迟 |
|------|-----------|--------------|-------------|------|
| deepseek-chat | **78.3%** | **93.8%** | 42.9% | 2.6s |
| doubao-seed-2-0-pro | 72.5% | 66.7% | **85.7%** | 14.1s |
| deepseek-reasoner | 60.9% | 60.4% | 61.9% | 23.1s |
| mimo-v2-pro | 59.4% | 60.4% | 57.1% | 15.7s |

1. **对话模型 > 推理模型**：deepseek-chat 核心意图 93.8%，deepseek-reasoner 仅 60.4%。推理模型过度谨慎——用户说"提醒改成 30 分钟"，reasoner 追问"内容没说"而非直接创建。意图理解靠常识推断，推理链反而干扰
2. **混合通过率掩盖了截然不同的失败模式**：deepseek-chat 核心能力极强但几乎从不 reject（对"3000年提醒我"也照做），doubao 边界判断最好（85.7%），两者弱点互补。这揭示了**模型"性格"差异**：盲目顺从 vs 过度谨慎

### v2：工具调用执行（确定性断言，70 case × 4 模型 × 3 轮）

| 模型 | 通过率 | 平均延迟 |
|------|--------|----------|
| mimo-v2-pro | **95.2%** ± 1.6% | 18.2s |
| deepseek-reasoner | 93.8% ± 2.2% | 20.7s |
| deepseek-chat | 89.5% ± 0.8% | 11.7s |
| doubao-seed-2-0-pro | 88.1% ± 2.2% | 22.3s |

3. **工具约束大幅提升执行力**：v1 最高 78%，v2 最低也到 88%。Tool schema + 多轮修正补偿了 v1 暴露的意图理解短板——**模型不需要完全理解意图，只需在工具约束下正确执行**
4. **boundary / temporal_reasoning 是共性瓶颈**：4 模型在这两个 section 通过率均为 50%/80%，与模型强弱无关
5. **rich_context 区分度最高**：deepseek-chat 67%、doubao 73%、reasoner/mimo 80%——从长上下文提取隐含时间线索的能力差异最明显

### v3：真实部署验证（Telegram 实测，3 模型）

| 模型 | 有效通过率 (9 case) |
|------|---------------------|
| mimo-v2-pro | **100%** |
| doubao-seed-2-0-pro | **100%** |
| deepseek-chat | 77.8% |

> **补充数据（2026-04-12 凌晨 / doubao live rerun）**：`7 PASS / 1 PARTIAL / 1 FAIL / 1 INVALID`。这轮不改写主榜，但额外暴露了 `T6` 的 **stale-current-time grounding** 问题。复查主实验日志后发现这是跨模型共性问题：MiMo（`at=16:49:30`，用户消息 `16:49:48`）和 Doubao（`at=17:17:30`，用户消息 `17:18:07`）的 30s 提醒都因当前时间截断到整分钟而设为过去时间，从未触发。只有 DeepSeek 的 30s 提醒实际触发并发送了消息。

6. **条件推理是最大分水岭**："如果明天下雨就提醒我带伞" — MiMo/Doubao 设延迟检查 cron (PASS)，DeepSeek 立即查天气 (FAIL)
7. **错误恢复策略差异显著**：同一 Windows exec bug，Doubao 1 次失败后心算，DeepSeek 重试 13 次
8. **Mock → 真实的 gap 确实存在**：T1 案例设计假设有 `mark_complete` 接口，但 nanobot 的 cron 工具集不支持，导致评分标准失效。但 9/10 case 可评，整体结论与 v2 一致
9. **near-now 调度的 stale-time grounding 是跨模型共性风险**：不限于凌晨——主实验白天数据中 2/3 模型的 30s 提醒也因同一原因未触发。模型默认的"当前时间"与消息实际到达时间之间的秒级偏移，在短时延调度下足以导致任务写入过去

### 三阶段联合结论

> v1 测理解力：对话模型核心意图 94%，但边界判断弱 → 需要工具约束
> v2 测执行力：给工具后 89-95%，边界/时间推理仍是共性瓶颈
> v3 测真实性：主结论基本成立，但真实系统进一步暴露了 **工具集差异、错误恢复策略、以及当前时间 grounding** 三类 last-mile 问题
>
> **一句话**：模型的理解和执行能力已经基本够用，真正难点收敛在边界判断、fresh current-time grounding，以及真实系统工具差异。

## 动机

**实际问题驱动**。部署开源 Agent 项目 [nanobot](https://github.com/panyanyany/nanobot) 后，在日常使用中发现定时任务的各类问题：循环任务和一次性任务参数混淆（`every_seconds` vs `at`）、跨日"明天"推算出错、秒级提醒因模型推理耗时导致时间参数落入过去。这些问题的共性是——模型能理解意图，但在时间参数精度上存在系统性短板。

**真实需求驱动**。定时提醒是 Agent 最高频的能力之一——监控异步任务完成后通知、会议前提醒、周期性打卡、条件触发（"如果下雨就提醒我带伞"）——这些场景天然是异步的，用户发完指令就走了，Agent 必须在正确的时间把消息送达。这意味着时间参数不能"大致对"，必须精确。

**评测空白**。主流 Agent 评测（AgentBench、ToolBench 等）聚焦代码生成和 workflow 调度，尚未看到针对"自然语言→时间参数→定时动作"这个垂直能力的系统评测。定时任务的认知复杂度跨度大（L1 识别意图 → L6 多约束规划），天然匹配 Bloom's Taxonomy 六层结构，适合做分层评测。

## 快速开始

```bash
pip install -r requirements.txt
# 配置 .env（DEEPSEEK_API_KEY / MiMo_API_KEY / Doubao_API_KEY）

# v2 一键评测：4 模型并行，跑完自动生成报告
cd v2_tool_eval
python run.py --runs 3

# v1 意图评测
cd v1_intent_eval
python run.py --runs 3

# 单独查看分析报告
python analyze.py --latest 3 --report
```

## 详细文档

- v1 意图理解评测 → [v1_intent_eval/README.md](v1_intent_eval/README.md)
- v2 工具调用评测 → [v2_tool_eval/README.md](v2_tool_eval/README.md)
- v3 真实部署报告 → [v3_live_eval/nanobot/report_3model_comparison.md](v3_live_eval/nanobot/report_3model_comparison.md)
