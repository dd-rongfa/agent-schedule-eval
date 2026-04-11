# Nanobot Live 三模型对比评测报告

> **测试日期**: 2026-04-11  
> **测试平台**: nanobot 0.1.5 + Telegram (@nb_claw_bot)  
> **测试方案**: test_plan_v2.yaml — 6 个 session、10 个 case  
> **评分方法**: AI 初判 + 人工复核（发现 1 处案例设计缺陷，修正后 29/30 判定点一致）  
> **原始数据**: [sessions/](sessions/) 目录包含全部 JSONL 会话记录

---

## 1. 总分一览

> T1（隐性意图）因案例设计缺陷标记为 INVALID，不计入通过率。详见 §3.3。

| 模型 | PASS | PARTIAL | FAIL | INVALID | 有效通过率 (9 case) |
|------|------|---------|------|---------|---------------------|
| **deepseek-chat** | 7 | 1 | 1 | 1 | 77.8% (7/9) |
| **mimo-v2-pro** | 9 | 0 | 0 | 1 | 100% (9/9) |
| **doubao-seed-2-0-pro** | 9 | 0 | 0 | 1 | 100% (9/9) |

---

## 2. 逐案对比

| ID | 维度 | deepseek-chat | mimo-v2-pro | doubao-seed-2-0-pro |
|----|------|---------------|-------------|---------------------|
| T3 | 口语化理解 | **PARTIAL** — 错用 `every_seconds=300`（循环）而非 `at`（一次性） | **PASS** — `cron(add, at≈now+5min)` | **PASS** — `cron(add, at≈now+5min)` |
| T10 | 状态感知 | **PASS** — `cron(list)` → 准确报告 | **PASS** — `cron(list)` → 准确报告 | **PASS** — 凭记忆回答，未调 list，信息准确 |
| T8 | 上下文修改 | **PASS** — remove + add | **PASS** — remove + add | **PASS** — remove + add |
| T4 | 工具干扰 | **PASS** — 无 cron 误触，答案正确；但 exec 13 次失败 | **PASS** — 无 cron 误触，答案正确；exec 8 次失败后 write_file 绕过 | **PASS** — 无 cron 误触，答案正确；exec 仅 1 次失败后直接心算 |
| T2 | 过去时间 | **PASS** — 拒绝 + 建议替代 | **PASS** — 拒绝 + 建议替代 | **PASS** — 拒绝 + 建议替代（额外变体"4月10号"也拦截） |
| T7 | 幻觉探测 | **PASS** — list → 如实说没有 | **PASS** — list + grep memory → 如实说没有 | **PASS** — list → 如实说没有，还提供现有任务供选择 |
| T6 | 边界值 | **PASS** — 30s 提醒已创建 **且触发** | **PASS*** — 30s 提醒已创建，但 `at` 为过去时间，未触发 | **PASS*** — 同 MiMo，`at` 为过去时间，未触发 |
| T9 | 条件推理 | **FAIL** — 立即查天气(level_1_wrong_a)，时序错误 | **PASS** — 设明天8点cron，message含"检查天气→条件提醒"指令 (level_3) | **PASS** — 设明天8点cron，message含"检查天气→条件提醒"指令 (level_3) |
| T1 | 隐性意图 | **INVALID** — 案例设计缺陷（见 §3.3） | **INVALID** | **INVALID** |
| T5 | 多步操作 | **PASS** — list → 7×remove → list verify，保留 dream | **PASS** — list + 记忆ID → 5×remove，保留 dream | **PASS** — list → 7×parallel remove，保留 dream |

---

## 3. 关键发现

### 3.1 DeepSeek 两个失分点

**T3 (PARTIAL)**: `every_seconds=300` vs `at`
- DeepSeek 将"五分钟之后叫我一声"理解为循环任务，使用了 `every_seconds` 参数
- 这意味着不只 5 分钟后响一次，而是每 5 分钟循环响
- MiMo 和 Doubao 都正确使用了 `at` 参数做一次性提醒
- **根因**: 对 cron 工具 schema 中 `every_seconds` vs `at` 的语义区分不清

**T9 (FAIL)**: 立即查天气 vs 延迟查天气
- DeepSeek 收到"如果明天下雨就提醒我带伞，早上8点"后，**立刻**尝试查天气
- 这是 level_1_wrong_a 策略：用今天的天气预测明天的行为，时序逻辑错误
- MiMo 和 Doubao 都选择了 level_3 策略：设置明天 8:00 的 cron 任务，将"检查天气 → 条件提醒"写入 message，让 agent 在触发时再判断
- **根因**: 未理解"如果"隐含的**延迟判断**语义

### 3.2 T4 exec 失败模式对比（Windows 双引号 Bug）

三个模型都遇到了 Windows 下 `python -c "..."` 的引号转义问题，但错误恢复策略差异巨大：

| 模型 | exec 尝试次数 | 恢复策略 | 效率 |
|------|-------------|----------|------|
| DeepSeek | 13 | 反复重试相同引号组合 | 最差 |
| MiMo | 8+1 | 尝试多种引号 → write_file + exec | 中等 |
| Doubao | 1 | 1 次失败后直接心算 $2^7 \times 2^8 = 2^{15}$ | 最优 |

### 3.3 T1 案例设计缺陷：循环提醒 vs 一次性提醒

T1 的铺底设定是**每天循环**的喝水提醒（`cron_expr: "0 9 * * *"` 和 `"0 14 * * *"`），但评分标准把 `cron(remove)` 设为最佳行为。

**矛盾**：对循环提醒来说，用户说"喝过水了"，合理行为是确认/标记今日完成，而不是取消明天的提醒。但 nanobot 的 cron 工具只有 `add / remove / list`，没有 `acknowledge` 或 `mark_complete`。

| 模型 | 行为 | 分析 |
|------|------|------|
| DeepSeek | "要取消下午3点的吗？" | 主动消歧，但如果用户确认取消 → 明天也没了 |
| MiMo | "需要取消某个喝水提醒吗？" | 同上，较泛 |
| Doubao | "哈哈不错呀👍" | 对循环提醒反而是最安全的行为 |

**根因**：案例设计隐含了一个系统不支持的能力假设（标记完成）。这恰好说明了 mock 评测（v2 中可以自由定义 `update_schedule`）与真实部署之间的 gap。

**处理方式**：T1 标记为 INVALID，不计入通过率。三个模型的有效评分基于剩余 9 个 case。

### 3.4 T6 秒级提醒的 stale-time grounding（三模型共性问题）

T6（"30秒后提醒我一下"）在主实验中被评为全 PASS，但复查原始日志后发现，**只有 DeepSeek 的提醒实际触发了**：

| 模型 | 用户消息时间 | 模型推算的当前时间 | 设置的 `at` | 是否触发 |
|------|------------|------------------|------------|----------|
| deepseek-chat | ~16:15:42 | — | ~16:16:12 | ✅ 触发并发送 message |
| mimo-v2-pro | 16:49:48 | 16:49:00 | 16:49:30 (-18s) | ❌ 过去时间，未触发 |
| doubao-seed-2-0-pro | 17:18:07 | 17:17:00 | 17:17:30 (-37s) | ❌ 过去时间，未触发 |

MiMo 和 Doubao 的 `reasoning_content` 都将当前时间截断到整分钟，导致 +30s 后的 `at` 仍然在用户消息时间之前。任务被系统接受（`Created job`）但从未触发。这与凌晨补测（§6）中 Doubao 的 T6 FAIL 是同一根因。

**深层问题**：这不是某个模型的 bug，而是 **系统级的 current-time grounding gap**——模型拿到的"当前时间"与用户消息的实际到达时间之间存在秒级偏移，在 near-now 调度场景下，这个偏移足以导致任务写入过去。

> 注：主实验评分仍保留 PASS*（任务结构正确、参数方向正确），但标注了实际未触发。这一发现支持 §6 补测中 T6 FAIL 的结论。

### 3.5 T9 条件推理：DeepSeek vs MiMo/Doubao 的认知分水岭

这是区分度最高的一个 case。核心问题：**"如果"该在什么时候判断？**

- **DeepSeek**: 立即查 → 用今天天气决定明天行为 → 时序错误 (FAIL)
- **MiMo/Doubao**: 利用 cron message 作为 agent 指令，将判断延迟到明天 8:00 执行 (PASS, level_3)

MiMo 和 Doubao 都展现了一种关键能力：**理解 cron 不只是定时器，更是延迟执行的 agent 任务**。它们将条件判断逻辑编码进 cron 的 message 字段，让未来的 agent 实例去执行。

### 3.6 Doubao 的额外表现亮点

- **T2 变体测试**: 用户追加了"26年4月10号下午3点"的提醒请求（具体日期而非"昨天"），Doubao 不调 cron 直接拦截并展示推理过程（"当前时间是2026年4月11日17:16"），优于 MiMo 先创建再告知过期
- **T5 并行 remove**: Doubao 在 list 之后批量并行调用 7 次 cron(remove)，是三者中唯一使用并行工具调用的

---

## 4. 模型画像

### deepseek-chat
- **强项**: 幻觉抑制 + 上下文修改稳定
- **弱项**: cron schema 理解有偏差 (T3)；不具备两阶段推理 (T9)
- **错误恢复**: 最差（exec 13 次失败，策略无变化）
- **风格**: 简洁专业

### mimo-v2-pro
- **强项**: 全面均衡，9/9 通过；T7 会搜 memory 增加上下文
- **弱项**: 无明显短板
- **错误恢复**: 中等（尝试多种引号写法 → write_file 变通）
- **风格**: 结构化输出（任务 ID、详情列表）

### doubao-seed-2-0-pro
- **强项**: T4 错误恢复最优（心算代替 exec）；T5 并行调用最高效；T2 变体测试最佳
- **弱项**: 无明显短板
- **错误恢复**: 最优（1 次失败即切换策略）
- **风格**: emoji 丰富，对话感强

---

## 5. 总结

| 维度 | 最优模型 |
|------|---------|
| 有效通过率 | MiMo = Doubao (9/9) > DeepSeek (7/9) |
| 条件推理 (T9) | MiMo = Doubao (level 3) >> DeepSeek (FAIL) |
| 错误恢复 (T4) | Doubao >> MiMo >> DeepSeek |
| 工具 schema 理解 (T3) | MiMo = Doubao > DeepSeek |
| 幻觉抑制 (T7) | 三者均优 |
| 多步操作效率 (T5) | Doubao (parallel) > MiMo = DeepSeek |

**核心结论**: 在 9 个有效日程 Agent 测试用例上，MiMo-v2-pro 和 Doubao-seed-2-0-pro 均实现 100% 通过，DeepSeek-chat 77.8% 通过。三者最大分水岭在 **T9 条件推理**（两阶段 cron 策略）和 **T3 工具参数选择**。但 T6 的深入分析揭示了一个跨模型共性问题：**秒级 near-now 调度的 stale-time grounding**（§3.4），只有 DeepSeek 的 30s 提醒实际触发。

**方法论发现**: T1 案例设计缺陷的发现，验证了阶段 3（真实部署）对阶段 2（mock 评测）的校验价值——mock 环境中可自由定义的 `update_schedule` 在真实系统中不存在，导致评分标准失效。这是"评测评测本身"的元层面收获。

---

## 6. 2026-04-12 凌晨补测（Doubao，补充观察）

> 数据来源：`sessions/doubao-seed-2-0-pro/telegram_6246303978_20260412_*.jsonl` 与 `telegram_6246303978_20260412_003757_active.jsonl`。
> 本轮发生在 **00:25–00:37**，因此只作为补充诊断，不直接替换 4/11 白天主实验总榜。

| ID | 判定 | 观察 |
|----|------|------|
| T3 | PASS | `cron(add, at=00:30)` 创建一次性提醒，后续也能正确改写 |
| T10 | PARTIAL | `cron(list)` 后能确认任务存在，但在"只是查询状态"时顺手把时间重新计算并改写了 |
| T8 | PASS | `remove → add`，成功改成 10 分钟后 |
| T4 | PASS | 未误触 `cron`；`exec` 引号失败后改用 `write_file + exec` 得到 `32768` |
| T2 | PASS | 对"昨天下午3点"和"2026年4月11日下午3点"都直接拦截 |
| T7 | PASS | 先 `cron(list)`，再如实说明没有会议提醒 |
| T6 | **FAIL** | 用户消息时间是 `00:32:06`，但模型在 `reasoning_content` 里显式写的是"Current time is 2026-04-12 00:31:00"，且未先做任何查时动作，直接按这个过期基准 `+30s` 得到 `at: 2026-04-12T00:31:30`；到 `00:37` 再 `cron(list)` 时该 job 仍挂在列表里，说明它把过去时间写进了 cron |
| T9 | PASS | 建了 `2026-04-13T08:00:00` 的单次任务，message 中包含"检查天气→下雨再提醒" |
| T1 | INVALID | 凌晨 `00:36` 时，`9:00` 和 `14:00` 两个喝水提醒都还没到，语义比白天更歧义 |
| T5 | PASS | `list → remove all`，且保留了 `dream` 系统任务 |

### 补测结论

- **保守记法**：`7 PASS / 1 PARTIAL / 1 FAIL / 1 INVALID`
- **T6 的根因已定位**：不只是"时间太近"，而是 **没做 fresh current-time grounding**。从原始 log 看，模型直接沿用了过期的 `00:31:00` 作为当前时间，没有显式校准，所以把过去时间写进了任务参数
- **新增暴露的问题**：真实环境下即便是强模型，也会在 near-now 调度里出现"当前时间读取滞后 / 跨日语义漂移"，尤其体现在秒级提醒（T6）和"明天 / 上午 / 下午"这类表达上
- **建议**：若要做可横向比较的正式复测，优先在 **白天或下午** 重跑；凌晨数据保留为补充诊断更合适
