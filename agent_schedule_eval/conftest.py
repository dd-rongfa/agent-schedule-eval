import sys
from pathlib import Path

# 让 pytest 能找到上级目录里的模块（比如 mock_tools）
sys.path.insert(0, str(Path(__file__).resolve().parent))
