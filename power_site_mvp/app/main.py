from __future__ import annotations

import os
import base64
import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import parse_qs, quote
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from dotenv import load_dotenv
except ImportError:  # Keep the MVP bootable even if python-dotenv is unavailable.
    def load_dotenv(path: Path) -> bool:
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return True

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from . import geocode, geometry, parcel, policy, report, road, scoring, slope, vworld  # noqa: E402
from .schemas import AnalyzeRequest, PointRequest, PolicyReferenceUpsert, ReportRequest, ScoreRequest  # noqa: E402


app = FastAPI(title="PowerSite MVP", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or ("/tmp/powersite_reports" if os.getenv("VERCEL") else BASE_DIR / "reports"))
try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


@app.middleware("http")
async def redirect_loopback_ip_to_localhost(request: Request, call_next: Any) -> Any:
    host = request.headers.get("host", "")
    if host.startswith("127.0.0.1:"):
        target = str(request.url).replace("://127.0.0.1:", "://localhost:", 1)
        return RedirectResponse(target, status_code=307)
    return await call_next(request)


@app.middleware("http")
async def require_team_login(request: Request, call_next: Any) -> Any:
    if not _auth_required():
        return await call_next(request)

    path = request.url.path
    if _is_public_path(path):
        return await call_next(request)

    if not _login_configured():
        message = "APP_LOGIN_ID / APP_LOGIN_PASSWORD 환경변수가 필요합니다."
        if path.startswith("/api/"):
            return JSONResponse({"ok": False, "message": message}, status_code=503)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": message,
                "setup_error": True,
                "next_url": "/",
                "app_version": _asset_version(),
            },
            status_code=503,
        )

    if _valid_session(request):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"ok": False, "message": "로그인이 필요합니다."}, status_code=401)
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


@app.get("/login")
def login_page(request: Request, next: str = "/") -> Any:
    if _valid_session(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "setup_error": False,
            "next_url": _safe_next(next),
            "app_version": _asset_version(),
        },
    )


@app.post("/login")
async def login(request: Request) -> Any:
    body = (await request.body()).decode("utf-8", errors="ignore")
    data = parse_qs(body)
    username = (data.get("username") or [""])[0].strip()
    password = (data.get("password") or [""])[0]
    next_url = _safe_next((data.get("next") or ["/"])[0])

    if not _login_configured():
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "APP_LOGIN_ID / APP_LOGIN_PASSWORD 환경변수가 필요합니다.",
                "setup_error": True,
                "next_url": next_url,
                "app_version": _asset_version(),
            },
            status_code=503,
        )

    if _credentials_match(username, password):
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(
            "powersite_session",
            _make_session_cookie(username),
            max_age=12 * 60 * 60,
            httponly=True,
            secure=_secure_cookie(request),
            samesite="lax",
            path="/",
        )
        return response

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "아이디 또는 비밀번호가 올바르지 않습니다.",
            "setup_error": False,
            "next_url": next_url,
            "app_version": _asset_version(),
        },
        status_code=401,
    )


@app.get("/logout")
def logout() -> Any:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("powersite_session", path="/")
    return response


@app.get("/")
def index(request: Request) -> Any:
    app_version = _asset_version()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "kakao_js_key": os.getenv("KAKAO_JS_KEY", "").strip(),
            "vworld_domain": vworld.service_domain(),
            "key_status": _key_status(),
            "service_ids": vworld.service_ids(),
            "debug_vworld": vworld.debug_enabled(),
            "disclaimer": report.DISCLAIMER,
            "app_version": app_version,
            "auth_enabled": _auth_required(),
        },
    )


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "PowerSite MVP", "key_status": _key_status()}


@app.get("/api/config")
def config() -> Dict[str, Any]:
    return {
        "key_status": _key_status(),
        "vworld_domain": vworld.service_domain(),
        "service_ids": vworld.service_ids(),
        "debug_vworld": vworld.debug_enabled(),
        "disclaimer": report.DISCLAIMER,
    }


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest) -> Dict[str, Any]:
    address = payload.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력하세요.")

    geocoded = geocode.geocode_address(address)
    warnings = geocoded.get("warnings") or []
    if not geocoded.get("ok"):
        return {
            "ok": False,
            "address": address,
            "masked_address": mask_address(address),
            "message": geocoded.get("message"),
            "warnings": warnings,
            "score": scoring.score_analysis({}, payload.manual, []),
        }

    lat = float(geocoded["lat"])
    lng = float(geocoded["lng"])
    parcel_group = parcel.analyze_parcels(lat, lng, radius_m=200)
    main_parcel = parcel_group.get("main") or {}
    zoning = vworld.get_zoning_by_point(lat, lng)
    overlay_regulations = vworld.get_overlay_regulations(lat, lng, main_parcel.get("polygon") or [], zoning)
    growth = policy.evaluate_growth_management(zoning)
    roads_auto = road.analyze_roads(lat, lng, parcel_group, radius_m=500)
    roads = road.apply_manual_corrections(roads_auto, payload.manual)
    buildings = vworld.get_buildings_nearby(lat, lng, 3000)
    places = geocode.search_residential_risk_places(lat, lng, radius_m=1000)
    parcel_group = parcel.annotate_buildings(parcel_group, buildings)
    parcel_group = parcel.prepare_display_candidates(parcel_group, roads, zoning, limit=10)
    parcel_group = _annotate_parcel_group_zoning(parcel_group, zoning)
    slope_result = slope.analyze_slope(parcel_group)
    policy_result = policy.evaluate_policy(
        address,
        geocoded,
        payload.manual,
        BASE_DIR / "data" / "policy_reference.csv",
        BASE_DIR / "data" / "power_self_sufficiency_reference.csv",
    )
    permit_result = policy.evaluate_datacenter_permit(zoning, growth)
    selected_summary = parcel.summarize_selected(main_parcel, parcel_group.get("adjacent") or [], [])
    spatial = {
        "parcel": main_parcel,
        "parcel_group": parcel_group,
        "selected_parcel_summary": selected_summary,
        "zoning": zoning,
        "overlay_regulations": overlay_regulations,
        "growth_management": growth,
        "datacenter_permit": permit_result,
        "roads": roads,
        "roads_auto": roads_auto,
        "buildings": buildings,
        "places": places,
        "slope": slope_result,
        "policy": policy_result,
        "service_ids": vworld.service_ids(),
    }
    spatial["auto_lookup_failures"] = _spatial_failures(spatial)
    spatial["manual_check_items"] = _manual_check_items(spatial)
    analysis_result: Dict[str, Any] = {
        "ok": True,
        "address": address,
        "masked_address": mask_address(
            geocoded.get("road_address") or geocoded.get("jibun_address") or address
        ),
        "center": {"lat": lat, "lng": lng},
        "geocode": geocoded,
        **spatial,
        "warnings": warnings + _spatial_warnings(spatial),
    }
    analysis_result["score"] = scoring.score_analysis(analysis_result, payload.manual, [])
    return analysis_result


@app.post("/api/score")
def score(payload: ScoreRequest) -> Dict[str, Any]:
    analysis = dict(payload.analysis)
    analysis = _analysis_with_current_roads(analysis, payload.manual)
    selected_summary = parcel.selected_summary_from_analysis(analysis, payload.selected_parcel_ids)
    analysis["selected_parcel_summary"] = selected_summary
    result = scoring.score_analysis(analysis, payload.manual, payload.towers, payload.selected_parcel_ids)
    return {
        "ok": True,
        "score": result,
        "roads": analysis.get("roads"),
        "selected_parcel_summary": selected_summary,
        "transmission": result.get("metrics", {}).get("transmission"),
    }


@app.post("/api/parcel/point")
def parcel_at_point(payload: PointRequest) -> Dict[str, Any]:
    result = vworld.get_parcel_by_point(payload.lat, payload.lng)
    if result.get("ok"):
        zoning = vworld.get_zoning_by_point(payload.lat, payload.lng)
        result["zoning"] = zoning.get("main_zoning") or "미확인"
        result["zoning_names"] = zoning.get("names") or []
        result["zoning_lookup_status"] = "ok" if zoning.get("ok") else "failed"
        result["zoning_lookup_message"] = zoning.get("message")
        result["id"] = str(result.get("pnu") or f"manual-{payload.lat:.6f}-{payload.lng:.6f}")
        result["role"] = "manual_added"
        result["parcel_role"] = parcel.classify_parcel_role(str(result.get("land_category") or ""))
        result["relationship_to_main"] = "수동 추가 후보"
        result["is_incorporation_candidate"] = False
        result["has_road_contact"] = False
        result["road_connection_contribution"] = False
    return result


def _annotate_parcel_group_zoning(parcel_group: Dict[str, Any], base_zoning: Dict[str, Any]) -> Dict[str, Any]:
    main = parcel_group.get("main") or {}
    main_zoning = base_zoning.get("main_zoning") or "미확인"
    if main:
        main["zoning"] = main_zoning
        main["zoning_names"] = base_zoning.get("names") or []
        main["zoning_lookup_status"] = "ok" if base_zoning.get("ok") else "failed"
        main["zoning_lookup_message"] = base_zoning.get("message")

    seen: set[str] = set()
    candidates = [
        *(parcel_group.get("displayed_parcels") or []),
        *(parcel_group.get("display_adjacent") or []),
    ]
    for item in candidates:
        item_id = str(item.get("id") or item.get("pnu") or id(item))
        if item_id in seen or item is main:
            continue
        seen.add(item_id)
        point = item.get("centroid") or geometry.centroid(item.get("polygon") or [])
        if not point:
            item["zoning"] = item.get("zoning") or "미확인"
            item["zoning_lookup_status"] = "failed"
            item["zoning_lookup_message"] = "필지 중심점을 계산하지 못해 용도지역 자동조회 실패"
            continue
        zoning = vworld.get_zoning_by_point(float(point["lat"]), float(point["lng"]))
        item["zoning"] = zoning.get("main_zoning") or "미확인"
        item["zoning_names"] = zoning.get("names") or []
        item["zoning_lookup_status"] = "ok" if zoning.get("ok") else "failed"
        item["zoning_lookup_message"] = zoning.get("message")

    parcel_group["nearby_parcel_table"] = parcel.build_nearby_parcel_table(parcel_group.get("displayed_parcels") or [])
    parcel_group["summary"] = parcel.summarize_selected(
        parcel_group.get("main") or {}, parcel_group.get("adjacent") or [], parcel_group.get("selected_ids") or []
    )
    return parcel_group


@app.post("/api/policy-reference")
def upsert_policy_reference(payload: PolicyReferenceUpsert) -> Dict[str, Any]:
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return policy.upsert_policy_reference(BASE_DIR / "data" / "policy_reference.csv", data)


@app.post("/api/report/markdown")
def markdown(payload: ReportRequest) -> Response:
    analysis = _analysis_with_latest_score(payload)
    content = report.markdown_report(analysis, payload.manual, payload.towers, payload.privacy)
    return PlainTextResponse(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="powersite_report.md"'},
    )


@app.post("/api/report/csv")
def csv_report(payload: ReportRequest) -> Response:
    analysis = _analysis_with_latest_score(payload)
    content = report.score_csv(analysis)
    return PlainTextResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="powersite_score.csv"'},
    )


def mask_address(address: str) -> str:
    parts = [part for part in address.split() if part]
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return parts[0] if parts else "주소 비공개"


def _auth_required() -> bool:
    return _login_configured() or bool(os.getenv("VERCEL", "").strip())


def _login_configured() -> bool:
    return bool(os.getenv("APP_LOGIN_ID", "").strip() and os.getenv("APP_LOGIN_PASSWORD", ""))


def _is_public_path(path: str) -> bool:
    return path in {"/login", "/logout", "/health", "/favicon.ico"} or path.startswith("/static/")


def _credentials_match(username: str, password: str) -> bool:
    expected_user = os.getenv("APP_LOGIN_ID", "").strip()
    expected_password = os.getenv("APP_LOGIN_PASSWORD", "")
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password)


def _session_secret() -> str:
    return os.getenv("APP_SESSION_SECRET") or os.getenv("APP_LOGIN_PASSWORD") or "powersite-local-session"


def _sign_session_payload(payload: str) -> str:
    return hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_session_cookie(username: str) -> str:
    expires_at = int(time.time()) + 12 * 60 * 60
    payload = f"{username}|{expires_at}"
    signature = _sign_session_payload(payload)
    raw = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _valid_session(request: Request) -> bool:
    token = request.cookies.get("powersite_session", "")
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        username, expires_text, signature = raw.split("|", 2)
        payload = f"{username}|{expires_text}"
        if not hmac.compare_digest(signature, _sign_session_payload(payload)):
            return False
        if int(expires_text) < int(time.time()):
            return False
        return hmac.compare_digest(username, os.getenv("APP_LOGIN_ID", "").strip())
    except Exception:
        return False


def _safe_next(next_url: str) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    if "\r" in next_url or "\n" in next_url:
        return "/"
    return next_url


def _secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https" or bool(os.getenv("VERCEL", "").strip())


def _with_https_scheme(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _is_local_domain(url: str) -> bool:
    value = str(url or "").strip().lower()
    return "localhost" in value or "127.0.0.1" in value or value.startswith("http://0.0.0.0")


def _key_status() -> Dict[str, bool]:
    return {
        "kakao_rest": bool(os.getenv("KAKAO_REST_API_KEY", "").strip()),
        "kakao_js": bool(os.getenv("KAKAO_JS_KEY", "").strip()),
        "vworld": bool(os.getenv("VWORLD_API_KEY", "").strip()),
    }


def _asset_version() -> str:
    try:
        app_mtime = int((BASE_DIR / "static" / "app.js").stat().st_mtime)
        css_mtime = int((BASE_DIR / "static" / "style.css").stat().st_mtime)
        parcel_fix_mtime = int((BASE_DIR / "static" / "parcel-selection-fix.js").stat().st_mtime)
        return str(max(app_mtime, css_mtime, parcel_fix_mtime))
    except OSError:
        return "dev"


def _spatial_warnings(spatial: Dict[str, Any]) -> list[str]:
    warnings = []
    for key in ["parcel", "zoning", "roads", "buildings", "policy", "growth_management"]:
        if key == "growth_management":
            continue
        item = spatial.get(key) or {}
        if not item.get("ok") and item.get("message"):
            warnings.append(str(item["message"]))
    return warnings


def _analysis_with_latest_score(payload: ReportRequest) -> Dict[str, Any]:
    analysis = dict(payload.analysis)
    analysis = _analysis_with_current_roads(analysis, payload.manual)
    selected_summary = parcel.selected_summary_from_analysis(analysis, payload.selected_parcel_ids)
    analysis["selected_parcel_summary"] = selected_summary
    analysis["score"] = scoring.score_analysis(analysis, payload.manual, payload.towers, payload.selected_parcel_ids)
    return analysis


def _analysis_with_current_roads(analysis: Dict[str, Any], manual: Any) -> Dict[str, Any]:
    auto_roads = analysis.get("roads_auto")
    if isinstance(auto_roads, dict):
        analysis["roads"] = road.apply_manual_corrections(auto_roads, manual)
        return analysis

    if not _has_road_manual_override(manual):
        roads = dict(analysis.get("roads") or {})
        roads["manual_override_width_class"] = None
        roads.pop("construction_access_difficult_manual", None)
        access_path = dict(roads.get("access_path") or {})
        if access_path.get("manual_override"):
            access_path = {"method": "접도 불명확", "grade": "F", "via_parcels": []}
            roads["road_access_level"] = "F"
        roads["access_path"] = access_path
        analysis["roads"] = roads
        return analysis

    analysis["roads"] = road.apply_manual_corrections(analysis.get("roads") or {}, manual)
    return analysis


def _has_road_manual_override(manual: Any) -> bool:
    return any(
        bool(getattr(manual, name, False))
        for name in [
            "actual_road_10m",
            "actual_road_6m",
            "actual_road_4m",
            "farm_or_unpaved_road",
            "construction_access_difficult",
        ]
    )


def _spatial_failures(spatial: Dict[str, Any]) -> list[str]:
    labels = {
        "parcel": "필지",
        "zoning": "용도지역",
        "roads": "도로",
        "buildings": "건물밀집",
        "policy": "정책항목",
        "growth_management": "성장관리계획구역",
        "overlay_regulations": "중첩 규제구역",
    }
    failures = []
    for key, label in labels.items():
        if key == "growth_management":
            continue
        item = spatial.get(key) or {}
        if not item.get("ok"):
            failures.append(f"{label}: {item.get('message', '수동확인 필요')}")
    return failures


def _manual_check_items(spatial: Dict[str, Any]) -> list[str]:
    items = []
    parcel_group = spatial.get("parcel_group") or {}
    main = parcel_group.get("main") or spatial.get("parcel") or {}
    selected_summary = spatial.get("selected_parcel_summary") or {}
    land_text = " ".join(
        str(value or "")
        for value in [
            main.get("land_category"),
            *((selected_summary.get("land_categories") or [])),
        ]
    )
    if "임야" in land_text:
        items.append("지목이 임야인 필지가 있어 다드림/산지정보 추가 확인이 필요합니다.")
    items.append("송전탑·송전선 후보는 위성지도 수동마킹 기반이며 한전 및 현장확인이 필요합니다.")
    items.append("토지이음·다드림 자료는 직접 크롤링하지 않으며 최종 확인 링크 또는 수동확인 항목으로 둡니다.")
    return items
