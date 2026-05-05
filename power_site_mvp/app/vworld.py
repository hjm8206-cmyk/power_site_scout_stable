from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import geometry


VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
DEFAULT_DOMAIN = "http://localhost:8501"

ZONING_LAYERS = [
    ("LT_C_UQ111", "도시지역"),
    ("LT_C_UQ112", "관리지역"),
    ("LT_C_UQ113", "농림지역"),
    ("LT_C_UQ114", "자연환경보전지역"),
]

REGULATION_TARGETS = [
    {
        "key": "greenbelt",
        "label": "개발제한구역",
        "layers": ["LT_C_UD801", "lt_c_ud801"],
        "keywords": ["개발제한구역", "개발제한"],
    },
    {
        "key": "water_source_protection",
        "label": "상수원보호구역",
        "layers": [],
        "keywords": ["상수원보호구역", "상수원보호"],
    },
    {"key": "waterside_zone", "label": "수변구역", "layers": [], "keywords": ["수변구역"]},
    {
        "key": "paldang_daecheong_special",
        "label": "팔당/대청호 특별대책지역",
        "layers": [],
        "keywords": ["팔당", "대청호", "특별대책지역"],
    },
    {"key": "conservation_mountain", "label": "보전산지", "layers": [], "keywords": ["보전산지"]},
    {"key": "public_mountain", "label": "공익용산지", "layers": [], "keywords": ["공익용산지"]},
    {
        "key": "agricultural_promotion",
        "label": "농업진흥지역",
        "layers": ["LT_C_AGRIXUE101", "lt_c_agrixue101"],
        "keywords": ["농업진흥지역", "농업진흥"],
    },
    {
        "key": "cultural_heritage",
        "label": "문화재보호구역",
        "layers": ["LT_C_UO301", "lt_c_uo301"],
        "keywords": ["문화재보호구역", "문화재보호", "문화재"],
    },
    {"key": "military_protection", "label": "군사시설보호구역", "layers": [], "keywords": ["군사시설보호구역", "군사시설보호"]},
    {"key": "river_area", "label": "하천구역", "layers": ["LT_C_WKMSTRM", "lt_c_wkmstrm"], "keywords": ["하천구역"]},
    {"key": "flood_management", "label": "홍수관리구역", "layers": [], "keywords": ["홍수관리구역", "홍수관리"]},
    {
        "key": "development_permit_restricted",
        "label": "개발행위허가제한지역",
        "layers": ["LT_C_UPISUQ171", "lt_c_upisuq171"],
        "keywords": ["개발행위허가제한지역", "개발행위허가제한"],
    },
]

BUILDING_DENSITY_NOTICE = (
    "민가밀집 기본점수는 500m 이내 주거노출지수 또는 건물 수를 기준으로 산정합니다. "
    "건물 수와 용도는 실제 민가 수와 다를 수 있으므로 현장확인이 필요합니다."
)


def debug_enabled() -> bool:
    return os.getenv("DEBUG_VWORLD", "").strip().lower() in {"1", "true", "yes", "on"}


def service_domain() -> str:
    explicit = os.getenv("VWORLD_DOMAIN", "").strip()
    if explicit:
        return _with_https_scheme(explicit)

    public_url = os.getenv("APP_PUBLIC_URL", "").strip()
    if public_url:
        return _with_https_scheme(public_url)

    return DEFAULT_DOMAIN


def service_ids() -> Dict[str, Any]:
    return {
        "parcel": os.getenv("VWORLD_PARCEL_SERVICE_ID", "LP_PA_CBND_BUBUN"),
        "building": os.getenv("VWORLD_BUILDING_SERVICE_ID", "spbd"),
        "road": os.getenv("VWORLD_ROAD_SERVICE_ID", "upisuq151"),
        "zoning": [layer_id for layer_id, _ in ZONING_LAYERS],
        "overlay_regulations": {
            item["key"]: _regulation_layers(item)
            for item in REGULATION_TARGETS
        },
    }


def analyze_site(lat: float, lng: float) -> Dict[str, Any]:
    parcel = get_parcel_by_point(lat, lng)
    zoning = get_zoning_by_point(lat, lng)
    roads = get_roads_nearby(lat, lng, 1000)
    buildings = get_buildings_nearby(lat, lng, 3000)

    spatial = {
        "parcel": parcel,
        "zoning": zoning,
        "roads": roads,
        "buildings": buildings,
        "service_ids": service_ids(),
    }
    spatial["auto_lookup_failures"] = _failed_items(spatial)
    spatial["manual_check_items"] = _manual_check_items(spatial)
    return spatial


def query_vworld_data_layer(
    data_id: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    point: Optional[Tuple[float, float]] = None,
    geom: Optional[str] = None,
    size: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    api_key = os.getenv("VWORLD_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "data_id": data_id,
            "features": [],
            "message": "VWorld API 키 필요: .env의 VWORLD_API_KEY를 확인하세요.",
        }
    if not data_id:
        return {"ok": False, "data_id": data_id, "features": [], "message": "VWorld data id가 비어 있습니다."}

    geom_filter = geom
    if not geom_filter and point:
        lat, lng = point
        geom_filter = f"POINT({lng} {lat})"
    if not geom_filter and bbox:
        geom_filter = _box_filter(bbox)
    if not geom_filter:
        return {"ok": False, "data_id": data_id, "features": [], "message": "bbox, point, geom 중 하나가 필요합니다."}

    active_domain = service_domain()
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": data_id,
        "key": api_key,
        "domain": active_domain,
        "format": "json",
        "crs": "EPSG:4326",
        "geomFilter": geom_filter,
        "geometry": "true",
        "size": str(size),
        "page": str(page),
    }

    try:
        response = requests.get(VWORLD_DATA_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        features = _extract_features(payload)
        result: Dict[str, Any] = {
            "ok": bool(features),
            "data_id": data_id,
            "features": features,
            "message": "" if features else _vworld_message_with_domain(_response_message(payload), active_domain),
            "geom_filter": geom_filter,
            "service_domain": active_domain,
        }
        if debug_enabled():
            result["raw_response"] = _debug_payload(payload)
        return result
    except requests.RequestException as exc:
        return {
            "ok": False,
            "data_id": data_id,
            "features": [],
            "message": f"VWorld 데이터 API 호출 실패({data_id}, service_url={active_domain}): {exc}",
            "service_domain": active_domain,
        }
    except Exception as exc:
        return {
            "ok": False,
            "data_id": data_id,
            "features": [],
            "message": f"VWorld 응답 파싱 실패({data_id}, service_url={active_domain}), 수동확인 필요: {exc}",
            "service_domain": active_domain,
        }


def _with_https_scheme(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return DEFAULT_DOMAIN
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def get_parcel_by_point(lat: float, lng: float) -> Dict[str, Any]:
    data_id = os.getenv("VWORLD_PARCEL_SERVICE_ID", "LP_PA_CBND_BUBUN")
    query = query_vworld_data_layer(data_id, point=(lat, lng), size=10)
    if not query.get("features"):
        return _empty("parcel", query.get("message") or "연속지적도 조회 실패, 수동확인 필요", source=data_id, query=query)

    candidates = []
    for feature in query["features"]:
        polygon = _largest_polygon(feature.get("geometry"))
        if not polygon:
            continue
        area_m2 = geometry.polygon_area_m2(polygon)
        props = feature.get("properties") or {}
        candidates.append(
            {
                "polygon": polygon,
                "area_m2": round(area_m2, 2),
                "area_pyeong": round(geometry.area_to_pyeong(area_m2) or 0, 2),
                "centroid": geometry.centroid(polygon),
                "pnu": _first_value(props, ["pnu", "PNU"]),
                "jibun": _first_value(props, ["jibun", "JIBUN", "addr", "ADDR", "lot_no", "A1", "PNU"]),
                "land_category": _first_value(props, ["jimok", "JIMOK", "land_cat", "LAND_CAT", "A2"]) or "수동확인",
                "properties": _safe_props(props),
            }
        )

    if not candidates:
        return _empty("parcel", "연속지적도 geometry 파싱 실패, 수동확인 필요", source=data_id, query=query)

    selected = max(candidates, key=lambda item: item["area_m2"])
    selected.update(
        {
            "ok": True,
            "source": data_id,
            "data_id": data_id,
            "message": "연속지적도에서 좌표 포함 필지 후보를 조회했습니다.",
        }
    )
    _attach_debug(selected, query)
    return selected


def get_zoning_by_point(lat: float, lng: float) -> Dict[str, Any]:
    checked = []
    records = []
    failure_messages = []

    for data_id, category in ZONING_LAYERS:
        query = query_vworld_data_layer(data_id, point=(lat, lng), size=20)
        checked.append({"data_id": data_id, "label": category, "ok": bool(query.get("features"))})
        if not query.get("features"):
            if query.get("message"):
                failure_messages.append(f"{data_id}: {query['message']}")
            continue

        for feature in query["features"]:
            props = feature.get("properties") or {}
            name = _feature_name(props) or category
            record = {
                "data_id": data_id,
                "category": category,
                "name": name,
                "properties": _safe_props(props),
                "geometry": _compact_geometry(feature.get("geometry")),
            }
            records.append(record)

        first = records[0]
        names = _unique([record["name"] for record in records])
        result = {
            "ok": True,
            "source": first["data_id"],
            "data_id": first["data_id"],
            "main_zoning": first["name"],
            "main_zoning_category": first["category"],
            "management_detail": _management_detail(names),
            "names": names,
            "records": records[:20],
            "layers_checked": checked,
            "message": "용도지역 자동조회 결과를 확인했습니다.",
        }
        _attach_debug(result, query)
        return result

    return {
        "ok": False,
        "source": None,
        "main_zoning": None,
        "main_zoning_category": None,
        "management_detail": None,
        "names": [],
        "records": [],
        "layers_checked": checked,
        "message": "용도지역 자동조회 실패, 수동확인 필요",
        "debug_messages": failure_messages[:8],
    }


def get_overlay_regulations(
    lat: float,
    lng: float,
    parcel_polygon: Optional[List[Dict[str, float]]] = None,
    zoning: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context_text = _regulation_context_text(zoning or {})
    items = [
        _evaluate_regulation_target(target, lat, lng, parcel_polygon or [], context_text)
        for target in REGULATION_TARGETS
    ]
    detected = [item for item in items if item.get("detected")]
    unknown = [item for item in items if item.get("status") == "미확인"]
    greenbelt = next((item for item in items if item.get("key") == "greenbelt"), {})
    messages = []
    if greenbelt.get("detected"):
        messages.append("개발제한구역 중첩 — 대규모 데이터센터 개발 중대 제한")
    elif greenbelt.get("status") == "미확인":
        messages.append("개발제한구역 미확인: 토지이용계획확인원 확인 필요")

    return {
        "ok": True,
        "items": items,
        "detected_items": detected,
        "unknown_items": unknown,
        "detected_labels": [item["label"] for item in detected],
        "unknown_labels": [item["label"] for item in unknown],
        "greenbelt_detected": bool(greenbelt.get("detected")),
        "greenbelt_status": greenbelt.get("status") or "미확인",
        "greenbelt_overlap_ratio": greenbelt.get("overlap_ratio"),
        "greenbelt_message": greenbelt.get("message"),
        "message": " / ".join(messages) if messages else "중첩 규제구역 자동조회 결과를 확인했습니다.",
        "needs_land_use_confirmation": bool(unknown),
    }


def _evaluate_regulation_target(
    target: Dict[str, Any],
    lat: float,
    lng: float,
    parcel_polygon: List[Dict[str, float]],
    context_text: str,
) -> Dict[str, Any]:
    base = {
        "key": target["key"],
        "label": target["label"],
        "status": "미확인",
        "detected": False,
        "suspected": False,
        "source": "VWorld/토지이용계획 자동조회",
        "data_ids": _regulation_layers(target),
        "feature_count": 0,
        "overlap_ratio": None,
        "overlap_area_m2": None,
        "message": "자동 확인 레이어 응답 없음 / 토지이용계획확인원 확인 필요",
    }

    if _contains_keyword(context_text, target.get("keywords") or []):
        base.update(
            {
                "status": "해당",
                "detected": True,
                "suspected": False,
                "source": "용도지역·지구·구역 텍스트",
                "message": f"{target['label']} 키워드가 용도지역·지구·구역 텍스트에서 확인되었습니다.",
            }
        )

    layers = _regulation_layers(target)
    if not layers:
        return base

    bbox = _polygon_bbox(parcel_polygon) if parcel_polygon else None
    last_message = ""
    queried = False
    for data_id in layers:
        query = query_vworld_data_layer(data_id, bbox=bbox, point=None if bbox else (lat, lng), size=200)
        queried = True
        features = query.get("features") or []
        if not features:
            last_message = query.get("message") or last_message
            continue
        evaluated = _regulation_features_status(target, features, parcel_polygon)
        evaluated["data_ids"] = [data_id]
        return evaluated

    if base.get("detected"):
        return base
    if queried and _empty_vworld_result(last_message):
        base.update(
            {
                "status": "미해당",
                "detected": False,
                "message": f"{target['label']} 자동조회 결과 중첩 정보가 없습니다.",
            }
        )
    elif last_message:
        base["message"] = last_message
    return base


def _regulation_features_status(
    target: Dict[str, Any],
    features: List[Dict[str, Any]],
    parcel_polygon: List[Dict[str, float]],
) -> Dict[str, Any]:
    best_ratio: Optional[float] = None
    best_area: Optional[float] = None
    has_overlap = False
    ratio_unknown = False
    records = []
    for feature in features:
        props = feature.get("properties") or {}
        name = _feature_name(props) or target["label"]
        records.append({"name": name, "properties": _safe_props(props), "geometry": _compact_geometry(feature.get("geometry"))})
        if parcel_polygon:
            overlap = geometry.polygon_geojson_overlap_ratio(parcel_polygon, feature.get("geometry"))
            if overlap is None:
                ratio_unknown = True
                continue
            ratio = float(overlap.get("overlap_ratio") or 0)
            if ratio > 0:
                has_overlap = True
                best_ratio = max(best_ratio or 0, ratio)
                best_area = max(best_area or 0, float(overlap.get("overlap_area_m2") or 0))
        else:
            has_overlap = True

    status = "해당" if has_overlap else ("일부 중첩 의심" if ratio_unknown else "미해당")
    suspected = bool(ratio_unknown and not has_overlap)
    detected = status in {"해당", "일부 중첩 의심"}
    message = f"{target['label']} 중첩이 확인되었습니다."
    if status == "일부 중첩 의심":
        message = f"{target['label']} 후보 레이어가 조회됐지만 중첩비율 계산이 어려워 일부 중첩 의심으로 표시합니다."
    elif status == "미해당":
        message = f"{target['label']} 후보 레이어는 조회됐지만 선택 필지와 중첩되지 않았습니다."

    return {
        "key": target["key"],
        "label": target["label"],
        "status": status,
        "detected": detected,
        "suspected": suspected,
        "source": "VWorld 2D Data API",
        "feature_count": len(features),
        "overlap_ratio": round(best_ratio, 2) if best_ratio is not None else None,
        "overlap_area_m2": round(best_area, 2) if best_area is not None else None,
        "records": records[:8],
        "message": message,
    }


def _regulation_layers(target: Dict[str, Any]) -> List[str]:
    env_key = f"VWORLD_REGULATION_{str(target['key']).upper()}_LAYERS"
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return _unique([item.strip() for item in env_value.replace(";", ",").split(",")])
    return _unique(list(target.get("layers") or []))


def _regulation_context_text(zoning: Dict[str, Any]) -> str:
    parts = [zoning.get("main_zoning"), zoning.get("main_zoning_category"), zoning.get("management_detail")]
    parts.extend(zoning.get("names") or [])
    for record in zoning.get("records") or []:
        parts.extend([record.get("name"), record.get("category")])
        props = record.get("properties") or {}
        parts.extend(str(value) for value in props.values() if isinstance(value, (str, int, float)))
    return " ".join(str(value or "") for value in parts)


def _contains_keyword(text: str, keywords: List[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _polygon_bbox(polygon: List[Dict[str, float]]) -> Optional[Tuple[float, float, float, float]]:
    if not polygon:
        return None
    lngs = [float(point["lng"]) for point in polygon if "lng" in point]
    lats = [float(point["lat"]) for point in polygon if "lat" in point]
    if not lngs or not lats:
        return None
    return (min(lngs), min(lats), max(lngs), max(lats))


def _empty_vworld_result(message: str) -> bool:
    text = str(message or "")
    upper = text.upper()
    if not text:
        return True
    if any(token in upper for token in ["INVALID", "ERROR", "FAIL", "API KEY"]):
        return False
    if any(token in text for token in ["인증키", "오류", "실패", "존재하지"]):
        return False
    return "조회 결과 없음" in text or "status=" in text


def get_roads_nearby(lat: float, lng: float, radius_m: int) -> Dict[str, Any]:
    primary = os.getenv("VWORLD_ROAD_SERVICE_ID", "upisuq151")
    data_ids = _candidate_data_ids(primary, "LT_C_UPISUQ151")
    bbox = geometry.bbox_around(lat, lng, radius_m)
    last_message = ""

    for data_id in data_ids:
        query = query_vworld_data_layer(data_id, bbox=bbox, size=700)
        if not query.get("features"):
            last_message = query.get("message") or last_message
            continue

        candidates = []
        for feature in query["features"]:
            distance = geometry.distance_to_geojson_m(lat, lng, feature.get("geometry"))
            if distance is None or distance > radius_m:
                continue
            props = feature.get("properties") or {}
            candidates.append(
                {
                    "name": _first_value(props, ["road_name", "ROAD_NAME", "rd_nm", "RN", "DGM_NM", "A1", "name"])
                    or "도시계획도로 후보",
                    "distance_m": round(distance, 1),
                    "geometry": _compact_geometry(feature.get("geometry")),
                    "properties": _safe_props(props),
                }
            )

        candidates.sort(key=lambda item: item["distance_m"])
        nearest = candidates[0] if candidates else None
        result = {
            "ok": bool(candidates),
            "source": data_id,
            "data_id": data_id,
            "nearest": nearest,
            "nearest_road_distance_m": nearest["distance_m"] if nearest else None,
            "road_candidate_count_500m": sum(1 for item in candidates if item["distance_m"] <= 500),
            "road_candidate_count_1km": sum(1 for item in candidates if item["distance_m"] <= 1000),
            "road_access_level": _road_access_level(nearest["distance_m"] if nearest else None),
            "candidates": candidates[:30],
            "message": "도시계획도로 후보와 최근접 도로 거리를 산정했습니다."
            if candidates
            else "도시계획도로 geometry 파싱 실패, 카카오 지도상 도로 확인 필요",
        }
        _attach_debug(result, query)
        return result

    return {
        "ok": False,
        "source": primary,
        "data_id": primary,
        "nearest": None,
        "nearest_road_distance_m": None,
        "road_candidate_count_500m": None,
        "road_candidate_count_1km": None,
        "road_access_level": "수동확인",
        "candidates": [],
        "message": last_message or "도시계획도로 자동조회 실패, 카카오 지도상 도로 확인 필요",
    }


def get_buildings_nearby(lat: float, lng: float, radius_m: int) -> Dict[str, Any]:
    primary = os.getenv("VWORLD_BUILDING_SERVICE_ID", "spbd")
    data_ids = _candidate_data_ids(primary, "LT_C_SPBD")
    bbox = geometry.bbox_around(lat, lng, radius_m)
    last_message = ""

    for data_id in data_ids:
        features: List[Dict[str, Any]] = []
        raw_queries = []
        for tile_bbox in _split_bbox(bbox, divisions=2):
            query = query_vworld_data_layer(data_id, bbox=tile_bbox, size=1000)
            raw_queries.append(query)
            if query.get("features"):
                features.extend(query["features"])
            elif query.get("message"):
                last_message = query["message"]

        if not features:
            continue

        features = _dedupe_features(features)
        counts = {"150m": 0, "250m": 0, "350m": 0, "500m": 0, "1km": 0, "3km": 0}
        exposures = {"150m": 0.0, "250m": 0.0, "350m": 0.0, "500m": 0.0}
        known_use_count = 0
        candidates = []
        for feature in features:
            point = geometry.representative_point_from_geojson(feature.get("geometry"))
            if not point:
                continue
            props = feature.get("properties") or {}
            building_use = _building_use(props)
            weight = _residential_use_weight(building_use)
            distance = geometry.haversine_distance_m(lat, lng, point["lat"], point["lng"])
            weighted_exposure = weight * _residential_distance_weight(distance)
            if distance <= 3000 and building_use:
                known_use_count += 1
            if distance <= 150:
                counts["150m"] += 1
                exposures["150m"] += weighted_exposure
            if distance <= 250:
                counts["250m"] += 1
                exposures["250m"] += weighted_exposure
            if distance <= 350:
                counts["350m"] += 1
                exposures["350m"] += weighted_exposure
            if distance <= 500:
                counts["500m"] += 1
                exposures["500m"] += weighted_exposure
            if distance <= 1000:
                counts["1km"] += 1
            if distance <= 3000:
                counts["3km"] += 1
            if distance <= radius_m and len(candidates) < 1000:
                candidates.append(
                    {
                        "lat": point["lat"],
                        "lng": point["lng"],
                        "distance_m": round(distance, 1),
                        "name": _first_value(props, ["BD_NM", "buld_nm", "BULD_NM", "A1", "name"]) or "건물 후보",
                        "building_use": building_use or "용도 미상",
                        "residential_weight": weight,
                        "residential_distance_weight": _residential_distance_weight(distance),
                        "residential_exposure_weight": round(weighted_exposure, 3),
                        "properties": _safe_props(props),
                    }
                )

        if known_use_count == 0:
            exposures = {key: float(counts[key]) for key in ["150m", "250m", "350m", "500m"]}
        exposure_500m = round(exposures["500m"], 1)
        density = _residential_density(exposure_500m)
        confidence = _residential_confidence(known_use_count, counts["3km"])
        result = {
            "ok": True,
            "source": data_id,
            "data_id": data_id,
            "counts": counts,
            "density": density,
            "building_count_150m": counts["150m"],
            "building_count_250m": counts["250m"],
            "building_count_350m": counts["350m"],
            "building_count_500m": counts["500m"],
            "building_count_1km": counts["1km"],
            "building_count_3km": counts["3km"],
            "residential_exposure": {key: round(value, 1) for key, value in exposures.items()},
            "residential_exposure_150m": round(exposures["150m"], 1),
            "residential_exposure_250m": round(exposures["250m"], 1),
            "residential_exposure_350m": round(exposures["350m"], 1),
            "residential_exposure_500m": exposure_500m,
            "residential_confidence": confidence,
            "residential_density_level": density,
            "residential_density_level_500m": density,
            "candidates": candidates,
            "sampled": len(features),
            "notice": BUILDING_DENSITY_NOTICE,
            "message": "도로명주소 건물 데이터를 기반으로 반경별 건물 수와 민가밀집도를 산정했습니다.",
        }
        if debug_enabled():
            result["raw_response"] = [query.get("raw_response") for query in raw_queries if query.get("raw_response")]
        return result

    return {
        "ok": False,
        "source": primary,
        "data_id": primary,
        "counts": {"150m": None, "250m": None, "350m": None, "500m": None, "1km": None, "3km": None},
        "density": "수동확인",
        "building_count_150m": None,
        "building_count_250m": None,
        "building_count_350m": None,
        "building_count_500m": None,
        "building_count_1km": None,
        "building_count_3km": None,
        "residential_exposure": {"150m": None, "250m": None, "350m": None, "500m": None},
        "residential_exposure_150m": None,
        "residential_exposure_250m": None,
        "residential_exposure_350m": None,
        "residential_exposure_500m": None,
        "residential_confidence": "낮음",
        "residential_density_level": "수동확인",
        "residential_density_level_500m": "수동확인",
        "candidates": [],
        "notice": BUILDING_DENSITY_NOTICE,
        "message": last_message or "도로명주소 건물 자동조회 실패, 수동확인 필요",
    }


def get_parcel(lat: float, lng: float) -> Dict[str, Any]:
    return get_parcel_by_point(lat, lng)


def get_zoning(lat: float, lng: float) -> Dict[str, Any]:
    return get_zoning_by_point(lat, lng)


def get_roads(lat: float, lng: float) -> Dict[str, Any]:
    return get_roads_nearby(lat, lng, 1000)


def get_buildings(lat: float, lng: float) -> Dict[str, Any]:
    return get_buildings_nearby(lat, lng, 3000)


def _extract_features(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("features"), list):
            return payload["features"]
        feature_collection = payload.get("featureCollection")
        if isinstance(feature_collection, dict) and isinstance(feature_collection.get("features"), list):
            return feature_collection["features"]
        for value in payload.values():
            found = _extract_features(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _extract_features(value)
            if found:
                return found
    return []


def _response_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "VWorld 응답이 비어 있거나 JSON 객체가 아닙니다."
    response = payload.get("response") or {}
    error = response.get("error") or {}
    if error.get("text"):
        return str(error["text"])
    status = response.get("status")
    return f"조회 결과 없음(status={status}), 수동확인 필요"


def _vworld_message_with_domain(message: str, domain: str) -> str:
    text = str(message or "조회 결과 없음, 수동확인 필요")
    if "인증키" in text or "API KEY" in text.upper() or "INVALID" in text.upper():
        return f"{text} 현재 VWorld service_url={domain} 입니다. VWorld 콘솔의 서비스 URL과 Vercel 환경변수 VWORLD_DOMAIN을 확인하세요."
    return text


def _largest_polygon(geojson: Optional[Dict[str, Any]]) -> List[Dict[str, float]]:
    rings = geometry.polygon_rings_from_geojson(geojson)
    if not rings:
        return []
    return max(rings, key=geometry.polygon_area_m2)


def _compact_geometry(geojson: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not geojson:
        return {}
    geometry_type = geojson.get("type")
    if geometry_type in {"LineString", "MultiLineString"}:
        return {"type": "LineString", "path": geometry.flatten_geojson_points(geojson)[:300]}
    if geometry_type in {"Polygon", "MultiPolygon"}:
        return {"type": "Polygon", "path": _largest_polygon(geojson)[:300]}
    point = geometry.representative_point_from_geojson(geojson)
    return {"type": "Point", "point": point} if point else {}


def _box_filter(bbox: Tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bbox
    return f"BOX({minx},{miny},{maxx},{maxy})"


def _split_bbox(bbox: Tuple[float, float, float, float], divisions: int) -> List[Tuple[float, float, float, float]]:
    minx, miny, maxx, maxy = bbox
    x_step = (maxx - minx) / divisions
    y_step = (maxy - miny) / divisions
    tiles = []
    for x_idx in range(divisions):
        for y_idx in range(divisions):
            tiles.append(
                (
                    minx + x_step * x_idx,
                    miny + y_step * y_idx,
                    minx + x_step * (x_idx + 1),
                    miny + y_step * (y_idx + 1),
                )
            )
    return tiles


def _dedupe_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for feature in features:
        props = feature.get("properties") or {}
        point = geometry.representative_point_from_geojson(feature.get("geometry"))
        key = (
            _first_value(props, ["id", "ID", "pnu", "PNU", "bd_mgt_sn", "BD_MGT_SN", "buld_mnnm", "BULD_MNNM"]),
            round(point["lat"], 7) if point else None,
            round(point["lng"], 7) if point else None,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(feature)
    return result


def _feature_name(props: Dict[str, Any]) -> Optional[str]:
    return _first_value(
        props,
        [
            "DGM_NM",
            "dgm_nm",
            "UNAME",
            "uname",
            "ZONENAME",
            "zone_nm",
            "LCLAS_CL",
            "SCLAS_CL",
            "A1",
            "name",
        ],
    )


def _management_detail(names: List[str]) -> Optional[str]:
    joined = " ".join(names)
    for keyword in ["보전관리지역", "생산관리지역", "계획관리지역"]:
        if keyword in joined:
            return keyword
    return None


def _road_access_level(distance_m: Optional[float]) -> str:
    if distance_m is None:
        return "수동확인"
    if distance_m <= 50:
        return "좋음"
    if distance_m <= 200:
        return "보통"
    return "나쁨"


def _residential_density(value_500m: Optional[float]) -> str:
    if value_500m is None:
        return "수동확인"
    if value_500m <= 30:
        return "낮음"
    if value_500m <= 70:
        return "보통"
    if value_500m <= 150:
        return "주의"
    if value_500m <= 300:
        return "높음"
    if value_500m <= 500:
        return "매우 높음"
    return "과밀"


def _building_use(props: Dict[str, Any]) -> str:
    value = _first_value(
        props,
        [
            "MAIN_PURPS_CD_NM",
            "main_purps_cd_nm",
            "ETC_PURPS",
            "etc_purps",
            "PURPS",
            "purps",
            "USE_NM",
            "use_nm",
            "BDTYP_CD_NM",
            "bdtyp_cd_nm",
            "A5",
            "A6",
        ],
    )
    return str(value or "").strip()


def _residential_use_weight(building_use: str) -> float:
    text = str(building_use or "")
    if any(keyword in text for keyword in ["학교", "병원", "요양", "어린이집", "유치원", "보육", "의료"]):
        return 2.0
    if any(keyword in text for keyword in ["단독주택", "공동주택", "다가구", "다세대", "연립", "아파트"]):
        return 1.0
    if any(keyword in text for keyword in ["근린생활", "상가주택", "상업"]):
        return 0.6
    if any(keyword in text for keyword in ["공장", "업무시설"]):
        return 0.35
    if any(keyword in text for keyword in ["창고", "축사", "농업"]):
        return 0.2
    if any(keyword in text for keyword in ["종교", "공공", "교육", "문화", "기타"]):
        return 0.5
    return 0.7


def _residential_distance_weight(distance_m: Optional[float]) -> float:
    if distance_m is None:
        return 1.0
    if distance_m <= 150:
        return 2.0
    if distance_m <= 250:
        return 1.5
    if distance_m <= 350:
        return 1.2
    return 1.0


def _residential_confidence(known_use_count: int, total_count: int) -> str:
    if not total_count:
        return "낮음"
    ratio = known_use_count / max(total_count, 1)
    if ratio >= 0.7:
        return "높음"
    if ratio >= 0.3:
        return "중간"
    return "낮음"


def _candidate_data_ids(primary: str, *fallbacks: str) -> List[str]:
    return _unique([primary, *fallbacks])


def _first_value(props: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    lower = {str(key).lower(): value for key, value in props.items()}
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return props[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _safe_props(props: Dict[str, Any]) -> Dict[str, Any]:
    safe = {}
    for idx, (key, value) in enumerate(props.items()):
        if idx >= 24:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def _unique(values: List[Any]) -> List[Any]:
    seen = set()
    result = []
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _empty(kind: str, message: str, source: Optional[str] = None, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = {
        "ok": False,
        "source": source or service_ids().get(kind),
        "data_id": source or service_ids().get(kind),
        "message": message,
    }
    _attach_debug(result, query)
    return result


def _attach_debug(result: Dict[str, Any], query: Optional[Dict[str, Any]]) -> None:
    if query and debug_enabled() and "raw_response" in query:
        result["raw_response"] = query["raw_response"]


def _debug_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    return {
        "response": payload.get("response"),
        "features_count": len(_extract_features(payload)),
    }


def _failed_items(spatial: Dict[str, Any]) -> List[str]:
    labels = {
        "parcel": "연속지적도",
        "zoning": "용도지역",
        "roads": "도로",
        "buildings": "건물/민가밀집",
    }
    failures = []
    for key, label in labels.items():
        item = spatial.get(key) or {}
        if not item.get("ok"):
            failures.append(f"{label}: {item.get('message', '조회 실패, 수동확인 필요')}")
    return failures


def _manual_check_items(spatial: Dict[str, Any]) -> List[str]:
    checks = []
    if not (spatial.get("zoning") or {}).get("ok"):
        checks.append("용도지역/지구는 토지이음 또는 지자체 도시계획 자료로 확인하세요.")
    if not (spatial.get("roads") or {}).get("ok"):
        checks.append("현황도로, 사도, 도시계획도로 저촉 여부는 카카오 지도와 현장자료로 확인하세요.")
    if not (spatial.get("buildings") or {}).get("ok"):
        checks.append("민가밀집도는 건축물대장, 항공사진, 현장조사로 보완하세요.")
    checks.append("송전탑/송전선은 자동조회하지 않으며 위성지도에서 수동 마킹해야 합니다.")
    return checks
