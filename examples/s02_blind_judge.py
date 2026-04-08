import json
import os
import time
from openai import OpenAI

# ==========================================
# 1. 客户端配置
# ==========================================
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

# 定义要测试的模型和裁判模型
MODEL_NORMAL = os.getenv("MODEL_NORMAL", "deepseek-chat")      # 非推理模型 (V3)
MODEL_REASONER = os.getenv("MODEL_REASONER", "deepseek-reasoner") # 推理模型 (R1)
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-chat")        # 裁判模型

# ==========================================
# 2. 迷你高难度测试集 (专门区分推理与非推理)
# ==========================================
test_questions = [
    {
        "id": 1,
        "type": "字形/计数陷阱",
        "question": "单词 'strawberrry' 里面共有几个字母 'r'？"
    },
    {
        "id": 2,
        "type": "空间与物理常识",
        "question": "把一个不漏水的玻璃杯倒扣在一个装满水的水盆里，杯子内部的水面会和盆里的水面一样高吗？为什么？"
    },
    {
        "id": 3,
        "type": "复杂逻辑推导",
        "question": "A、B、C三人赛跑。A说：我不是第一。B说：我是第一。C说：A不是第一。已知只有一人说真话，请问谁是第一？"
    },
    {
        "id": 4,
        "type": "边界条件陷阱",
        "question": "一个标准的正方形长方形桌子被锯掉了一个角，现在桌子还剩下几个角？请列出所有可能性。"
    },
    {
        "id": 5,
        "type": "语义与常识对抗",
        "question": "我昨天有5个苹果，今天吃了一个，然后我给了朋友两个，请问我明天有几个苹果？"
    }
]

# ==========================================
# 3. 核心函数定义
# ==========================================
def get_answer(model_name, question):
    """调用模型获取回答"""
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": question}]
    )
    # 注意：如果是 R1 推理模型，由于有思维链，我们只提取最终回答部分进行评判
    return response.choices[0].message.content

def run_judge(question, answer_a, answer_b):
    """调用裁判进行单次打分"""
    prompt = f"""你是一个公正的 AI 裁判。请评估两个模型对同一个问题的回答，判断哪个更好。
评估标准：1. 逻辑是否严密 2. 是否掉入陷阱 3. 最终答案是否准确。
问题：{question}
【模型 A 的回答】：\n{answer_a}
【模型 B 的回答】：\n{answer_b}

请你给出判决。必须输出 JSON 格式：{{"winner": "A" 或 "B" 或 "Tie", "reason": "一句话理由"}}
"""
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": "你是一个只输出 JSON 的机器。"},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    return json.loads(response.choices[0].message.content)

# ==========================================
# 4. 执行全自动流水线
# ==========================================
def main():
    print("🚀 开始全自动 LLM-as-a-Judge 测评流水线...\n")
    
    score_board = {"V3_Wins": 0, "R1_Wins": 0, "Ties": 0}

    for item in test_questions:
        print(f"▶️ 正在测试题目 {item['id']} [{item['type']}]")
        
        # 步骤 1：让两个模型做题
        print("   正在获取 V3 和 R1 的回答...")
        ans_v3 = get_answer(MODEL_NORMAL, item["question"])
        ans_r1 = get_answer(MODEL_REASONER, item["question"])
        
        # 步骤 2：消除位置偏见的双盲裁判
        print("   裁判正在进行双重交叉打分...")
        
        # 回合 1：V3 是 A，R1 是 B
        judge_1 = run_judge(item["question"], ans_v3, ans_r1)
        
        # 回合 2：R1 是 A，V3 是 B (交换位置)
        judge_2 = run_judge(item["question"], ans_r1, ans_v3)
        
        # 步骤 3：综合判定最终胜者
        final_winner = "Tie"
        # 如果回合1说B好(R1好)，且回合2说A好(也是R1好)，说明 R1 真的赢了
        if judge_1["winner"] == "B" and judge_2["winner"] == "A":
            final_winner = "R1 (推理模型)"
            score_board["R1_Wins"] += 1
        # 反之，说明 V3 赢了
        elif judge_1["winner"] == "A" and judge_2["winner"] == "B":
            final_winner = "V3 (非推理模型)"
            score_board["V3_Wins"] += 1
        else:
            score_board["Ties"] += 1
            
        print(f"   ✅ 本题最终胜出者: {final_winner}")
        print(f"   📝 裁判1理由: {judge_1.get('reason')}")
        print(f"   📝 裁判2理由: {judge_2.get('reason')}\n")
        
        time.sleep(1) # 防止触发 API 频率限制

    # 步骤 4：打印报表
    print("="*40)
    print("📊 最终双盲测评报告")
    print("="*40)
    print(f"DeepSeek-V3 (非推理) 获胜次数: {score_board['V3_Wins']}")
    print(f"DeepSeek-R1 (推理型) 获胜次数: {score_board['R1_Wins']}")
    print(f"平局次数: {score_board['Ties']}")

if __name__ == "__main__":
    main()