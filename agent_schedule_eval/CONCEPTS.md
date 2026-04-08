# AI 评测必备概念 — 查缺补漏清单

> 目的：做大模型/Agent 评测需要的统计学和方法论基础
> 
> 分为三类：🔴 必须掌握（Phase 1 就要用）、🟡 应该了解（做对比实验时用）、🟢 锦上添花（写文章/答辩时加分）

---

## 一、评分可信度（你的裁判靠不靠谱）🔴

### 1.1 信度 Reliability — "量两次，结果一样吗"

| 概念 | 一句话解释 | 你什么时候用到 |
|------|-----------|---------------|
| **评分者间信度** (Inter-rater reliability) | 两个人（你 vs GEval）给同一个东西打分，一致性多高 | Phase 1：验证 GEval |
| **重测信度** (Test-retest reliability) | 同一个 case 跑两次 GEval，分数波动大不大 | Phase 1：检查 GEval 稳定性 |
| **内部一致性** (Internal consistency) | 同一份测试里的各题是不是在测同一个东西 | 暂不需要 |

### 1.2 效度 Validity — "你量的是你想量的吗"

| 概念 | 一句话解释 | 你什么时候用到 |
|------|-----------|---------------|
| **内容效度** (Content validity) | 你的 case 覆盖了要测的能力吗？有没有遗漏？ | 设计 case 时自问 |
| **构念效度** (Construct validity) | 分数高真的代表能力强吗？ | Bloom 分层是否真的反映认知层级 |
| **预测效度** (Predictive validity) | 测试成绩能预测真实表现吗？ | "评测通过"的模型在实际场景也好用吗？ |

### 1.3 关键统计量

#### Cohen's Kappa (κ)
- **是什么：** 衡量两个评分者的一致性，排除了"碰巧一致"的概率
- **公式概念：** κ = (实际一致率 - 随机一致率) / (1 - 随机一致率)
- **解读标准（Landis & Koch 1977）：**

```
κ < 0.20    几乎没有一致性（你的裁判不可用）
0.21-0.40   一般（需要改进裁判 prompt）
0.41-0.60   中等（可以用，但要注明局限）
0.61-0.80   较好（可以信赖）
0.81-1.00   很好（几乎等于人工）
```

- **怎么算：**
```python
from sklearn.metrics import cohen_kappa_score
# human_labels 和 geval_labels 都是 pass/fail 的列表
kappa = cohen_kappa_score(human_labels, geval_labels)
```

#### Spearman 等级相关系数 (ρ)
- **是什么：** 衡量两组排名的相关性（不要求线性，比 Pearson 适合打分数据）
- **范围：** -1 到 1，越接近 1 表示排名越一致
- **怎么算：**
```python
from scipy.stats import spearmanr
rho, p_value = spearmanr(human_scores, geval_scores)
# rho > 0.7 且 p < 0.05 → 相关性显著
```

#### 标准差 (σ) — 重测信度用
- **是什么：** 同一个 case 跑 N 次，分数的离散程度
- **期望：** σ < 0.15 表示评分稳定
- **怎么算：**
```python
import numpy as np
scores = [0.8, 0.75, 0.85]  # 一个 case 跑 3 次的分数
std = np.std(scores)  # 0.041
```

---

## 二、阈值校准（0.7 从哪来）🔴

### 正确做法（不是拍脑袋）

```
1. 跑一遍测试，收集所有 case 的 GEval 分数
2. 自己标注每个 case 是 pass 还是 fail
3. 尝试不同阈值（0.5, 0.6, 0.7, 0.8），看哪个跟人工判断最吻合
4. 用 F1-score 或准确率找最优 cutoff
```

### 相关概念

| 概念 | 一句话 |
|------|--------|
| **准确率** (Accuracy) | 跟人工一致的比例 |
| **精确率** (Precision) | 机器说 pass 的里面，人工也说 pass 的比例 |
| **召回率** (Recall) | 人工说 pass 的里面，机器也说 pass 的比例 |
| **F1-score** | Precision 和 Recall 的调和平均，平衡两者 |
| **ROC 曲线** | 不同阈值下 True Positive Rate vs False Positive Rate 的曲线 |
| **AUC** | ROC 曲线下面积，越接近 1 越好，0.5 = 随机猜 |

---

## 三、实验设计（怎么做对比才公平）🟡

| 概念 | 一句话 | 什么时候用 |
|------|--------|-----------|
| **Baseline** | 对照组，没有它你的数字没意义 | Phase 2 多模型对比 |
| **控制变量** | 比较两个模型时，prompt/case/评分标准必须一样 | Phase 2 |
| **消融实验** (Ablation) | 去掉一个组件看效果变化多少 | 如：去掉 system prompt，通过率变多少？ |
| **统计显著性** | 差异不是碰巧的 | 样本量 ≥ 30 时可以做 t-test |
| **效应量** (Effect size) | 差异有多大（不只是"有没有差"） | Cohen's d > 0.8 = 大效应 |

---

## 四、LLM-as-a-Judge 专题（这个领域特有的）🟡

### 4.1 已知问题

| 问题 | 说明 |
|------|------|
| **位置偏差** (Position bias) | 给 judge 两个回答，先出现的更容易被选好 |
| **自我偏好** (Self-preference) | GPT 给 GPT 的输出打分更高 |
| **冗长偏好** (Verbosity bias) | 更长的回答更容易得高分 |
| **分数膨胀** (Score inflation) | LLM judge 普遍偏高分 |

### 4.2 缓解方法

| 方法 | 做法 |
|------|------|
| 多次评分取平均 | 同一个 case 跑 3 次 GEval |
| 人工锚定 | 用人工标注校准（你正在做的 Phase 1） |
| 不同 judge 对比 | 用 DeepSeek judge + GPT judge，看一致性 |
| 结构化评分 | 给 judge 明确的评分维度（GEval 已经在做） |

### 4.3 核心论文（如需深入）

```
- Zheng et al. "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." NeurIPS 2023.
  → LLM-as-a-Judge 的奠基论文，70%+ 与人类一致

- Liu et al. "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment." EMNLP 2023.
  → GEval 方法论来源

- ℹ️ 以下论文待验证，仅供参考方向：
  Position bias in LLM evaluators — 搜索关键词：position bias, LLM-as-a-Judge
  → 位置偏差的系统研究
```

---

## 五、Bloom's Taxonomy 使用注意事项 🟢

### 你的用法 vs 原始定义

| | 原始 Bloom（教育学） | 你的用法 |
|---|---|---|
| 评测对象 | 学生的认知过程 | 模型的任务处理能力 |
| 层级含义 | 认知复杂度 | 输入/任务复杂度 |
| 是否严格 | 有严格定义和动词分类 | 借用框架做难度分级 |

### 面试时怎么说（诚实 > 正确）

> "我借用了 Bloom's Taxonomy 作为测试用例设计的组织框架。严格来说，Bloom 衡量的是学习者的认知过程，我这里更接近用它来做任务复杂度的分层。选择 Bloom 是因为它天然提供了从简单识别到复杂创造的六级递进，跟定时任务从'设个闹钟'到'规划多条件复杂提醒'的难度递增是吻合的。COLING 2025 的论文验证了这个框架在 LLM 评测中的适用性，但我清楚这是类比借用，不是严格教育学意义上的应用。"

---

## 六、学习优先级

### 🔴 Phase 1 就要用的（现在学）
1. Cohen's Kappa — 1 行代码，但要理解含义
2. Spearman ρ — 1 行代码
3. 标准差 — 已经会了
4. 阈值校准的思路 — 概念上理解就行

### 🟡 Phase 2 要用的（做对比时学）
5. Baseline 和控制变量思维
6. LLM-as-a-Judge 的已知偏差
7. 简单可视化（热力图，matplotlib 够用）

### 🟢 需要时再查的
8. ROC/AUC
9. 效应量
10. Bloom 的原始论文（Anderson & Krathwohl 2001 修订版）

---

## 推荐资源（精选，不贪多）

| 资源 | 为什么推荐 | 优先级 |
|------|-----------|--------|
| sklearn 文档的 cohen_kappa_score 页面 | 有例子，5 分钟能跑通 | 🔴 |
| Zheng et al. 2023 MT-Bench 论文 | LLM judge 领域必读，了解一致性怎么报告的 | 🟡 |
| Huber & Niklaus 2025 COLING 论文 | 你项目的理论基础 | 🟡 |
