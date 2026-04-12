# Agent Tool-Calling Hard-Case Dataset

> 自动从 v2_tool_eval 评测结果生成 | 构建时间：2026-04-12 19:32

## 数据集概览

| 数据集 | 记录数 | 用途 |
|--------|--------|------|
| tool_call_hard_cases | 12 | 从评测轨迹筛选的工具调用失败案例（DPO 负样本 / 弱点诊断） |
| action_hallucination | 64 | 故障注入下的幻觉检测标注 |
| hallucination_dpo_pairs | 6 | 同 case 下正确 vs 幻觉的对比训练对 |
| generated_hard_cases | 31 | 按 6 类错误 pattern 程序化生成、真实跑框架采集的困难轨迹 |

## 数据来源

- **正向失败轨迹**：v2_tool_eval 的 70 case × 4 模型 × 多轮运行中 passed=False 的完整对话
- **幻觉检测轨迹**：FlakyScheduler 故障注入（4 种故障模式）× 4 模型 × 2 温度
- **程序化生成轨迹**：从 6 类已知错误 pattern（tool_confusion / missing_tool / wrong_params / blind_retry / hallucination / chain_break）定义 case，通过 `generate_cases.py` + `run_dataset.py` 在真实框架上采集，自动判定 + 预填标注

## 失败类型分类

| 类型 | 说明 |
|------|------|
| wrong_tool | 调了错误的工具 |
| missing_tool | 应该调工具但没调（退化为纯文本） |
| tool_confusion | 在相似工具间选错（如 schedule vs todo） |
| wrong_params | 工具对了但参数错误 |
| over_clarify | 信息已完整却追问用户 |

## 幻觉类型分类

| 类型 | 说明 |
|------|------|
| blind_confirm | 工具返回异常但模型盲目确认成功 |
| fabricated_info | 模型编造工具未返回的信息（任务 ID、时间等） |
| detected_but_fabricated | 检测到异常但回复中夹带编造内容 |
| execution_gap | 未调用工具就回复 |

## Schema

### tool_call_hard_cases.jsonl

| 字段 | 说明 |
|------|------|
| id | 唯一标识，含模型名和 section |
| model | 运行模型 |
| section / operation | 测试分区（direct / temporal 等） |
| failure_type | 失败类型（见上表） |
| user_input | 用户原始输入 |
| expected_action | 正确应调用的工具 |
| actual_tools_called | 模型实际调用的工具列表 |
| errors | 判定失败的具体原因 |
| conversation | 完整对话，OpenAI messages 格式，可直接用于 SFT/DPO |

### action_hallucination.jsonl

| 字段 | 说明 |
|------|------|
| id | 唯一标识，含模型名、case_id、温度 |
| case_id / fault_mode | 故障注入场景（SD=silent_drop, PM=param_mismatch 等） |
| user_request | 用户输入 |
| tool_calls / tool_responses | 完整工具交互记录 |
| labels.behavior_detected | 模型是否检测到异常 |
| labels.info_fabricated | 回复中是否含编造信息 |
| labels.verdict | 综合判定（blind_confirm / detected_but_fabricated / fully_correct 等） |

### hallucination_dpo_pairs.jsonl

| 字段 | 说明 |
|------|------|
| id | 对应 case_id |
| fault_mode | 故障模式 |
| chosen | 正确回复一方（model + 完整对话 + verdict） |
| rejected | 幻觉回复一方（model + 完整对话 + verdict） |

## 20 工具环境

get_current_time, create_schedule, cancel_schedule, create_recurring, list_schedules, update_schedule, create_todo, complete_todo, list_todos, delete_todo, play_media, pause_media, get_play_history, list_media_library, open_app, list_apps, bash, find_program, control_window, check_task_status

完整 tool schema 见 `eval/test_tool_calling.py`。

## 当前状态与下一步方向

### 已完成
- 从现有 v2 评测结果中筛选失败轨迹（过滤了 61% 误判后保留 12 条真实失败）
- 故障注入 × 4 模型 × 2 温度的幻觉检测标注（64 条）
- 6 类错误 pattern 程序化 case 定义 + 真实框架采集（31 条，1 模型）

### 已知局限
- `generated_hard_cases` 目前只跑了 deepseek-chat，尚未覆盖其他模型
- `hallucination` pattern 的 auto-verdict 有效性低（4 条全为 needs_manual_review），需人工标注
- `wrong_params` 对 deepseek-chat 无区分力（5/5 全过），参数混淆 case 难度不足

### 下一步方向
1. **扩大模型覆盖**：用同一套 30 case 跑 4 个模型，生成跨模型对比数据
2. **加入诊断工具扩展**：`diagnose_error` + `wait_and_retry`（已在 `eval/diagnostic_tools.py` 实现）纳入正式工具集，测试带诊断工具后模型的鲁棒性变化
3. **人工标注 hallucination**：对 needs_manual_review 的 case 建立人工标注规范，补全 DPO 对
4. **提升 wrong_params 难度**：加入更隐蔽的参数陷阱（如时区歧义、隐式日期格式）

## 许可

研究用途。数据来源于受控环境下的模型 API 调用，不含任何个人信息。
