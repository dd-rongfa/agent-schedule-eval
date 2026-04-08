# promptfoo demos

This folder contains three small demos that run locally without API keys.

## 1. Basic echo demo

Shows the core config shape:

- `providers`
- `prompts`
- `tests`
- `assert`

Run:

```powershell
npm run promptfoo:demo:echo
```

## 2. Logged output demo

Shows how to evaluate outputs that already exist in logs or production traces.
The `echo` provider returns the logged payload unchanged, and `transform` extracts the field you want to assert on.

Run:

```powershell
npm run promptfoo:demo:logs
```

## 3. Python provider demo

Shows how to connect promptfoo to local Python logic using `file://./demo_provider.py`.

Run:

```powershell
npm run promptfoo:demo:python
```

## 4. S01 framework demo

Wraps [s01.py](../s01.py) as a promptfoo Python provider so you can run the judge workflow through the framework.

Run:

```powershell
npm run promptfoo:demo:s01
```

## 5. S02 framework demo

Wraps [s02.py](../s02.py) as a promptfoo Python provider so you can run the full model-vs-model blind judging flow through the framework.

Run:

```powershell
npm run promptfoo:demo:s02
```

## Useful commands

Validate a config:

```powershell
npx promptfoo validate -c promptfoo/basic-echo.yaml
```

Open the local result viewer after an eval:

```powershell
npx promptfoo view -y
```