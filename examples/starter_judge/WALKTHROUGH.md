# Starter 执行流程详解

本文逐步解释 starter 模板从启动到出结果的完整流程。

## 1. 真正的入口是什么

你运行：

```powershell
npm run promptfoo:starter
```

该命令定义在 `package.json`，展开为：

```powershell
promptfoo eval -c starter_judge/promptfooconfig.yaml --env-file starter_judge/.env --no-progress-bar
```

所以真正的入口不是 Python 文件，而是 `promptfoo eval` 命令。

## 2. promptfoo 先读什么

promptfoo 首先读取：

- `starter_judge/promptfooconfig.yaml`
- `starter_judge/.env`

从配置文件得知：

1. 调用哪个 provider
2. 使用什么 prompt 模板
3. 加载哪些测试用例

从 `.env` 得知：

1. API Key
2. Base URL
3. Judge 模型名

## 3. 每个文件的职责

### `promptfooconfig.yaml`

框架入口。告诉 promptfoo：

1. 使用 `file://./judge_provider.py` 作为 provider
2. 使用 prompt 模板 `Judge which answer is better for this question: {{question}}`
3. 从 `cases.yaml` 加载测试数据

### `cases.yaml`

纯数据文件。每条 case 包含：

1. `question`
2. `answer_a`
3. `answer_b`
4. `assert`

只回答一个问题：评测什么数据？

### `judge_provider.py`

适配层——连接 promptfoo 和你的 Python 逻辑。

promptfoo 不了解你的业务逻辑，它只调用：

```python
call_api(prompt, options, context)
```

这个文件：

1. 从 `context["vars"]` 提取 `question`、`answer_a`、`answer_b`
2. 调用 `run_judge(...)`
3. 把结果转成 promptfoo 需要的格式

回答的问题：promptfoo 怎么跟我的 Python 代码通信？

### `judge_logic.py`

真正的业务逻辑。做三件事：

1. 读取环境变量（`DEEPSEEK_API_KEY` 等）
2. 构建 Judge prompt
3. 调用模型并解析 JSON 结果

回答的问题：Judge 模型是怎么被调用的？

## 4. 一条测试用例的执行过程

以 `cases.yaml` 中的一行为例，promptfoo 依次：

1. 加载该 case 的变量
2. 将 `{{question}}` 填入 prompt 模板
3. 调用 `judge_provider.py`
4. `judge_provider.py` 从 `context["vars"]` 提取原始变量
5. `judge_provider.py` 调用 `run_judge(question, answer_a, answer_b)`
6. `judge_logic.py` 调用 LLM
7. LLM 返回 JSON，如 `{"winner": "B", "reason": "..."}`
8. `judge_provider.py` 将 JSON 作为 `output` 返回给 promptfoo
9. promptfoo 执行 `cases.yaml` 中的 assert
10. promptfoo 标记该 case 为 pass / fail / error

## 5. 为什么 validate 通过但 eval 仍然报错

这是一个非常重要的区别。

### `promptfoo validate`

只检查结构，例如：

1. YAML 是否合法？
2. 配置结构是否正确？
3. provider 路径格式对不对？

**不调用模型。**

### `promptfoo eval`

才是真正执行——它会：

1. 加载 provider
2. 运行你的 Python 函数
3. 调用外部模型 API
4. 执行 assert 断言

所以缺 API Key、模型名错误、网络问题、provider bug 都只在 `eval` 阶段暴露。

## 6. 最简单的记忆方式

四层架构：

1. `.env`：凭证和运行配置
2. `cases.yaml`：评测数据
3. `judge_provider.py`：promptfoo 适配器
4. `judge_logic.py`：模型调用逻辑

以及它们之上的编排层：

5. `promptfoo eval`：统一调度器

## 7. 复用模板时优先改什么

通常只需大改两个文件：

1. `judge_logic.py`（prompt 和模型逻辑）
2. `cases.yaml`（测试数据）

Usually these files change very little:

1. `judge_provider.py`
2. `promptfooconfig.yaml`

That is the main benefit of this template. The framework wiring stays stable while your business logic and datasets evolve.