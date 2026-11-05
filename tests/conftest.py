import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="robin_test_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-for-robin-unit-tests-only"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
