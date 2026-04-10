"""Wrapper to force MiMo env vars before running the test."""
import os
import sys

os.environ["TARGET_MODEL"] = "mimo-v2-pro"
os.environ["TARGET_BASE_URL"] = "https://token-plan-cn.xiaomimimo.com/v1"
# MiMo API key must be set in .env as MIMO_API_KEY (or pass TARGET_API_KEY env var)
if not os.environ.get("TARGET_API_KEY"):
    from dotenv import load_dotenv
    load_dotenv()
    mimo_key = os.getenv("MIMO_API_KEY")
    if not mimo_key:
        print("ERROR: MIMO_API_KEY not found. Set it in .env or pass TARGET_API_KEY env var.")
        sys.exit(1)
    os.environ["TARGET_API_KEY"] = mimo_key
os.environ.pop("TARGET_ENV_PREFIX", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_action_hallucination import main
main()
