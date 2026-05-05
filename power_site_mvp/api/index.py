from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT_DIR.parent
for path in (ROOT_DIR, REPO_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app as fastapi_app

app = fastapi_app
application = app
handler = app
