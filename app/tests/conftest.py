# Must run before shopping_agent modules are imported: db.py and ai_parser.py
# read their env at import time.
import os

os.environ.setdefault("DB_PATH", "/tmp/pytest-shopping.db")
os.environ.setdefault("GEMINI_API_KEY", "dummy-for-tests")
os.environ.setdefault("WEBHOOK_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_NUMBERS", "41791234567,41797654321")
os.environ.setdefault("EVOLUTION_BASE_URL", "http://evolution.invalid")
os.environ.setdefault("EVOLUTION_API_KEY", "dummy-for-tests")
os.environ.setdefault("EVOLUTION_INSTANCE_NAME", "test")
