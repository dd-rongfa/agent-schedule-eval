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

```json
{
  "id": "hard_deepseek-chat_direct_0",
  "dataset": "agent_tool_calling_hard_cases",
  "model": "deepseek-chat",
  "section": "direct",
  "operation": "direct",
  "failure_type": "wrong_tool",
  "user_input": "取消那个提醒",
  "expected_action": "cancel_schedule",
  "actual_tools_called": ["list_schedules"],
  "errors": ["期望调用 cancel_schedule，实际调用了 list_schedules"],
  "conversation": [...]  // OpenAI messages format
}
```

### action_hallucination.jsonl

```json
{
  "id": "hal_deepseek_chat_SD-1_0.1",
  "dataset": "action_hallucination_detection",
  "case_id": "SD-1",
  "fault_mode": "silent_drop",
  "user_request": "帮我设一个今天 08:00 的提醒，内容是开会",
  "labels": {
    "behavior_detected": true,
    "info_fabricated": true,
    "verdict": "detected_but_fabricated",
    "hallucination_type": ["fabricated_info", "detected_but_fabricated"]
  }
}
```

### hallucination_dpo_pairs.jsonl

```json
{
  "id": "dpo_SD-1",
  "case_id": "SD-1",
  "fault_mode": "silent_drop",
  "chosen": { "model": "deepseek-chat", "verdict": "fully_correct", ... },
  "rejected": { "model": "mimo-v2-pro", "verdict": "blind_confirm_fabricated", ... }
}
```

## 20 工具环境

get_current_time, create_schedule, cancel_schedule, create_recurring, list_schedules, update_schedule, create_todo, complete_todo, list_todos, delete_todo, play_media, pause_media, get_play_history, list_media_library, open_app, list_apps, bash, find_program, control_window, check_task_status

完整 tool schema 见 `eval/test_tool_calling.py`。

## 许可

研究用途。数据来源于受控环境下的模型 API 调用，不含任何个人信息。
