# MiMo-v2-pro 测试分析

**模型**: mimo-v2-pro (provider=custom, xiaomimimo.com)  
**测试日期**: 2026-04-11  
**测试方案**: test_plan_v2.yaml (S1-S6, T1-T10)

## 评分总览

| ID | 维度 | 得分 | 说明 |
|---|---|---|---|
| T3 | asr_tolerance | **PASS** | `cron(add, at="...T16:48:00")` — 正确使用 `at` 模式 |
| T10 | status_aware | **PASS** | `cron(list)` 查询当前状态 |
| T8 | rich_context | **PASS** | `remove` + `add` 更新定时器(5→10min) |
| T4 | tool_selection | **PARTIAL** | exec 6× SyntaxError，但发现 write-file 变通方案，最终答案正确(32768) |
| T2 | temporal_reasoning | **PASS** | 直接文本拒绝"已经过去了"，未调用任何工具 |
| T7 | hallucination_probe | **PASS** | 搜索 cron list + history.jsonl，确认无会议提醒 |
| T6 | boundary | **FAIL** | 设置 at=16:49:30 但当时已 16:49:48，30s 提醒从未触发 |
| T9 | chain_reasoning | **PASS** | 一次性任务 at 8:00 + 嵌入天气检查指令（Level 4 策略） |
| T1 | implicit | **PASS** | 识别隐性意图，主动询问"需要取消喝水提醒吗" |
| T5 | compound | **PASS** | list → 5×remove → list 验证 → 详细摘要 |

**总分: 8 PASS / 1 PARTIAL / 1 FAIL**

## 逐案详细分析

### S1: T3 → T10 → T8 (session: _164430, 14 msgs)

**T3 (asr_tolerance)** — "5分钟之后叫我一声"
- 工具调用: `cron(add, at="2026-04-11T16:48:00")`
- ✅ 正确使用 `at` 一次性模式（deepseek 错用 `every_seconds=300` 循环）
- 亮点：MiMo 对 at vs every_seconds 语义理解更准确

**T10 (status_aware)** — "提醒说好了没有"
- 工具调用: `cron(list)` 查询状态
- ✅ 正确识别"说好了没有"是查询意图

**T8 (rich_context)** — "改成10分钟"
- 工具调用: `cron(remove, job_id=...)` → `cron(add, at=...)`
- ✅ 正确理解上下文引用，remove 旧任务 + add 新任务

### S2: T4 (session: _164611, 20 msgs)

**T4 (tool_selection)** — "帮我算一下128乘以256"
- 过程: `exec(python -c "print(128*256)")` → SyntaxError (Windows 双引号 bug) × 6 次
- **变通**: 写入临时文件 `temp_calc.py` → exec 执行 → 得到 32768 → 删除临时文件
- ⚠️ 虽然最终正确，但浪费 6 次调用在错误方法上
- 对比 deepseek-chat: 也遇到 exec 问题但循环 13 次，未找到变通方案
- **MiMo 的 write-file 策略是关键差异，展示了错误恢复能力**

### S3: T2 (session: _164647, 2 msgs)

**T2 (temporal_reasoning)** — "帮我设一个昨天下午3点的提醒"
- 回复: 纯文本 "已经过去了，没办法设置"
- ✅ **零工具调用，直接拒绝** — 比 deepseek-chat（也是纯文本拒绝）更简洁

补测 (_164811, 10 msgs): 用户换成 "26年4月10号下午3点"
- MiMo 先读 SKILL.md → 创建了过去时间的 cron → 然后自己说 "已经过去了"
- ⚠️ 知道是过去但仍然创建了任务，逻辑矛盾

### S4: T7 (session: _164932, 16 msgs)

**T7 (hallucination_probe)** — "帮我取消昨天设的那个会议提醒"
- 过程: `cron(list)` → `grep(history.jsonl, "提醒")` → 尝试 remove 过期任务 → 复没回找到
- ✅ 没有凭空编造，而是搜索了历史记录后确认不存在
- 亮点: 主动用 `grep` 搜索历史对话，信息检索策略更全面

### S5: T6 + T9 (session: _165237, 12 msgs)

**T6 (boundary)** — "30秒后提醒我一下"
- 工具调用: `cron(add, at="2026-04-11T16:49:30")`
- ❌ 用户发送时间 ≈16:49:48，设置的 16:49:30 已在 18 秒前
- 30s 提醒从未触发（S6 中仍在列表里被手动删除）
- **时间计算错误**：MiMo 可能取了整分钟时间而非精确 +30s

**T9 (chain_reasoning)** — "如果明天下雨，就提醒我带伞，早上8点"
- 过程:
  1. `read_file(weather/SKILL.md)` — 了解天气查询能力
  2. `read_file(MEMORY.md)` — 检查已有信息
  3. `cron(add, at="2026-04-12T08:00:00", message="检查天气：使用curl检查wttr.in的天气。如果下雨，发送提醒'记得带伞！'。使用默认位置。")`
- ✅ **Level 4 策略**: 设置一次性任务在明早 8 点触发，任务 message 中嵌入了天气检查指令
- 这是一种"延迟执行+条件检查"方案：cron 触发时 agent 会读到 message，执行天气查询，然后根据结果决定是否提醒
- **对比 deepseek-chat**: 先立即查天气（Level 2）→ 失败后设 daily cron_expr（退化为 Level 1）→ FAIL

### S6: Setup + T1 + T5 (session: telegram_6246303978.jsonl, 44 msgs)

**Setup** — 4 项任务:
1. 每天早上9点喝水 → `cron(add, cron_expr="0 9 * * *")` + `list` 验证
2. 每天下午2点喝水 → `cron(add, cron_expr="0 14 * * *")` + `list` 验证
3. 2分钟后开会 → `cron(add, at="2026-04-11T16:55:00+08:00")` + `list` 验证
4. 5分钟后打电话 → `cron(add, at="2026-04-11T16:59:00+08:00")` + `list` 验证
- 亮点: **每次 add 后都自动 list 验证**，工作习惯严谨
- 开会提醒在 16:55:05 成功触发 ✅

**T1 (implicit)** — "我刚刚已经喝完水了"
- 回复: "需要取消某个喝水提醒吗？还是只是分享一下？"
- ✅ 识别了"喝完水"与喝水提醒的关联，主动询问是否取消
- 对比 deepseek: 直接定位到"下午那个要取消吗"（更具体）
- MiMo 的询问更开放，但核心意图识别到位

**T5 (compound)** — "先帮我看看还有什么提醒事件，然后全部取消"
- 工具链: `list` → `remove` ×5 → `list` 验证
- 移除: 打电话(4997c1b8) + 天气检查(e5b2477f) + 早9点水(9ac01a62) + 下午2点水(c53c51a6) + 30秒(7f86c069)
- 保留: dream（系统保护任务）
- ✅ 完美执行复合指令，并列出了全部已删除项目

## 关键发现

### MiMo vs deepseek-chat 差异对比

| 维度 | deepseek-chat | mimo-v2-pro | 差异 |
|---|---|---|---|
| T3 at vs every | ❌ 用了 every_seconds | ✅ 正确用 at | MiMo 语义理解更准 |
| T4 exec 恢复 | 13× 同样错误 | 6× 后改 write-file | MiMo 有错误恢复能力 |
| T6 30s 精度 | ✅ 触发成功 | ❌ 时间计算错误 | deepseek 时间精度更好 |
| T9 条件提醒 | ❌ 查当下天气 | ✅ 嵌入式延迟检查 | MiMo 策略大幅领先 |
| 验证习惯 | 有时验证 | 每次 add 后 list | MiMo 更严谨 |
| 信息检索 | 仅 cron list | cron list + grep history | MiMo 更全面 |

### MiMo 亮点
1. **T9 策略出色**: 将天气检查指令嵌入 cron message，实现了"延迟条件执行"（Level 4），这是三个模型中最优方案
2. **错误恢复**: T4 exec 失败后能自主切换到 write-file 方案
3. **验证习惯**: 每次操作后自动 list 确认
4. **信息检索**: T7 主动搜索 history.jsonl

### MiMo 弱点
1. **T6 时间计算**: 30s 短间隔场景时间计算出错，设了过去的时间
2. **T2 补测矛盾**: 知道时间过去但仍创建了任务
3. **T4 windows exec**: 仍然先尝试了 6 次错误的方法
