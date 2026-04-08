# Starter Walkthrough

This file explains how the starter template runs from beginning to end.

## 1. Which command actually starts everything

You run:

```powershell
npm run promptfoo:starter
```

That command is defined in `package.json` and expands to:

```powershell
promptfoo eval -c starter_judge/promptfooconfig.yaml --env-file starter_judge/.env --no-progress-bar
```

So the true entrypoint is not a Python file. The true entrypoint is the `promptfoo eval` command.

## 2. What `promptfoo` reads first

Promptfoo first reads:

- `starter_judge/promptfooconfig.yaml`
- `starter_judge/.env`

From the config file it learns:

1. Which provider to call
2. Which prompt template to use
3. Which test cases to load

From `.env` it learns:

1. API key
2. Base URL
3. Judge model name

## 3. What each file is responsible for

### `promptfooconfig.yaml`

This is the framework entry.

It tells promptfoo:

1. Use `file://./judge_provider.py` as the provider
2. Use the prompt template `Judge which answer is better for this question: {{question}}`
3. Load test cases from `cases.yaml`

### `cases.yaml`

This is only data.

Each case contains:

1. `question`
2. `answer_a`
3. `answer_b`
4. `assert`

So this file answers one question only: what data should be evaluated?

### `judge_provider.py`

This is the adapter layer between promptfoo and your Python logic.

Promptfoo does not know your business logic, so it calls the function:

```python
call_api(prompt, options, context)
```

This file:

1. Reads `question`, `answer_a`, and `answer_b` from `context["vars"]`
2. Calls `run_judge(...)`
3. Converts the result into the shape promptfoo expects

So this file answers: how does promptfoo talk to my Python code?

### `judge_logic.py`

This is the real business logic.

It does three things:

1. Read environment variables such as `DEEPSEEK_API_KEY`
2. Build the judge prompt
3. Call the model and parse the JSON result

So this file answers: how is the judge model actually called?

## 4. What happens when one test case runs

Take one row in `cases.yaml`.

Promptfoo does this:

1. Load the case variables
2. Fill `{{question}}` into the prompt template
3. Call `judge_provider.py`
4. `judge_provider.py` extracts the original variables from `context["vars"]`
5. `judge_provider.py` calls `run_judge(question, answer_a, answer_b)`
6. `judge_logic.py` calls the LLM
7. The LLM returns JSON like `{"winner": "B", "reason": "..."}`
8. `judge_provider.py` returns that JSON to promptfoo as `output`
9. Promptfoo runs the assertions in `cases.yaml`
10. Promptfoo marks the case as pass, fail, or error

## 5. Why `validate` can pass but `eval` can still fail

This is a very important distinction.

### `promptfoo validate`

This checks only structure.

For example, it checks:

1. Is the YAML valid?
2. Does the config shape make sense?
3. Is the provider path formatted correctly?

It does not call your model.

### `promptfoo eval`

This is real execution.

It actually:

1. Loads the provider
2. Runs your Python function
3. Calls the external model API
4. Evaluates assertions

So missing API keys, invalid model names, network errors, or provider bugs only appear during `eval`.

## 6. The easiest way to memorize the architecture

Think in four layers:

1. `.env`: credentials and runtime settings
2. `cases.yaml`: evaluation data
3. `judge_provider.py`: adapter for promptfoo
4. `judge_logic.py`: actual model-calling logic

And above all of them:

5. `promptfoo eval`: the orchestrator

## 7. What you should change first when copying this template

When you build your next demo, usually only two files change a lot:

1. `judge_logic.py`
2. `cases.yaml`

Usually these files change very little:

1. `judge_provider.py`
2. `promptfooconfig.yaml`

That is the main benefit of this template. The framework wiring stays stable while your business logic and datasets evolve.