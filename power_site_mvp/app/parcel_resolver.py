from __future__ import annotations

import inspect
import re
import unicodedata
from typing import Any, Dict, List, Tuple

from . import geometry, parcel, vworld


SEARCH_RADII_M = [20, 50, 100, 200, 500]
_ORIGINAL_ANALYZE = None
_PATCHED = False


def patch() -> None:
    global _ORIGINAL_ANALYZE, _PATCHED
    if _PATCHED:
        return
    _ORIGINAL_ANALYZE = parcel.analyze_parcels
    parcel.analyze_parcels = analyze_parcels_with_address_resolution
    _PATCHED = True


def analyze_parcels_with_address_resolution(lat: float, lng: float, radius_m: int = 200, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    group = _ORIGINAL_ANALYZE(lat, lng, radius_m=radius_m, *args, **kwargs)
    address = str(kwargs.get("address") or _caller_address() or "")
    hint = parse_address_lot_hint(address)
    main = group.get("main") or {}

    if _area_m2(main) > 0 and (not hint.get("normalized_jibun") or _lot_match_score(main, hint) > 0):
        return group

    resolved = resolve_main_parcel_from_address(group, lat, lng, hint)
    return resolved or group


def parse_address_lot_hint(address: str) -> Dict[str, str]:
    text = unicodedata.normalize("NFKC", str(address or "")).strip()
    matches = list(re.finditer(r"(산\s*)?\d+(?:\s*-\s*\d+)?", text))
    if not matches:
        return {"raw": text, "legal_dong": "", "jibun": "", "normalized_jibun": ""}

    match = matches[-1]
    legal_dong = ""
    for token in reversed(re.split(r"\s+", text[: match.start()].strip())):
        if re.search(r"(동|리|읍|면)$", token):
            legal_dong = token
            break

    jibun = match.group(0).replace(" ", "")
    return {
        "raw": text,
        "legal_dong": legal_dong,
        "jibun": jibun,
        "normalized_jibun": _normalize_lot_value(jibun),
    }


def resolve_main_parcel_from_address(group: Dict[str, Any], lat: float, lng: float, hint: Dict[str, str]) -> Dict[str, Any]:
    queried, search_radius, lookup_message = _query_parcels_expanding(lat, lng)
    existing = list(group.get("nearby_parcels") or [])
    if group.get("main"):
        existing.append(group["main"])
    candidates = _dedupe_prepared(existing + queried, {"lat": lat, "lng": lng})

    if not candidates:
        return _mark_failed(group, lookup_message)

    main, method, warning = _choose_main_parcel(candidates, hint)
    if not main or _area_m2(main) <= 0:
        return _mark_failed(group, lookup_message)

    return _rebuild_group(group, main, candidates, {"lat": lat, "lng": lng}, search_radius, lookup_message, method, warning)


def _query_parcels_expanding(lat: float, lng: float) -> Tuple[List[Dict[str, Any]], int, str]:
    anchor = {"lat": lat, "lng": lng}
    results: List[Dict[str, Any]] = []
    messages: List[str] = []
    last_radius = SEARCH_RADII_M[-1]

    for radius in SEARCH_RADII_M:
        last_radius = radius
        response = vworld.query_vworld_data_layer(parcel.PARCEL_LAYER, bbox=geometry.bbox_around(lat, lng, radius), size=1000)
        message = response.get("message")
        if message:
            messages.append(f"{radius}m: {message}")

        for feature in response.get("features") or []:
            item = parcel.parcel_from_feature(feature)
            if not item:
                continue
            distance = parcel.anchor_distance_m(anchor, item)
            if distance is None or distance > radius:
                continue
            item["anchor_distance_m"] = round(distance, 1)
            results.append(item)

        results = _dedupe_prepared(results, anchor)

    return results, last_radius, " | ".join(messages)


def _choose_main_parcel(parcels: List[Dict[str, Any]], hint: Dict[str, str]) -> Tuple[Dict[str, Any], str, str]:
    with_area = [item for item in parcels if _area_m2(item) > 0]
    if not with_area:
        return {}, "not_found", _lookup_failed_message("")

    scored = [(_lot_match_score(item, hint), item) for item in with_area]
    scored = [(score, item) for score, item in scored if score > 0]
    if scored:
        scored.sort(key=lambda pair: (-pair[0], _distance(pair[1]), -_area_m2(pair[1])))
        return scored[0][1], "jibun_match", "입력 주소 지번과 일치하는 연속지적도 필지를 메인 필지로 지정했습니다."

    development = [item for item in with_area if _is_development_candidate(item)]
    if development:
        development.sort(key=lambda item: (_distance(item), -_area_m2(item)))
        return development[0], "nearest_development_candidate", "입력 지번과 정확히 일치하는 필지를 찾지 못해 좌표와 가장 가까운 개발 가능 필지를 메인 필지로 지정했습니다. 주소 기준 필지 자동매칭은 불완전하므로 수동확인 필요"

    with_area.sort(key=lambda item: (_distance(item), -_area_m2(item)))
    return with_area[0], "nearest_area_parcel", "주소 기준 필지 자동매칭은 불완전하므로 수동확인 필요"


def _rebuild_group(group: Dict[str, Any], main: Dict[str, Any], parcels: List[Dict[str, Any]], anchor: Dict[str, float], search_radius: int, lookup_message: str, method: str, warning: str) -> Dict[str, Any]:
    main_code = parcel.parcel_code(main)
    nearby = _dedupe_prepared(parcels, anchor)
    if main_code and not any(parcel.parcel_code(item) == main_code for item in nearby):
        nearby.insert(0, main)

    for item in nearby:
        is_main = parcel.parcel_code(item) == main_code
        item["role"] = "main" if is_main else "adjacent"
        item["relationship_to_main"] = "메인" if is_main else _relationship_to_main(main, item)
        item["distance_from_main_m"] = 0 if is_main else _round(parcel.parcel_distance_m(main.get("polygon") or [], item.get("polygon") or []))
        item["is_incorporation_candidate"] = False
        item["selection_status"] = "메인 필지" if is_main else "검토 후보"

    displayed = parcel.get_connected_display_parcels(nearby, main, limit=10) or [main]
    adjacent = [item for item in nearby if parcel.parcel_code(item) != main_code]
    display_adjacent = [item for item in displayed if parcel.parcel_code(item) != main_code]
    difficulty = parcel.calculate_parcel_group_difficulty(displayed)

    group.update(
        {
            "ok": True,
            "anchor_point": anchor,
            "main": main,
            "connection_root_parcel_id": main_code,
            "recommended_main_parcel_id": main_code,
            "nearby_parcels": nearby[:120],
            "adjacent": adjacent[:120],
            "displayed_parcels": displayed,
            "display_adjacent": display_adjacent,
            "display_limit": 10,
            "search_radius_m": search_radius,
            "display_excluded_count": max(0, len(nearby) - len(displayed)),
            "selected_ids": [],
            "nearby_parcel_table": parcel.build_nearby_parcel_table(displayed),
            "summary": parcel.summarize_selected(main, adjacent, []),
            "message": warning,
            "main_resolution_status": "resolved",
            "main_resolution_method": method,
            "main_resolution_warning": warning,
            "vworld_parcel_lookup_message": lookup_message or "",
            **difficulty,
        }
    )
    group["site_scenarios"] = parcel.build_site_scenarios(group)
    return group


def _mark_failed(group: Dict[str, Any], lookup_message: str) -> Dict[str, Any]:
    message = _lookup_failed_message(lookup_message)
    group["main"] = {"ok": False, "message": message, "area_m2": 0, "area_pyeong": 0}
    group["message"] = message
    group["vworld_parcel_lookup_message"] = message
    group["main_resolution_warning"] = message
    group["ok"] = False
    return group


def _lot_match_score(item: Dict[str, Any], hint: Dict[str, str]) -> int:
    target = hint.get("normalized_jibun") or ""
    if not target:
        return 0
    legal_dong = _normalize_plain(hint.get("legal_dong") or "")
    best = 0

    for value in _parcel_text_values(item):
        text = _normalize_plain(value)
        lots = _extract_lots(value)
        if target in lots:
            best = max(best, 100 if legal_dong and legal_dong in text else 90)
        elif target.replace("산", "") in [lot.replace("산", "") for lot in lots]:
            best = max(best, 70 if legal_dong and legal_dong in text else 60)
    return best


def _parcel_text_values(item: Dict[str, Any]) -> List[str]:
    values = [str(item.get("jibun") or ""), str(item.get("land_category") or ""), str(item.get("id") or ""), str(item.get("pnu") or "")]
    for value in (item.get("properties") or {}).values():
        if isinstance(value, (str, int, float)):
            values.append(str(value))
    return values


def _extract_lots(value: Any) -> List[str]:
    return re.findall(r"산?\d+(?:-\d+)?", _normalize_plain(value))


def _normalize_lot_value(value: Any) -> str:
    lots = _extract_lots(value)
    return lots[-1] if lots else ""


def _normalize_plain(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).lower())


def _is_development_candidate(item: Dict[str, Any]) -> bool:
    if item.get("parcel_role") == "development_candidate":
        return True
    text = " ".join(_parcel_text_values(item))
    if any(keyword in text for keyword in ["구거", "도로", "하천", "제방", "유지", "철도", "공원", "묘지"]):
        return False
    return any(keyword in text for keyword in [" 대", "전", "답", "임", "임야", "잡종지", "공장용지", "창고용지"])


def _dedupe_prepared(items: List[Dict[str, Any]], anchor: Dict[str, float]) -> List[Dict[str, Any]]:
    prepared = []
    for item in items:
        if item:
            prepared.append(parcel._prepare_anchor_parcel(item, anchor))
    return parcel._dedupe_parcels(prepared)


def _area_m2(item: Dict[str, Any]) -> float:
    try:
        return float((item or {}).get("area_m2") or 0)
    except Exception:
        return 0.0


def _distance(item: Dict[str, Any]) -> float:
    try:
        value = item.get("anchor_distance_m")
        return float(value if value is not None else 999999)
    except Exception:
        return 999999.0


def _relationship_to_main(main: Dict[str, Any], item: Dict[str, Any]) -> str:
    distance = parcel.parcel_distance_m(main.get("polygon") or [], item.get("polygon") or [])
    if distance is None:
        return "수동확인"
    if distance <= 1:
        return "접함"
    if distance <= 30:
        return "인접"
    return "이격"


def _round(value: Any) -> Any:
    return None if value is None else round(float(value), 1)


def _lookup_failed_message(message: str) -> str:
    base = "연속지적도 필지조회 실패 / VWORLD_DOMAIN 또는 필지 레이어 응답 없음"
    return f"{base}: {message}" if message else base


def _caller_address() -> str:
    frame = inspect.currentframe()
    frame = frame.f_back if frame else None
    while frame:
        address = frame.f_locals.get("address")
        if address:
            return str(address)
        payload = frame.f_locals.get("payload")
        payload_address = getattr(payload, "address", None)
        if payload_address:
            return str(payload_address)
        frame = frame.f_back
    return ""
