"""
Vercel Serverless Function 진입점 (api/index.py)
"""
import sys
from pathlib import Path

# 루트 디렉터리를 sys.path에 추가하여 main.py와 tools.py를 안전하게 참조
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
