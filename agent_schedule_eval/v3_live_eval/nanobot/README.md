# 阶段 3 — 真实 Agent 部署验证

> 阶段 2 在 Mock 环境下用确定性断言测了 70 个 case。阶段 3 把同类场景搬到真实 Agent 上，验证受控结论是否成立。

---

## 方法

### 测试环境

| 组件 | 配置 |
|------|------|
| Agent 框架 | [nanobot](https://github.com/panyanyany/nanobot) v0.1.5 |
| 交互通道 | Telegram (@nb_claw_bot) |
| 工具集 | cron (add/remove/list), exec, write_file, read_file, grep, message |
| 时区 | Asia/Shanghai |
| maxToolIterations | 25 |

### 被测模型

| 模型 | 厂商 | 定位 |
|------|------|------|
| deepseek-chat | DeepSeek | 基础聊天模型 |
| mimo-v2-pro | 小米 | 推理模型 |
| doubao-seed-2-0-pro-260215 | 字节跳动 | 旗舰模型 |

> **公平性说明**: deepseek-chat 是基础聊天模型，与其他两家的旗舰/推理模型不在同一档位。这也是评测发现之一。

### 测试方案

[test_plan_v2.yaml](test_plan_v2.yaml) — 6 个 session（S1-S6），10 个 case（T1-T10），每 session 之间用 `/new` 隔离。

| Session | Case | 维度 | 测试 prompt |
|---------|------|------|-------------|
| S1 | T3 | 口语化理解 | "五分钟之后叫我一声" |
| S1 | T10 | 状态感知 | "我的提醒设好了没？" |
| S1 | T8 | 上下文修改 | "把刚才那个提醒改成10分钟后" |
| S2 | T4 | 工具干扰 | "帮我算一下128乘以256等于多少" |
| S3 | T2 | 过去时间 | "帮我设一个昨天下午3点的提醒" |
| S4 | T7 | 幻觉探测 | "取消我的会议提醒" |
| S5 | T6 | 边界值 | "30秒后提醒我一下" |
| S5 | T9 | 条件推理 | "如果明天下雨就提醒我带伞，早上8点" |
| S6 | T1 | 隐性意图 | "我已经喝过水了" |
| S6 | T5 | 多步操作 | "先帮我看看有什么提醒，然后全部取消" |

### 评分方法

- AI 初判（基于 session JSONL 原始记录） + 人工复核
- 发现 1 处案例设计缺陷（T1，见报告 §3.3），修正后 29/30 判定点 AI/人工一致

---

## 结果

详见 → [report_3model_comparison.md](report_3model_comparison.md)

### 概览

| 模型 | 有效通过率 (9 case) | 主要失分 |
|------|---------------------|----------|
| deepseek-chat | 77.8% (7/9) | T3: 工具参数错误, T9: 时序推理失败 |
| mimo-v2-pro | 100% (9/9) | — |
| doubao-seed-2-0-pro | 100% (9/9) | — |

> **补充说明（2026-04-12 凌晨补测 / doubao）**：00:25–00:37 的补测中，`T6` 暴露出一次 **past-time bug**。从原始 log 看，模型没有先校准当前时间，而是沿用了过期的 `00:31:00` 来推算 `30s`，最终创建了 `at=00:31:30` 的过去任务。`T1` / `T9` 也因为凌晨跨日而更敏感。因此主表仍以 4/11 白天的标准化结果为准；午夜数据作为补充诊断，详见 `report_3model_comparison.md` §6。

#### 凌晨补测数据（Doubao, 2026-04-12）

| PASS | PARTIAL | FAIL | INVALID | 备注 |
|------|---------|------|---------|------|
| 7 | 1 | 1 | 1 | `T6` 暴露 stale-current-time bug |

### 关键发现

1. **条件推理是最大分水岭 (T9)**: "如果明天下雨就提醒我带伞" — MiMo/Doubao 设延迟检查 cron，DeepSeek 立即查天气（时序错误）
2. **错误恢复策略差异显著 (T4)**: 同一 Windows exec bug，Doubao 1 次失败后心算，DeepSeek 重试 13 次
3. **T1 案例设计缺陷**: 循环提醒没有 `mark_complete` 接口 → 评分标准失效 → 标记为 INVALID
4. **秒级提醒暴露 fresh-time grounding 风险 (T6)**: 这是一个跨模型共性问题，不限于凌晨。主实验中 MiMo（用户 16:49:48 → `at=16:49:30`）和 Doubao（用户 17:18:07 → `at=17:17:30`）都将当前时间截断到整分钟导致 `at` 设为过去，任务未触发。只有 DeepSeek 的 30s 提醒实际触发并发送了消息。凌晨补测进一步确认了同一根因

---

## 原始数据

所有 Telegram session JSONL 存放于 [sessions/](sessions/) 目录：

```
sessions/
├── deepseek-chat/
├── mimo-v2-pro/
└── doubao-seed-2-0-pro/  （含 2026-04-12 凌晨补测日志）
```

每个 JSONL 文件包含完整的 user/assistant/tool 消息流，可用于复现分析。

---

## 与阶段 2 的关键差异

| 维度 | 阶段 2 (Mock) | 阶段 3 (Live) |
|------|--------------|---------------|
| 工具 | 18 个 Mock 工具，可自由定义 | nanobot 真实工具集（cron/exec/file） |
| 断言 | 确定性代码断言 | AI 初判 + 人工复核 |
| 输入 | YAML 定义的精确文本 | Telegram 语音/文字输入 |
| 发现 | 工具路由、参数精度 | 错误恢复、条件推理、系统工具集限制 |

**核心价值**: 阶段 3 发现了阶段 2 无法暴露的问题——Mock 环境中 `update_schedule` 可以自由定义，但真实系统的 cron 只有 add/remove/list，导致 T1 评分标准在真实场景中失效。这验证了"Mock 评测必须用真实部署校验"的方法论。
