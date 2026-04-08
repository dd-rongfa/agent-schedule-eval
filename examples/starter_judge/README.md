# Starter Judge 入门模板

这是一个在原型代码和工程实践之间取平衡的模板。

只保留 4 个核心文件：

- `judge_logic.py`：业务逻辑 & 模型调用
- `judge_provider.py`：promptfoo 适配层
- `cases.yaml`：测试数据
- `promptfooconfig.yaml`：框架入口

## 为什么这个模板适合入门

1. 文件夹足够小，一次看完。
2. 模型调用与框架调用分离。
3. 测试数据外置，加 case 不用改代码。
4. API Key 从环境变量读取，不硬编码。

## 运行步骤

1. 创建或编辑 `starter_judge/.env`：

```env
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
JUDGE_MODEL=deepseek-chat
```

2. 校验配置：

```powershell
npx promptfoo validate -c starter_judge/promptfooconfig.yaml
```

3. 运行 demo：

```powershell
npm run promptfoo:starter
```

4. 如果不想依赖 npm script，等效原生命令：

```powershell
npx promptfoo eval -c starter_judge/promptfooconfig.yaml --env-file starter_judge/.env
```

## 常见失败原因

API Key 并非缺失，而是 `promptfoo` 从仓库根目录运行时找不到 `starter_judge/.env`。

- `promptfoo validate` 只检查配置结构，不调用 provider，也不校验 Key。
- `promptfoo eval` 才真正运行 `judge_provider.py` → `judge_logic.py` → 需要 `DEEPSEEK_API_KEY`。

## 如何复用这个模板

1. 复制整个文件夹。
2. 按需重命名 4 个文件。
3. 替换 `judge_logic.py` 中的 prompt 和模型调用逻辑。
4. 替换 `cases.yaml` 中的测试数据。
5. `judge_provider.py` 基本不需要改，除非输入输出结构变化。

## 执行流程详解

见 `WALKTHROUGH.md`，逐步解释 4 个文件如何协同，以及为什么 `validate` 通过了 `eval` 仍然报错。