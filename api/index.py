from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "power_site_mvp"

for path in (ROOT_DIR, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from power_site_mvp.app.main import app as fastapi_app

app = fastapi_app
application = app
handler = app
