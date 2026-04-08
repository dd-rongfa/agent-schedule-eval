import json
import os
from openai import OpenAI

# ==========================================
# 1. 配置裁判大模型 (这里以 DeepSeek 官方 API 为例)
# 你也可以换成 OpenAI、阿里云、智谱等任何兼容 OpenAI SDK 的模型
# ==========================================
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-chat")

# ==========================================
# 2. 准备测试数据 (Question + Model A + Model B)
# ==========================================
test_cases = [
    {
        "id": 1,
        "question": "蜗牛在20米深的井底，白天往上爬5米，晚上向下滑4米。请问它几天能爬出井口？",
        "answer_a": "蜗牛每天净向上爬 5 - 4 = 1 米。井深 20 米，所以需要 20 / 1 = 20 天。答案是20天。", # 非推理模型的直觉错误
        "answer_b": "前15天，蜗牛每天净爬1米，第15天结束时爬了15米。第16天白天，蜗牛向上爬5米，15 + 5 = 20米，直接爬出井口，不会再向下滑。答案是16天。" # 推理模型的正确逻辑
    },
    {
        "id": 2,
        "question": "大卫有三个姐妹，每个姐妹都有一个兄弟。请问大卫有几个兄弟？",
        "answer_a": "大卫有三个姐妹，每个姐妹有一个兄弟，所以是 3 * 1 = 3 个兄弟。大卫有3个兄弟。", # 常见的模型幻觉错误
        "answer_b": "大卫的三个姐妹的那个“一个兄弟”，其实就是大卫本人。因此大卫没有其他的兄弟。答案是0个（大卫是唯一的男孩）。" # 推理模型的正确逻辑
    }
]

# ==========================================
# 3. 编写裁判提示词 (Prompt Engineering)
# ==========================================
def get_judge_prompt(question, answer_a, answer_b):
    return f"""你是一个公正的 AI 裁判。你的任务是评估两个 AI 模型对同一个问题的回答，判断哪个更好。
    
请重点考察：
1. 逻辑推理是否严密，是否掉入思维陷阱。
2. 最终答案是否准确。

问题：{question}

【模型 A 的回答】：
{answer_a}

【模型 B 的回答】：
{answer_b}

请你给出判决。你必须且只能输出严格的 JSON 格式，不要有任何其他废话。格式如下：
{{
    "winner": "A" 或 "B" 或 "Tie",
    "reason": "请用一句话简述判决理由"
}}
"""

# ==========================================
# 4. 执行流水线 (Pipeline 核心逻辑)
# ==========================================
def run_evaluation():
    results = {"A_wins": 0, "B_wins": 0, "Ties": 0}
    
    print("🚀 开始运行 LLM-as-a-Judge 自动化测评...\n")
    
    for item in test_cases:
        print(f"正在评估题目 {item['id']}...")
        prompt = get_judge_prompt(item['question'], item['answer_a'], item['answer_b'])
        
        try:
            # 调用裁判模型
            response = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个只输出 JSON 的机器。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}, # 强制输出 JSON (需模型支持)
                temperature=0.1 # 裁判需要稳定，温度调低
            )
            
            # 解析裁判结果
            judge_result = json.loads(response.choices[0].message.content)
            winner = judge_result.get("winner")
            reason = judge_result.get("reason")
            
            print(f"✅ 裁判结果: 获胜者是 {winner}")
            print(f"📝 裁判理由: {reason}\n")
            
            # 统计分数
            if winner == "A":
                results["A_wins"] += 1
            elif winner == "B":
                results["B_wins"] += 1
            else:
                results["Ties"] += 1
                
        except Exception as e:
            print(f"❌ 评估题目 {item['id']} 时发生错误: {e}\n")

    # ==========================================
    # 5. 输出最终报告
    # ==========================================
    print("="*30)
    print("📊 最终测评报告")
    print("="*30)
    print(f"模型 A (非推理) 获胜次数: {results['A_wins']}")
    print(f"模型 B (推理型) 获胜次数: {results['B_wins']}")
    print(f"平局次数: {results['Ties']}")
    
if __name__ == "__main__":
    run_evaluation()