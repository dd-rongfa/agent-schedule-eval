"""
共享模型 Provider
================
所有 v1/v2/v3 测试文件共用的模型配置与客户端创建。

用法:
    from provider import target_client, TARGET_MODEL
    from provider import judge_client, JUDGE_MODEL, get_judge_gpt_model

切换被测模型（只需传模型名，其余自动解析）:
    TARGET_MODEL=mimo-v2-pro  python -m pytest ...
    TARGET_MODEL=deepseek-chat python -m pytest ...   # 默认

注册新模型: 在 MODEL_REGISTRY 中添加一行即可。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ── .env 加载 ──────────────────────────────────────
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Model Registry ────────────────────────────────
# 模型名 → .env 中对应的 key/url 前缀
# 解析规则: {prefix}_API_KEY, {prefix}_BASE_URL
MODEL_REGISTRY: dict[str, str] = {
    "deepseek-chat":              "DEEPSEEK",
    "deepseek-reasoner":          "DEEPSEEK",
    "mimo-v2-pro":                "MiMo",
    "mimo-v2-omni":               "MiMo",
    "doubao-seed-2-0-pro-260215": "Doubao",
}

_DEFAULT_MODEL = "deepseek-chat"


def _resolve_model(model: str) -> tuple[str, str]:
    """根据模型名从 registry 查 API key 和 base_url。"""
    prefix = MODEL_REGISTRY.get(model)
    if prefix:
        api_key = os.getenv(f"{prefix}_API_KEY", "")
        base_url = os.getenv(f"{prefix}_BASE_URL", "https://api.deepseek.com/v1")
        return api_key, base_url
    # 未注册的模型，回退到 DEEPSEEK
    return (os.getenv("DEEPSEEK_API_KEY", ""),
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))


# ── Target 模型（被测模型） ────────────────────────

TARGET_MODEL = os.getenv("TARGET_MODEL", _DEFAULT_MODEL)
TARGET_API_KEY, TARGET_BASE_URL = _resolve_model(TARGET_MODEL)

target_client = OpenAI(api_key=TARGET_API_KEY, base_url=TARGET_BASE_URL)


# ── Judge 模型（LLM 评分，固定用 DeepSeek） ───────

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-chat")
JUDGE_API_KEY, JUDGE_BASE_URL = _resolve_model(JUDGE_MODEL)

judge_client = OpenAI(api_key=JUDGE_API_KEY, base_url=JUDGE_BASE_URL)


def get_judge_gpt_model():
    """延迟导入 deepeval，只有需要 GEval 时才调用。"""
    from deepeval.models import GPTModel
    return GPTModel(model=JUDGE_MODEL, api_key=JUDGE_API_KEY, base_url=JUDGE_BASE_URL)
