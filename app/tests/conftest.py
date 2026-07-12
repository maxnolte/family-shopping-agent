# Must run before shopping_agent modules are imported: db.py and ai_parser.py
# read their env at import time.
import os

os.environ.setdefault("DB_PATH", "/tmp/pytest-shopping.db")
os.environ.setdefault("GEMINI_API_KEY", "dummy-for-tests")
