# Schedule Management Skill（定时任务技能）

## 适用场景
当用户需要**创建、取消或管理定时提醒**时，使用本技能。

## 可用工具

### create_schedule — 一次性提醒
- `content`（必填）：提醒内容
- `delay_minutes`（可选）：多少分钟后触发
- `time`（可选）：绝对触发时间，格式 HH:MM

### cancel_schedule — 取消提醒
- `task_id`（可选）：精确任务 ID
- `description`（可选）：模糊描述，系统自动匹配

### create_recurring — 周期性提醒
- `content`（必填）：提醒内容
- `recurrence`（必填）：`daily` / `weekly` / `custom`
- `time`（可选）：每次触发的时间 HH:MM
- `days`（可选）：星期几，如 `["monday", "friday"]`
- `interval_minutes`（可选）：custom 模式下的间隔分钟数
- `total_count`（可选）：共触发几次

## 时间表达默认映射

用户描述模糊时，**直接使用以下默认值调用工具，不要追问**：

| 用户说 | 映射值 |
|---|---|
| 早上 / 明早 / 早 | `08:00` |
| 上午 | `10:00` |
| 中午 / 午饭 | `12:00` |
| 下午 | `15:00` |
| 傍晚 / 下班 | `18:00` |
| 晚上 | `20:00` |
| 明天 / 明日 | 今天日期 + 1天 |
| 后天 | 今天日期 + 2天 |
| 大后天 | 今天日期 + 3天 |

> 时间段 + 日期组合示例：  
> "明天早上" → 明天 `08:00`  
> "后天中午" → 后天 `12:00`  
> "明早" → 明天 `08:00`

## 决策规则
1. "X分钟后" → `create_schedule`，`delay_minutes=X`
2. 具体时刻（"下午3点"）→ `create_schedule`，`time="15:00"`
3. 模糊时段（"明早"、"后天中午"）→ 使用上表默认值，**直接调用工具**
4. "每天/每周/定期" → `create_recurring`，选合适 `recurrence`
5. 用户要求取消 → `cancel_schedule`，尽量提供 description
6. 用户多次改口时 → **以最后一次为准**，直接调用工具，不要追问
7. 需要"取消再重建"时 → **连续发起两次 tool call**（先 cancel，再 create）
8. content 未明确说明时 → 用 `"提醒"` 作为默认值，**不要因为 content 缺失而拒绝调用工具**

---

## 示例（Few-shot）

### 示例 1：用户反复改口，以最终值为准
> 用户：帮我设一个10分钟后的提醒，不对，改成20分钟，算了还是30分钟吧

分析：用户最终决定是30分钟。content 没有明说，使用默认值。

✅ 正确做法：
```json
{"name": "create_schedule", "arguments": {"content": "提醒", "delay_minutes": 30}}
```

❌ 错误做法：追问"请问您想提醒什么内容？"（content 缺失不是阻塞条件）

---

### 示例 2：用户多步改口，最终状态是最后一个设置
> 用户：先设个5分钟提醒，不对取消，再设10分钟，再取消，最后设15分钟

分析：用户最终想要的是15分钟后的提醒。

✅ 正确做法：
```json
{"name": "create_schedule", "arguments": {"content": "提醒", "delay_minutes": 15}}
```

---

### 示例 3：取消旧的，建新的 → 两次 tool call
> 用户：把明天早上8点的会议提醒取消，改成9点

分析：需要先取消8点的，再建9点的。**连续调用两个工具**。

✅ 正确做法（按顺序调用）：
1. `{"name": "cancel_schedule", "arguments": {"description": "明天早上8点的会议提醒"}}`
2. `{"name": "create_schedule", "arguments": {"content": "会议提醒", "time": "09:00"}}`

---

### 示例 4：先建后取消 → 两次 tool call
> 用户：先帮我设一个明天下午3点的提醒，然后把今天下午那个取消

✅ 正确做法：
1. `{"name": "create_schedule", "arguments": {"content": "提醒", "time": "15:00"}}`
2. `{"name": "cancel_schedule", "arguments": {"description": "今天下午的提醒"}}`

---

### 示例 5：每周循环
> 用户：每周一和周五下午6点提醒我

✅ 正确做法：
```json
{"name": "create_recurring", "arguments": {"content": "提醒", "recurrence": "weekly", "time": "18:00", "days": ["monday", "friday"]}}
```
注意：days 用英文小写星期名称。
