# Starter Judge Template

This is a compromise template between prototype code and engineering practice.

It keeps only four files that matter:

- `judge_logic.py`: business logic and model call
- `judge_provider.py`: promptfoo adapter layer
- `cases.yaml`: test data
- `promptfooconfig.yaml`: framework entry

## Why this template works for beginners

1. The folder is small enough to understand in one sitting.
2. The model call is separated from the framework call.
3. Test data is externalized, so you can add cases without touching logic.
4. API keys are read from environment variables instead of hard-coded.

## Run steps

1. Create or edit `starter_judge/.env`:

```env
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
JUDGE_MODEL=deepseek-chat
```

2. Validate config:

```powershell
npx promptfoo validate -c starter_judge/promptfooconfig.yaml
```

3. Run the demo:

```powershell
npm run promptfoo:starter
```

4. If you do not want to rely on the npm script, the equivalent raw command is:

```powershell
npx promptfoo eval -c starter_judge/promptfooconfig.yaml --env-file starter_judge/.env
```

## Why your previous run failed

Your API key was not missing from the project entirely. The issue was that `promptfoo` was run from the repository root, while the real `.env` file lived in `starter_judge/.env`.

`promptfoo validate` only checks config structure. It does not call the provider or verify API keys.

`promptfoo eval` actually runs `judge_provider.py`, which then calls `judge_logic.py`, which needs `DEEPSEEK_API_KEY` or `OPENAI_API_KEY`.

## How to copy this template later

1. Copy the whole folder.
2. Rename the four files if needed.
3. Replace the prompt and model-call logic in `judge_logic.py`.
4. Replace the cases in `cases.yaml`.
5. Keep `judge_provider.py` almost unchanged unless the input/output shape changes.

## Understand the execution flow

See `WALKTHROUGH.md` for a beginner-friendly explanation of how the files work together and why `validate` can pass while `eval` still fails.