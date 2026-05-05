from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from starlette.responses import RedirectResponse

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "power_site_mvp"
DEFAULT_PUBLIC_ORIGIN = "https://power-site-scout-stable.vercel.app"

# Keep VWorld/Kakao domain-sensitive calls on the single production origin even
# when Vercel exposes preview/branch/project URLs. These are public origins, not
# secrets; API keys still come only from Vercel environment variables.
os.environ.setdefault("APP_PUBLIC_URL", DEFAULT_PUBLIC_ORIGIN)
os.environ.setdefault("VWORLD_DOMAIN", DEFAULT_PUBLIC_ORIGIN)

for path in (ROOT_DIR, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from power_site_mvp.app.main import app as fastapi_app


def _with_https_scheme(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _origin_url(value: str) -> str:
    normalized = _with_https_scheme(value)
    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return normalized.rstrip("/")


def _is_local_origin(origin: str) -> bool:
    host = (urlparse(_with_https_scheme(origin)).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _canonical_origin() -> str:
    for key in ("APP_PUBLIC_URL", "VWORLD_DOMAIN"):
        value = os.getenv(key, "").strip()
        if value:
            return _origin_url(value)
    return DEFAULT_PUBLIC_ORIGIN


def _header(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin1").split(",")[0].strip()
    return ""


def _request_origin(scope: dict) -> str:
    host = _header(scope, b"x-forwarded-host") or _header(scope, b"host")
    proto = _header(scope, b"x-forwarded-proto") or scope.get("scheme") or "https"
    return f"{proto}://{host}".rstrip("/") if host else ""


class CanonicalOriginApp:
    def __init__(self, wrapped_app):
        self.wrapped_app = wrapped_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") in {"GET", "HEAD"}:
            canonical = _canonical_origin()
            current = _request_origin(scope)
            if canonical and current and not _is_local_origin(canonical) and current.lower() != canonical.lower():
                path = scope.get("path") or "/"
                query = (scope.get("query_string") or b"").decode("latin1")
                target = f"{canonical}{path}{'?' + query if query else ''}"
                response = RedirectResponse(target, status_code=308)
                await response(scope, receive, send)
                return
        await self.wrapped_app(scope, receive, send)


app = CanonicalOriginApp(fastapi_app)
application = app
handler = app
