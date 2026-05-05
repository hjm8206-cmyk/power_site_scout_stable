from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import geometry


ROAD_NOTICE = (
    "도로폭은 공식 공간정보 및 위성지도 기반 1차 추정값이며, 실제 공사차량 진입 가능성은 "
    "현장확인, 지자체 도로대장, 사용승낙, 확폭 가능성 검토가 필요합니다."
)

ACCESS_NOTICE = (
    "접도 보완 가능성은 공간정보 기반 1차 분석이며, 실제 진입도로 확보 가능성은 경유 필지 권리관계, "
    "지자체 도로대장, 사용승낙, 현장 측량 및 인허가 검토를 통해 확인해야 합니다."
)


def analyze_roads(lat: float, lng: float, parcel_group: Dict[str, Any], radius_m: int = 500) -> Dict[str, Any]:
    from . import vworld

    candidates: List[Dict[str, Any]] = []
    sources = [
        ("LT_C_UPISUQ151", "도시계획도로", "도시계획도로"),
        ("upisuq151", "도시계획도로", "도시계획도로"),
        ("LT_C_RNADR_MA", "도로명도로", "도로명주소 도로구간"),
    ]
    bbox = geometry.bbox_around(lat, lng, radius_m)
    last_message = ""

    main = parcel_group.get("main") or {}
    site_polygon = main.get("polygon") or []

    for data_id, road_type, source_label in sources:
        query = vworld.query_vworld_data_layer(data_id, bbox=bbox, size=500)
        if not query.get("features"):
            last_message = query.get("message") or last_message
            continue
        for feature in query["features"]:
            anchor_distance = geometry.distance_to_geojson_m(lat, lng, feature.get("geometry"))
            if anchor_distance is None or anchor_distance > radius_m:
                continue
            props = feature.get("properties") or {}
            width = parse_width(props)
            width_class = classify_width(width)
            compact = compact_geometry(feature.get("geometry"))
            site_distance = distance_site_to_compact(site_polygon, compact)
            distance = site_distance if site_distance is not None else anchor_distance
            candidates.append(
                {
                    "name": first_value(props, ["road_name", "ROAD_NAME", "rd_nm", "RN", "DGM_NM", "A1", "name"])
                    or road_type,
                    "distance_m": round(distance, 1),
                    "anchor_distance_m": round(anchor_distance, 1),
                    "site_distance_m": round(site_distance, 1) if site_distance is not None else None,
                    "road_type": road_type,
                    "official_width_m": width,
                    "estimated_width_m": None,
                    "width_class": width_class,
                    "road_confidence": "높음" if width else "중간",
                    "road_source": source_label,
                    "geometry": compact,
                    "style": road_style(road_type, width_class),
                    "properties": safe_props(props),
                }
            )

    candidates.extend(cadastral_road_candidates(parcel_group, site_polygon, radius_m))
    candidates = dedupe_road_candidates(candidates)
    candidates.sort(key=lambda item: item["distance_m"])
    nearest = candidates[0] if candidates else fallback_unconfirmed(parcel_group, last_message)
    access_path = analyze_access_path(parcel_group, candidates)
    access = classify_access(nearest, access_path)
    final_width = nearest.get("width_class") or "폭원 미확인"

    return {
        "ok": bool(candidates),
        "search_radius_m": radius_m,
        "nearest": nearest,
        "nearest_road_distance_m": nearest.get("distance_m"),
        "nearest_road_type": nearest.get("road_type"),
        "official_width_m": nearest.get("official_width_m"),
        "estimated_width_m": nearest.get("estimated_width_m"),
        "width_class": nearest.get("width_class"),
        "final_width_class": final_width,
        "manual_override_width_class": None,
        "road_access_level": access,
        "road_confidence": nearest.get("road_confidence"),
        "road_source": nearest.get("road_source"),
        "road_candidate_count_500m": sum(1 for item in candidates if item["distance_m"] <= 500),
        "candidates": candidates[:40],
        "access_path": access_path,
        "notice": ROAD_NOTICE,
        "access_notice": ACCESS_NOTICE,
        "message": "500m 내 도로 후보, 폭원, 접근등급을 산정했습니다."
        if candidates
        else "500m 내 도로 자동조회 실패, 접도 수동확인 필요",
    }


def apply_manual_corrections(roads: Dict[str, Any], manual: Any) -> Dict[str, Any]:
    corrected = dict(roads or {})
    access_path = dict(corrected.get("access_path") or {})
    manual_width = None

    if getattr(manual, "actual_road_10m", False):
        manual_width = "10m 이상"
        corrected.update({"final_width_class": manual_width, "road_access_level": "A", "road_confidence": "수동확인"})
        access_path.update({"grade": "A", "method": "수동보정 직접 접도", "manual_override": True})
    elif getattr(manual, "actual_road_6m", False):
        manual_width = "6m 이상 10m 미만"
        corrected.update({"final_width_class": manual_width, "road_access_level": "B", "road_confidence": "수동확인"})
        access_path.update({"grade": "B", "method": "수동보정 직접 접도", "manual_override": True})
    elif getattr(manual, "actual_road_4m", False):
        manual_width = "4m 이상 6m 미만"
        corrected.update({"final_width_class": manual_width, "road_access_level": "D", "road_confidence": "수동확인"})
        access_path.update({"grade": "D", "method": "수동보정 4m 이상 도로", "manual_override": True})
    elif getattr(manual, "construction_access_difficult", False):
        manual_width = "협소·장거리 진입로"
        corrected.update(
            {
                "final_width_class": manual_width,
                "road_access_level": "F",
                "road_confidence": "수동확인",
                "construction_access_difficult_manual": True,
            }
        )
        access_path.update(
            {
                "grade": "F",
                "method": "공사차량 진입 곤란 수동확인",
                "manual_override": True,
                "construction_access_difficult": True,
            }
        )

    corrected["manual_override_width_class"] = manual_width
    corrected["access_path"] = access_path
    return corrected


def parse_width(props: Dict[str, Any]) -> Optional[float]:
    for key in ["width", "WIDTH", "rd_width", "ROAD_BT", "WID", "rw", "road_wid", "WDR_RD"]:
        value = props.get(key)
        try:
            if value not in (None, ""):
                return float(str(value).replace("m", "").strip())
        except ValueError:
            continue
    return None


def classify_width(width_m: Optional[float]) -> str:
    if width_m is None:
        return "폭원 미확인"
    if width_m >= 10:
        return "10m 이상"
    if width_m >= 6:
        return "6m 이상 10m 미만"
    if width_m >= 4:
        return "4m 이상 6m 미만"
    return "4m 미만"


def classify_access(road: Dict[str, Any], access_path: Dict[str, Any]) -> str:
    grade = access_path.get("grade")
    if grade in {"A", "B", "C", "D", "E", "F"}:
        return grade
    road_type = road.get("road_type")
    if road_type in {"농로추정", "임도추정"}:
        return "E"
    return "F"


def analyze_access_path(parcel_group: Dict[str, Any], roads: List[Dict[str, Any]]) -> Dict[str, Any]:
    adjacent = list(parcel_group.get("adjacent") or [])
    if not roads:
        return {
            "method": "접도 불명확",
            "grade": "F",
            "via_parcels": [],
            "road_contact_point": None,
            "message": "500m 내 도로 연결 구조를 확인하지 못했습니다.",
        }

    nearest = roads[0]
    distance = nearest.get("distance_m")
    width_rank = _width_rank(nearest.get("width_class"))
    road_type = nearest.get("road_type")

    if distance is not None and distance <= 5:
        if width_rank >= 10 and road_type in {"공식도로", "도로명도로"}:
            grade = "A"
        elif width_rank >= 6:
            grade = "B"
        elif width_rank >= 4:
            grade = "D"
        elif road_type in {"공식도로", "도로명도로", "지적도 도로필지", "도시계획도로"}:
            grade = "D"
        else:
            grade = "E"
        return {
            "method": "직접 접도",
            "grade": grade,
            "via_parcels": [],
            "road_contact_point": _road_contact_point(nearest),
            "message": "메인 필지 또는 부지군이 도로에 직접 접한 것으로 추정됩니다.",
        }

    close_adjacent = sorted(
        [item for item in adjacent if float(item.get("distance_from_main_m") or 9999) <= 200],
        key=lambda item: (float(item.get("distance_from_main_m") or 9999), -float(item.get("area_m2") or 0)),
    )
    if close_adjacent and distance is not None:
        if distance <= 30 and width_rank == 0 and road_type in {"지적도 도로필지", "공식도로", "도로명도로", "도시계획도로"}:
            return _via_result("1필지 경유 접도", "D", close_adjacent[:1], nearest)
        if distance <= 50 and width_rank >= 6:
            return _via_result("1필지 경유 접도", "C", close_adjacent[:1], nearest)
        if distance <= 80 and width_rank >= 4:
            return _via_result("1필지 경유 접도", "D", close_adjacent[:1], nearest)
        if distance <= 120 and width_rank >= 6:
            return _via_result("2필지 경유 접도", "D", close_adjacent[:2], nearest)
        if distance <= 160 and width_rank >= 4:
            return _via_result("2필지 경유 접도", "D", close_adjacent[:2], nearest)
        if distance <= 200 and width_rank >= 4:
            return _via_result("3필지 경유 접도", "E", close_adjacent[:3], nearest)

    return {
        "method": "접도 불명확",
        "grade": "F",
        "via_parcels": [],
        "road_contact_point": None,
        "message": "500m 내 도로 연결 구조 확인이 불가합니다.",
    }


def cadastral_road_candidates(parcel_group: Dict[str, Any], site_polygon: List[Dict[str, float]], radius_m: int) -> List[Dict[str, Any]]:
    parcels = [parcel_group.get("main") or {}, *(parcel_group.get("adjacent") or []), *(parcel_group.get("nearby_parcels") or [])]
    results: List[Dict[str, Any]] = []
    seen = set()
    for parcel in parcels:
        code = str(parcel.get("id") or parcel.get("pnu") or parcel.get("jibun") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        land = str(parcel.get("land_category") or "")
        if parcel.get("parcel_role") != "access_candidate" and "도로" not in land:
            continue
        polygon = parcel.get("polygon") or []
        if not polygon:
            continue
        distance = polygon_distance_m(site_polygon, polygon)
        if distance is None:
            distance = float(parcel.get("distance_from_main_m") or parcel.get("anchor_distance_m") or 999999)
        if distance > radius_m:
            continue
        estimated_width = estimate_road_parcel_width_m(polygon)
        width_class = classify_width(estimated_width)
        if width_class == "폭원 미확인" and distance <= 5:
            width_class = "4m 이상 6m 미만"
        results.append(
            {
                "name": parcel.get("jibun") or parcel.get("land_category") or "지적도 도로필지",
                "distance_m": round(distance, 1),
                "anchor_distance_m": parcel.get("anchor_distance_m"),
                "site_distance_m": round(distance, 1),
                "road_type": "지적도 도로필지",
                "official_width_m": None,
                "estimated_width_m": round(estimated_width, 1) if estimated_width else None,
                "width_class": width_class,
                "road_confidence": "중간" if estimated_width else "중간(지적도 도로필지)",
                "road_source": "연속지적도 지목=도로",
                "geometry": {"type": "Polygon", "path": polygon[:300]},
                "style": road_style("공식도로", width_class),
                "properties": {"land_category": land, "parcel_id": code},
            }
        )
    return results


def dedupe_road_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in candidates:
        geom = item.get("geometry") or {}
        point = geom.get("point") or ((geom.get("path") or [{}])[0] if geom.get("path") else {})
        key = (
            str(item.get("road_type")),
            round(float(item.get("distance_m") or 0), 1),
            round(float(point.get("lat") or 0), 5),
            round(float(point.get("lng") or 0), 5),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def distance_site_to_compact(site_polygon: List[Dict[str, float]], compact: Dict[str, Any]) -> Optional[float]:
    if not site_polygon or not compact:
        return None
    if compact.get("type") == "LineString":
        return geometry.distance_polygon_to_line_m(site_polygon, compact.get("path") or [])
    if compact.get("type") == "Polygon":
        return polygon_distance_m(site_polygon, compact.get("path") or [])
    if compact.get("type") == "Point" and compact.get("point"):
        return geometry.distance_point_to_polygon_m(compact["point"], site_polygon)
    return None


def polygon_distance_m(a: List[Dict[str, float]], b: List[Dict[str, float]]) -> Optional[float]:
    if len(a) < 3 or len(b) < 3:
        return None
    try:
        from shapely.geometry import Polygon

        poly_a = Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in a])
        poly_b = Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in b])
        return float(poly_a.distance(poly_b))
    except Exception:
        distances = [geometry.distance_point_to_polygon_m(point, b) for point in a]
        distances += [geometry.distance_point_to_polygon_m(point, a) for point in b]
        distances = [value for value in distances if value is not None]
        return min(distances) if distances else None


def estimate_road_parcel_width_m(polygon: List[Dict[str, float]]) -> Optional[float]:
    if len(polygon) < 3:
        return None
    area = geometry.polygon_area_m2(polygon)
    if area <= 0:
        return None
    xs = []
    ys = []
    origin = polygon[0]
    for point in polygon:
        x, y = geometry._local_xy(point["lng"], point["lat"], origin["lat"], origin["lng"])
        xs.append(x)
        ys.append(y)
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    long_side = max(span_x, span_y)
    if long_side <= 0:
        return None
    width = area / long_side
    if width <= 0 or width > 40:
        return None
    return width


def fallback_unconfirmed(parcel_group: Dict[str, Any], message: str) -> Dict[str, Any]:
    main = parcel_group.get("main") or {}
    land = str(main.get("land_category") or "")
    road_type = "임도추정" if "임야" in land else "접도불명확"
    return {
        "name": road_type,
        "distance_m": None,
        "road_type": road_type,
        "official_width_m": None,
        "estimated_width_m": None,
        "width_class": "폭원 미확인",
        "road_confidence": "낮음",
        "road_source": "자동조회 실패",
        "geometry": {},
        "style": road_style(road_type, "폭원 미확인"),
        "message": message,
    }


def road_style(road_type: str, width_class: str) -> Dict[str, Any]:
    color = "#2563eb"
    stroke_style = "solid"
    opacity = 0.85
    if road_type == "도시계획도로":
        stroke_style = "shortdash"
    elif road_type == "농로추정":
        color = "#92400e"
        stroke_style = "shortdash"
    elif road_type == "임도추정":
        color = "#6b7280"
        stroke_style = "shortdash"
    elif road_type in {"미확인도로", "접도불명확"}:
        opacity = 0.35
    weight = {"10m 이상": 6, "6m 이상 10m 미만": 4, "4m 이상 6m 미만": 3}.get(width_class, 2)
    return {"color": color, "strokeStyle": stroke_style, "weight": weight, "opacity": opacity}


def compact_geometry(geojson: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not geojson:
        return {}
    geometry_type = geojson.get("type")
    if geometry_type in {"LineString", "MultiLineString"}:
        return {"type": "LineString", "path": geometry.flatten_geojson_points(geojson)[:300]}
    if geometry_type in {"Polygon", "MultiPolygon"}:
        rings = geometry.polygon_rings_from_geojson(geojson)
        polygon = max(rings, key=geometry.polygon_area_m2) if rings else []
        return {"type": "Polygon", "path": polygon[:300]}
    point = geometry.representative_point_from_geojson(geojson)
    return {"type": "Point", "point": point} if point else {}


def first_value(props: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    lower = {str(key).lower(): value for key, value in props.items()}
    for key in keys:
        if key in props and props[key] not in (None, ""):
            return props[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def safe_props(props: Dict[str, Any]) -> Dict[str, Any]:
    safe = {}
    for idx, (key, value) in enumerate(props.items()):
        if idx >= 24:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def _via_result(method: str, grade: str, via_parcels: List[Dict[str, Any]], nearest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "method": method,
        "grade": grade,
        "via_parcels": via_parcels,
        "road_contact_point": _road_contact_point(nearest),
        "building_risk": any(bool(item.get("has_building")) for item in via_parcels),
        "farmland_or_forest_check": any(
            "전" in str(item.get("land_category"))
            or "답" in str(item.get("land_category"))
            or "임야" in str(item.get("land_category"))
            for item in via_parcels
        ),
        "message": f"{method} 가능성을 1차 추정했습니다.",
    }


def _road_contact_point(road: Dict[str, Any]) -> Optional[Dict[str, float]]:
    compact = road.get("geometry") or {}
    if compact.get("type") == "Point":
        return compact.get("point")
    path = compact.get("path") or []
    return path[0] if path else None


def _width_rank(width_class: str | None) -> int:
    return {"10m 이상": 10, "6m 이상 10m 미만": 6, "4m 이상 6m 미만": 4, "4m 미만": 1, "농로": 1}.get(width_class or "", 0)


def build_manual_road_geometry(manual_road: Any) -> Dict[str, Any]:
    """Normalize a user-drawn road polyline into app geometry."""
    if not isinstance(manual_road, dict):
        return {"ok": False, "points": [], "length_m": 0.0}
    raw_points = manual_road.get("road_polyline") or manual_road.get("points") or []
    points: List[Dict[str, float]] = []
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        try:
            lat = float(point.get("lat"))
            lng = float(point.get("lng"))
        except (TypeError, ValueError):
            continue
        points.append({"lat": lat, "lng": lng})
    length_m = 0.0
    for a, b in zip(points, points[1:]):
        length_m += geometry.haversine_distance_m(a["lat"], a["lng"], b["lat"], b["lng"])
    width_class = _normalize_manual_width_class(manual_road.get("width_class") or manual_road.get("road_width"))
    return {
        "ok": len(points) >= 2,
        "points": points,
        "length_m": round(length_m, 1),
        "width_class": width_class,
        "source": manual_road.get("source") or "manual_road_polyline",
        "road_type": manual_road.get("road_type") or "manual_road",
        "tolerance_m": _safe_float(manual_road.get("tolerance_m"), 5.0),
    }


def calculate_manual_road_touching_parcels(
    manual_road: Any,
    main_parcel: Dict[str, Any] | None,
    selected_parcels: List[Dict[str, Any]] | None = None,
    adjacent_parcels: List[Dict[str, Any]] | None = None,
    tolerance_m: float = 5.0,
) -> Dict[str, Any]:
    road_geom = build_manual_road_geometry(manual_road)
    if not road_geom.get("ok"):
        return {**road_geom, "touching_parcels": [], "closest_distance_m": None}

    line = road_geom["points"]
    selected_parcels = list(selected_parcels or [])
    adjacent_parcels = list(adjacent_parcels or [])
    main_parcel = main_parcel or {}

    groups: List[Dict[str, Any]] = []
    if _valid_polygon(main_parcel):
        groups.append({"group": "main", "parcel": main_parcel})
    for parcel in selected_parcels:
        if _valid_polygon(parcel):
            groups.append({"group": "selected_access" if _is_access_parcel(parcel) else "selected", "parcel": parcel})
    selected_ids = {_parcel_id(item) for item in selected_parcels}
    for parcel in adjacent_parcels:
        parcel_id = _parcel_id(parcel)
        if parcel_id in selected_ids or not _valid_polygon(parcel) or not _is_access_parcel(parcel):
            continue
        groups.append({"group": "adjacent_access", "parcel": parcel})

    touching: List[Dict[str, Any]] = []
    closest_distance: Optional[float] = None
    for item in groups:
        parcel = item["parcel"]
        distance = geometry.distance_polygon_to_line_m(parcel.get("polygon") or [], line)
        if distance is None:
            continue
        rounded = round(float(distance), 2)
        closest_distance = rounded if closest_distance is None else min(closest_distance, rounded)
        if distance <= tolerance_m:
            touching.append(
                {
                    "id": _parcel_id(parcel),
                    "group": item["group"],
                    "distance_m": rounded,
                    "parcel": _parcel_ref(parcel),
                    "is_development": _is_development_selected(parcel),
                    "is_access": _is_access_parcel(parcel),
                }
            )

    return {
        **road_geom,
        "touching_parcels": touching,
        "closest_distance_m": closest_distance,
        "touching_main": any(item["group"] == "main" for item in touching),
        "touching_selected": any(item["group"] == "selected" for item in touching),
        "touching_access": any(item["group"] in {"selected_access", "adjacent_access"} for item in touching),
    }


def calculate_road_connection_type_from_manual_road(
    manual_road: Any,
    main_parcel: Dict[str, Any] | None,
    selected_parcels: List[Dict[str, Any]] | None = None,
    adjacent_parcels: List[Dict[str, Any]] | None = None,
    tolerance_m: float = 5.0,
) -> Dict[str, Any]:
    touch = calculate_manual_road_touching_parcels(
        manual_road, main_parcel, selected_parcels, adjacent_parcels, tolerance_m
    )
    if not touch.get("ok"):
        return {**touch, "road_connection_type": "수동도로 없음", "connection_penalty": 15, "grade": "F"}

    touching = touch.get("touching_parcels") or []
    main_parcel = main_parcel or {}
    selected_parcels = list(selected_parcels or [])
    adjacent_parcels = list(adjacent_parcels or [])

    if touch.get("touching_main"):
        return {
            **touch,
            "road_connection_type": "직접 접도",
            "connection_penalty": 0,
            "grade": _grade_for_width(touch.get("width_class")),
            "via_parcels": [],
            "selected_access_improvement": False,
        }

    selected_touch = [item for item in touching if item["group"] == "selected"]
    if selected_touch:
        parcel_refs = [_find_parcel_by_id(item["id"], selected_parcels) for item in selected_touch]
        return {
            **touch,
            "road_connection_type": "편입 후보 포함 직접 접도",
            "connection_penalty": 2,
            "grade": _grade_for_width(touch.get("width_class")),
            "via_parcels": [item for item in parcel_refs if item],
            "selected_access_improvement": True,
        }

    access_touch_ids = [item["id"] for item in touching if item["group"] in {"selected_access", "adjacent_access"}]
    if access_touch_ids:
        chain = calculate_access_parcel_chain_length(main_parcel, selected_parcels, adjacent_parcels, access_touch_ids, tolerance_m)
        if chain and chain <= 3:
            via = find_access_path_to_manual_road(main_parcel, selected_parcels, adjacent_parcels, access_touch_ids, tolerance_m)[:3]
            return {
                **touch,
                "road_connection_type": f"{chain}필지 경유 접도",
                "connection_penalty": {1: 3, 2: 5, 3: 7}.get(chain, 15),
                "grade": "C" if chain == 1 else ("D" if chain == 2 else "E"),
                "via_parcels": via,
                "selected_access_improvement": True,
            }
        return {
            **touch,
            "road_connection_type": "MVP 분석범위 초과",
            "connection_penalty": 15,
            "grade": "F",
            "via_parcels": [],
            "selected_access_improvement": False,
        }

    return {
        **touch,
        "road_connection_type": "수동도로 있음 / 부지 접도 없음",
        "connection_penalty": 15,
        "grade": "F",
        "via_parcels": [],
        "selected_access_improvement": False,
    }


def calculate_road_score_from_manual_road(
    manual_road: Any,
    main_parcel: Dict[str, Any] | None,
    selected_parcels: List[Dict[str, Any]] | None = None,
    adjacent_parcels: List[Dict[str, Any]] | None = None,
    tolerance_m: float = 5.0,
) -> Dict[str, Any]:
    connection = calculate_road_connection_type_from_manual_road(
        manual_road, main_parcel, selected_parcels, adjacent_parcels, tolerance_m
    )
    width_class = connection.get("width_class") or "폭원 미확인"
    width_base = _manual_width_base_score(width_class)
    connection_penalty = int(connection.get("connection_penalty") or 0)
    has_touch = bool(
        connection.get("touching_main") or connection.get("touching_selected") or connection.get("touching_access")
    )
    score = max(0, width_base - connection_penalty) if has_touch and width_base > 0 else 0
    touching_ids = [item.get("id") for item in connection.get("touching_parcels") or [] if item.get("id")]
    applied = bool(has_touch and score > 0)
    return {
        **connection,
        "manual_road_exists": bool(connection.get("ok")),
        "manual_road_width_class": width_class,
        "manual_road_length_m": connection.get("length_m"),
        "manual_road_touching_main_parcel": bool(connection.get("touching_main")),
        "manual_road_touching_selected_parcel": bool(connection.get("touching_selected")),
        "manual_road_touching_access_parcel": bool(connection.get("touching_access")),
        "manual_road_touching_parcel_count": len(touching_ids),
        "manual_road_touching_parcel_ids": touching_ids,
        "road_touch_distance_m": connection.get("closest_distance_m"),
        "distance_m": connection.get("closest_distance_m"),
        "road_width_base_score": width_base,
        "road_connection_penalty": connection_penalty,
        "road_score_20": round(score, 1),
        "road_score_source": "manual_road_polyline" if connection.get("ok") else "none",
        "manual_road_applied_to_score": applied,
        "method": connection.get("road_connection_type"),
        "message": _manual_road_message(applied, connection.get("road_connection_type")),
        "ok": bool(connection.get("ok")),
    }


def merge_auto_and_manual_road_scores(auto_roads: Dict[str, Any], manual_profile: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(auto_roads or {})
    if not manual_profile or not manual_profile.get("ok"):
        return merged
    merged.update(
        {
            "manual_road_profile": manual_profile,
            "final_width_class": manual_profile.get("manual_road_width_class") or merged.get("final_width_class"),
            "manual_override_width_class": manual_profile.get("manual_road_width_class"),
            "road_access_level": manual_profile.get("grade") or merged.get("road_access_level"),
            "access_path": {
                **(merged.get("access_path") or {}),
                "method": manual_profile.get("road_connection_type"),
                "grade": manual_profile.get("grade"),
                "via_parcels": manual_profile.get("via_parcels") or [],
                "manual_road": True,
                "selected_access_improvement": manual_profile.get("selected_access_improvement"),
            },
        }
    )
    return merged


def find_access_path_to_manual_road(
    main_parcel: Dict[str, Any] | None,
    selected_parcels: List[Dict[str, Any]] | None,
    adjacent_parcels: List[Dict[str, Any]] | None,
    target_ids: List[str],
    tolerance_m: float = 5.0,
) -> List[Dict[str, Any]]:
    parcels = list(selected_parcels or []) + [item for item in (adjacent_parcels or []) if _is_access_parcel(item)]
    for target_id in target_ids:
        path = _bfs_access_path(main_parcel or {}, parcels, target_id, tolerance_m)
        if path:
            return path
    return []


def calculate_access_parcel_chain_length(
    main_parcel: Dict[str, Any] | None,
    selected_parcels: List[Dict[str, Any]] | None,
    adjacent_parcels: List[Dict[str, Any]] | None,
    target_ids: List[str],
    tolerance_m: float = 5.0,
) -> Optional[int]:
    path = find_access_path_to_manual_road(main_parcel, selected_parcels, adjacent_parcels, target_ids, tolerance_m)
    return len(path) if path else None


def _bfs_access_path(
    main_parcel: Dict[str, Any],
    parcels: List[Dict[str, Any]],
    target_id: str,
    tolerance_m: float,
) -> List[Dict[str, Any]]:
    access_parcels = [item for item in parcels if _valid_polygon(item) and _is_access_parcel(item)]
    by_id = {_parcel_id(item): item for item in access_parcels}
    if target_id not in by_id or not _valid_polygon(main_parcel):
        return [by_id[target_id]] if target_id in by_id else []

    frontier: List[tuple[str, List[str]]] = []
    for parcel_id, parcel in by_id.items():
        if _polygon_distance(main_parcel, parcel) <= tolerance_m:
            frontier.append((parcel_id, [parcel_id]))
    seen = {parcel_id for parcel_id, _ in frontier}
    while frontier:
        parcel_id, path = frontier.pop(0)
        if parcel_id == target_id:
            return [by_id[item] for item in path]
        if len(path) >= 3:
            continue
        for next_id, candidate in by_id.items():
            if next_id in seen:
                continue
            if _polygon_distance(by_id[parcel_id], candidate) <= tolerance_m:
                seen.add(next_id)
                frontier.append((next_id, path + [next_id]))
    return []


def _connected_to_main(
    main_parcel: Dict[str, Any],
    parcel_id: str,
    selected_parcels: List[Dict[str, Any]],
    tolerance_m: float,
) -> bool:
    parcel = _find_parcel_by_id(parcel_id, selected_parcels)
    return bool(parcel and _valid_polygon(main_parcel) and _polygon_distance(main_parcel, parcel) <= tolerance_m)


def _find_parcel_by_id(parcel_id: str, parcels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for parcel in parcels:
        if _parcel_id(parcel) == parcel_id:
            return parcel
    return None


def _valid_polygon(parcel: Dict[str, Any]) -> bool:
    return isinstance(parcel, dict) and isinstance(parcel.get("polygon"), list) and len(parcel.get("polygon") or []) >= 3


def _polygon_distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    distance = polygon_distance_m(a.get("polygon") or [], b.get("polygon") or [])
    return float(distance) if distance is not None else 999999.0


def _parcel_id(parcel: Dict[str, Any]) -> str:
    return str(parcel.get("id") or parcel.get("pnu") or parcel.get("jibun") or parcel.get("code") or "")


def _parcel_ref(parcel: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _parcel_id(parcel),
        "land_category": parcel.get("land_category"),
        "parcel_role": parcel.get("parcel_role"),
        "selection_status": parcel.get("selection_status"),
    }


def _is_access_parcel(parcel: Dict[str, Any]) -> bool:
    status = str(parcel.get("selection_status") or "")
    return bool(
        parcel.get("road_connection_contribution")
        or parcel.get("parcel_role") == "access_candidate"
        or "도로" in status
        or "access" in status.lower()
    )


def _is_development_selected(parcel: Dict[str, Any]) -> bool:
    status = str(parcel.get("selection_status") or "")
    if _is_access_parcel(parcel):
        return False
    return bool(parcel.get("is_incorporation_candidate") or "편입" in status or parcel.get("parcel_role") == "development_candidate")


def _normalize_manual_width_class(value: Any) -> str:
    text = str(value or "").strip()
    compact = text.lower().replace(" ", "")
    if compact in {"10", "10m", "10m+", "10m이상"} or compact.startswith("10"):
        return "10m 이상"
    if compact in {"6", "6m"} or compact.startswith("6"):
        return "6m 이상 10m 미만"
    if compact in {"4", "4m"} or compact.startswith("4"):
        return "4m 이상 6m 미만"
    return "폭원 미확인"


def _manual_width_base_score(width_class: Any) -> int:
    rank = _manual_width_rank(width_class)
    if rank >= 10:
        return 20
    if rank >= 6:
        return 15
    if rank >= 4:
        return 5
    return 0


def _manual_width_rank(width_class: Any) -> int:
    text = str(width_class or "").lower().replace(" ", "")
    if text.startswith("10"):
        return 10
    if text.startswith("6"):
        return 6
    if text.startswith("4"):
        return 4
    return 0


def _grade_for_width(width_class: Any) -> str:
    rank = _manual_width_rank(width_class)
    if rank >= 10:
        return "A"
    if rank >= 6:
        return "B"
    if rank >= 4:
        return "D"
    return "F"


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _manual_road_message(applied: bool, connection_type: Any) -> str:
    if applied:
        return "수동마킹 도로가 선택 부지군 또는 도로 연결 후보 필지와 접도하여 도로점수에 반영되었습니다."
    if connection_type == "수동도로 있음 / 부지 접도 없음":
        return "수동마킹 도로가 있으나 선택 부지군과 접도하지 않아 도로점수에 반영되지 않았습니다."
    return "수동도로가 저장되지 않았거나 도로폭이 미확인이라 도로점수에 반영되지 않았습니다."
