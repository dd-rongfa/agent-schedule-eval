import json


def call_api(prompt, options, context):
    config = options.get("config", {})
    positive_words = set(config.get("positive_words", ["love", "great", "good", "excellent"]))
    negative_words = set(config.get("negative_words", ["terrible", "bad", "frustrating", "awful"]))

    text = context.get("vars", {}).get("text", prompt)
    normalized = text.lower()

    sentiment = "neutral"
    if any(word in normalized for word in positive_words):
        sentiment = "positive"
    elif any(word in normalized for word in negative_words):
        sentiment = "negative"

    result = {
        "sentiment": sentiment,
        "contains_promptfoo": "promptfoo" in normalized,
        "original_text": text,
    }

    return {
        "output": json.dumps(result, ensure_ascii=True),
        "tokenUsage": {
            "total": 0,
            "prompt": 0,
            "completion": 0,
        },
        "cost": 0,
        "cached": False,
    }