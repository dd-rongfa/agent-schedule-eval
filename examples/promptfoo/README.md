# promptfoo 示例集

本文件夹包含若干小型 demo，可在本地运行，无需 API Key（echo/logged 不调模型）。

## 1. 基础 echo demo

展示 promptfoo 配置的核心结构：

- `providers`
- `prompts`
- `tests`
- `assert`

运行：

```powershell
npm run promptfoo:demo:echo
```

## 2. 日志回放 demo

展示如何对已有的日志/线上输出做评测。
`echo` provider 原样返回 logged payload，`transform` 提取需要断言的字段。

运行：

```powershell
npm run promptfoo:demo:logs
```

## 3. Python provider demo

展示如何通过 `file://./demo_provider.py` 把 promptfoo 接入本地 Python 逻辑。

运行：

```powershell
npm run promptfoo:demo:python
```

## 4. S01 框架 demo

将 [s01_simple_judge.py](../s01_simple_judge.py) 包装为 promptfoo Python provider，通过框架运行 Judge 流程。

运行：

```powershell
npm run promptfoo:demo:s01
```

## 5. S02 框架 demo

将 [s02_blind_judge.py](../s02_blind_judge.py) 包装为 promptfoo Python provider，运行双模型盲评流程。

运行：

```powershell
npm run promptfoo:demo:s02
```

## 常用命令

校验配置：

```powershell
npx promptfoo validate -c promptfoo/basic-echo.yaml
```

运行评测后打开本地结果查看器：

```powershell
npx promptfoo view -y
```