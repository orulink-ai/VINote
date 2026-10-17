import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
# Unit tests must never export fixtures to a developer's configured project.
# Live verification is explicitly available via scripts/check_langfuse.py --send.
ROOT_STR = str(ROOT_DIR)

if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

from app.config import settings

settings.langfuse_enabled = False
