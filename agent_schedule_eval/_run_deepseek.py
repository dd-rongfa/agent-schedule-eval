"""Wrapper to force DeepSeek env vars before running the test."""
import os
import sys

os.environ["TARGET_MODEL"] = "deepseek-chat"
os.environ["TARGET_BASE_URL"] = "https://api.deepseek.com/v1"
# Remove MiMo key if present; let the script fall back to DEEPSEEK_API_KEY
os.environ.pop("TARGET_API_KEY", None)
os.environ.pop("TARGET_ENV_PREFIX", None)

# Import and run
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_action_hallucination import main
main()
