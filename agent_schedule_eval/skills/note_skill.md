# Note Taking Skill（笔记管理技能）

## 适用场景
当用户需要**创建、搜索或删除笔记**时，使用本技能。

## 可用工具

### create_note — 创建笔记
- `title`（必填）：笔记标题
- `content`（必填）：笔记正文
- `tags`（可选）：标签列表，如 `["工作", "会议"]`

### search_notes — 搜索笔记
- `query`（必填）：搜索关键词或句子
- `tags`（可选）：按标签过滤

### delete_note — 删除笔记
- `note_id`（可选）：精确笔记 ID
- `title`（可选）：按标题模糊匹配

## 决策规则
1. "记录/写下/存一下" → `create_note`，填 title + content
2. "找/搜/查一下我的笔记" → `search_notes`，query 填用户关键词
3. "删掉/移除这条笔记" → `delete_note`，尽量提供 title
4. 内容不明确时 → 文字追问，不要生成空白笔记
