# Email Management Skill（邮件管理技能）

## 适用场景
当用户需要**发送、接收或整理邮件**时，使用本技能。

## 可用工具

### send_email — 发送邮件
- `to`（必填）：收件人地址或姓名
- `subject`（必填）：邮件主题
- `body`（必填）：邮件正文
- `cc`（可选）：抄送人列表

### read_email — 读取邮件
- `folder`（可选）：邮箱文件夹，默认 `inbox`
- `limit`（可选）：读取数量，默认 10
- `unread_only`（可选）：是否只读未读邮件

### delete_email — 删除邮件
- `email_id`（可选）：精确邮件 ID
- `subject`（可选）：按主题模糊匹配删除

## 决策规则
1. "发邮件给 X" → `send_email`，to=X
2. "查看/收邮件" → `read_email`，folder="inbox"
3. "删除邮件" → `delete_email`，subject 或 email_id
4. 收件人不明确时 → 文字追问，不要猜测地址
