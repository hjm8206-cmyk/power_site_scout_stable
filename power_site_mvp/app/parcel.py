from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from shapely.geometry import Point, Polygon
except Exception:  # pragma: no cover
    Point = Polygon = None

from . import geometry, vworld


PARCEL_LAYER = "LP_PA_CBND_BUBUN"
CONNECTED_DISTANCE_M = 5


def analyze_parcels(lat: float, lng: float, radius_m: int = 200) -> Dict[str, Any]:
    anchor = {"lat": lat, "lng": lng}
    hit = vworld.get_parcel_by_point(lat, lng)
    nearby, search_radius, query_message = get_anchor_based_nearby_parcels(lat, lng, radius_m=radius_m)
    if hit.get("ok"):
        hit = _prepare_anchor_parcel(hit, anchor)
        if parcel_code(hit) and not any(parcel_code(item) == parcel_code(hit) for item in nearby):
            nearby.append(hit)

    if not nearby:
        empty_main = hit if hit.get("ok") else {}
        return {
            "ok": False,
            "anchor_point": anchor,
            "main": empty_main,
            "adjacent": [],
            "nearby_parcels": [],
            "display_adjacent": [],
            "display_limit": 10,
            "search_radius_m": search_radius,
            "selected_ids": [],
            "summary": summarize_selected(empty_main, [], []),
            "nearby_parcel_table": [],
            "parcel_group_difficulty": "E",
            "parcel_group_judgement": "주소 기준점 주변 필지 자동조회에 실패했습니다.",
            "site_scenarios": {},
            "message": query_message or "필지 조회 실패, 수동확인 필요",
        }

    nearby = _dedupe_parcels([_prepare_anchor_parcel(item, anchor) for item in nearby])
    hit_code = parcel_code(hit) if hit.get("ok") else ""
    hit_parcel = next((item for item in nearby if parcel_code(item) == hit_code), None)
    root = hit_parcel or (rank_nearby_parcels_for_display(nearby)[0] if nearby else {})
    main = _recommend_main_parcel(hit_parcel, nearby)
    main_code = parcel_code(main)
    for item in nearby:
        item["role"] = "main" if parcel_code(item) == main_code else "adjacent"
        item["relationship_to_main"] = "메인" if item["role"] == "main" else _relationship_to_main(main, item)
        item["distance_from_main_m"] = 0 if item["role"] == "main" else _round_or_none(parcel_distance_m(main.get("polygon") or [], item.get("polygon") or []))
        item["is_incorporation_candidate"] = False
        item["selection_status"] = "메인 필지" if item["role"] == "main" else "검토 후보"

    displayed = get_connected_display_parcels(nearby, root or main, limit=10)
    if not displayed:
        displayed = [main] if main else []
    adjacent = [item for item in nearby if parcel_code(item) != main_code]
    display_adjacent = [item for item in displayed if parcel_code(item) != main_code]
    difficulty = calculate_parcel_group_difficulty(displayed)
    anchor_hit_non_development = bool(hit_parcel and hit_parcel.get("parcel_role") != "development_candidate")
    message = "주소가 찍힌 필지와 서로 붙어 이어지는 필지만 최대 10필지까지 표시했습니다."
    if anchor_hit_non_development:
        message = "주소 기준점이 개발부지가 아닌 필지에 위치한 것으로 보입니다. 붙어 있는 개발 후보 필지를 직접 메인으로 지정해 확인하세요."

    group = {
        "ok": True,
        "anchor_point": anchor,
        "main": main,
        "anchor_hit_parcel": hit_parcel,
        "connection_root_parcel_id": parcel_code(root),
        "anchor_hit_non_development": anchor_hit_non_development,
        "main_selection_required": anchor_hit_non_development,
        "recommended_main_parcel_id": main_code,
        "nearby_parcels": nearby[:120],
        "adjacent": adjacent[:120],
        "displayed_parcels": displayed,
        "display_adjacent": display_adjacent,
        "display_limit": 10,
        "search_radius_m": search_radius,
        "display_excluded_count": max(0, len(nearby) - len(displayed)),
        "selected_ids": [],
        "nearby_parcel_table": build_nearby_parcel_table(displayed),
        **difficulty,
        "message": message,
    }
    group["summary"] = summarize_selected(main, adjacent, [])
    group["site_scenarios"] = build_site_scenarios(group)
    return group


def parcel_from_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    polygon = _largest_polygon(feature.get("geometry"))
    if not polygon:
        return None
    props = feature.get("properties") or {}
    area_m2 = geometry.polygon_area_m2(polygon)
    code = _first_value(props, ["pnu", "PNU", "id", "ID"]) or f"parcel-{abs(hash(str(polygon[:3])))}"
    land_category = _first_value(props, ["jimok", "JIMOK", "land_cat", "LAND_CAT", "A2"]) or "수동확인"
    parcel_role = classify_parcel_role(str(land_category))
    return {
        "id": str(code),
        "pnu": _first_value(props, ["pnu", "PNU"]),
        "jibun": _first_value(props, ["jibun", "JIBUN", "addr", "ADDR", "lot_no", "A1"]),
        "land_category": land_category,
        "parcel_role": parcel_role,
        "main_parcel_is_development_candidate": parcel_role == "development_candidate",
        "polygon": polygon,
        "centroid": geometry.centroid(polygon),
        "area_m2": round(area_m2, 2),
        "area_pyeong": round(geometry.area_to_pyeong(area_m2) or 0, 2),
        "properties": _safe_props(props),
        "zoning": "수동확인 필요",
        "district": "수동확인 필요",
        "growth_management_area": None,
        "has_road_contact": "수동확인 필요",
        "nearest_road_distance_m": None,
        "has_building": False,
    }


def annotate_buildings(parcel_group: Dict[str, Any], buildings: Dict[str, Any]) -> Dict[str, Any]:
    candidates = buildings.get("candidates") or []
    for parcel in [parcel_group.get("main") or {}, *(parcel_group.get("adjacent") or [])]:
        polygon = parcel.get("polygon") or []
        parcel["has_building"] = any(point_in_polygon(item.get("lat"), item.get("lng"), polygon) for item in candidates)
    parcel_group["summary"] = summarize_selected(
        parcel_group.get("main") or {}, parcel_group.get("adjacent") or [], parcel_group.get("selected_ids") or []
    )
    return parcel_group


def prepare_display_candidates(
    parcel_group: Dict[str, Any],
    roads: Dict[str, Any],
    zoning: Dict[str, Any],
    limit: int = 10,
) -> Dict[str, Any]:
    adjacent = list(parcel_group.get("adjacent") or [])
    road_candidates = roads.get("candidates") or []
    all_parcels = [parcel_group.get("main") or {}, *adjacent]
    for parcel in all_parcels:
        nearest_distance = nearest_road_distance(parcel, road_candidates)
        parcel["nearest_road_distance_m"] = round(nearest_distance, 1) if nearest_distance is not None else None
        parcel["has_road_contact"] = nearest_distance is not None and nearest_distance <= 5
        parcel["road_connection_contribution"] = nearest_distance is not None and nearest_distance <= 100
        if zoning.get("main_zoning") and parcel.get("role") == "main":
            parcel.setdefault("zoning", zoning.get("main_zoning"))
        parcel["parcel_role"] = parcel.get("parcel_role") or classify_parcel_role(str(parcel.get("land_category") or ""))

    main = parcel_group.get("main") or {}
    existing_display_ids = [parcel_code(item) for item in parcel_group.get("displayed_parcels") or [] if parcel_code(item)]
    all_by_id = {parcel_code(item): item for item in all_parcels if parcel_code(item)}
    if existing_display_ids:
        display_all = [all_by_id[item_id] for item_id in existing_display_ids if item_id in all_by_id]
    else:
        root = next((item for item in all_parcels if parcel_code(item) == parcel_group.get("connection_root_parcel_id")), None) or main
        display_all = get_connected_display_parcels(all_parcels, root, limit=limit)
    manual_display = [
        item
        for item in adjacent
        if (item.get("role") == "manual_added" or item.get("manual_added")) and parcel_code(item) not in {parcel_code(p) for p in display_all}
    ]
    display_all = [*display_all[:limit], *manual_display]
    display = [item for item in display_all if parcel_code(item) != parcel_code(main)]
    display_ids = {item.get("id") for item in display}
    for item in adjacent:
        item["display_excluded"] = item.get("id") not in display_ids
    parcel_group["adjacent"] = adjacent
    parcel_group["displayed_parcels"] = display_all
    parcel_group["display_adjacent"] = display
    parcel_group["display_limit"] = limit
    parcel_group["display_excluded_count"] = max(0, len(all_parcels) - len(display_all))
    difficulty = calculate_parcel_group_difficulty(display_all)
    parcel_group.update(difficulty)
    parcel_group["nearby_parcel_table"] = build_nearby_parcel_table(display_all)
    parcel_group["summary"] = summarize_selected(
        parcel_group.get("main") or {}, adjacent, parcel_group.get("selected_ids") or []
    )
    parcel_group["site_scenarios"] = build_site_scenarios(parcel_group)
    return parcel_group


def summarize_selected(main: Dict[str, Any], adjacent: List[Dict[str, Any]], selected_ids: List[str]) -> Dict[str, Any]:
    selected_set = {str(item) for item in (selected_ids or []) if item is not None}
    parcels = [main] if main else []
    parcels.extend([item for item in adjacent if str(item.get("id")) in selected_set])
    parcels = [item for item in parcels if item]
    development_parcels = [
        item
        for item in parcels
        if item.get("parcel_role") == "development_candidate"
        or (
            str(item.get("id")) in selected_set
            and item.get("parcel_role") not in {"access_candidate", "constraint_parcel"}
            and item.get("selection_status") == "편입 후보"
        )
    ]
    access_parcels = [item for item in parcels if item.get("parcel_role") == "access_candidate"]
    constraint_parcels = [item for item in parcels if item.get("parcel_role") == "constraint_parcel"]
    development_area = sum(float(item.get("area_m2") or 0) for item in development_parcels)
    main_area = float((main or {}).get("area_m2") or 0)
    main_in_development_area = any(item is main for item in development_parcels)
    adjacent_area = max(0.0, development_area - (main_area if main_in_development_area else 0.0))
    total_area = main_area + adjacent_area
    categories = sorted({str(item.get("land_category") or "수동확인") for item in parcels})
    zoning_values = [str(item.get("zoning") or "") for item in parcels if item.get("zoning")]
    zoning_mix = {}
    for value in zoning_values:
        zoning_mix[value] = zoning_mix.get(value, 0) + 1
    return {
        "parcel_count": len(parcels),
        "main_area_m2": round(main_area, 2),
        "main_area_pyeong": round(geometry.area_to_pyeong(main_area) or 0, 2),
        "incorporation_area_m2": round(adjacent_area, 2),
        "incorporation_area_pyeong": round(geometry.area_to_pyeong(adjacent_area) or 0, 2),
        "total_area_m2": round(total_area, 2),
        "total_area_pyeong": round(geometry.area_to_pyeong(total_area) or 0, 2),
        "land_categories": categories,
        "has_building": any(bool(item.get("has_building")) for item in parcels),
        "building_parcel_count": sum(1 for item in parcels if bool(item.get("has_building"))),
        "road_contact_parcel_count": sum(1 for item in parcels if bool(item.get("has_road_contact"))),
        "selected_development_parcel_count": len(development_parcels),
        "selected_access_parcel_count": len(access_parcels),
        "selected_constraint_parcel_count": len(constraint_parcels),
        "main_parcel_role": (main or {}).get("parcel_role"),
        "main_parcel_is_development_candidate": (main or {}).get("parcel_role") == "development_candidate",
        "zoning_mix": zoning_mix,
        "selected_ids": list(selected_set),
    }


def selected_summary_from_analysis(analysis: Dict[str, Any], selected_ids: List[str]) -> Dict[str, Any]:
    group = analysis.get("parcel_group") or {}
    return summarize_selected(group.get("main") or analysis.get("parcel") or {}, group.get("adjacent") or [], selected_ids)


def get_anchor_based_nearby_parcels(lat: float, lng: float, radius_m: int = 200) -> tuple[List[Dict[str, Any]], int, str]:
    message = ""
    for search_radius in [radius_m, 300 if radius_m < 300 else radius_m]:
        bbox = geometry.bbox_around(lat, lng, search_radius)
        query = vworld.query_vworld_data_layer(PARCEL_LAYER, bbox=bbox, size=700)
        message = query.get("message") or message
        parcels = []
        anchor = {"lat": lat, "lng": lng}
        for feature in query.get("features") or []:
            parcel = parcel_from_feature(feature)
            if not parcel:
                continue
            distance = anchor_distance_m(anchor, parcel)
            if distance is None or distance > search_radius:
                continue
            parcel["anchor_distance_m"] = round(distance, 1)
            parcels.append(parcel)
        parcels = _dedupe_parcels(parcels)
        if len(parcels) >= 10 or search_radius >= 300:
            return parcels, search_radius, message
    return [], radius_m, message


def classify_parcel_role(land_category: str) -> str:
    text = str(land_category or "")
    if any(keyword in text for keyword in ["구거", "하천", "제방", "유지", "철도", "공원", "묘지"]):
        return "constraint_parcel"
    if any(keyword in text for keyword in ["도로", "공공용지"]):
        return "access_candidate"
    if any(keyword in text for keyword in ["대", "전", "답", "임야", "잡종", "공장", "창고"]):
        return "development_candidate"
    return "unknown"


def rank_nearby_parcels_for_display(parcels: List[Dict[str, Any]], zoning: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return sorted(parcels, key=lambda item: _display_rank(item, zoning or {}))


def get_connected_display_parcels(parcels: List[Dict[str, Any]], root: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    root_code = parcel_code(root)
    if not root_code:
        return []
    by_id = {parcel_code(item): item for item in parcels if parcel_code(item)}
    if root_code not in by_id:
        by_id[root_code] = root
    selected_codes = [root_code]
    frontier = [by_id[root_code]]

    while frontier and len(selected_codes) < limit:
        next_candidates: List[Dict[str, Any]] = []
        selected_set = set(selected_codes)
        for candidate_id, candidate in by_id.items():
            if candidate_id in selected_set:
                continue
            if any(_is_connected(front, candidate) for front in frontier):
                next_candidates.append(candidate)
        if not next_candidates:
            break
        next_candidates = sorted(next_candidates, key=lambda item: _connected_rank(item))
        next_frontier = []
        for candidate in next_candidates:
            code = parcel_code(candidate)
            if code in selected_codes:
                continue
            selected_codes.append(code)
            next_frontier.append(candidate)
            if len(selected_codes) >= limit:
                break
        frontier = next_frontier

    return [by_id[code] for code in selected_codes if code in by_id][:limit]


def detect_anchor_hit_non_development_parcel(parcel_group: Dict[str, Any]) -> bool:
    hit = parcel_group.get("anchor_hit_parcel") or {}
    return bool(hit and hit.get("parcel_role") != "development_candidate")


def recommend_main_parcel_candidates(parcel_group: Dict[str, Any]) -> List[Dict[str, Any]]:
    parcels = parcel_group.get("nearby_parcels") or []
    return [item for item in rank_nearby_parcels_for_display(parcels) if item.get("parcel_role") == "development_candidate"][:3]


def calculate_parcel_group_difficulty(parcels: List[Dict[str, Any]]) -> Dict[str, Any]:
    development = [item for item in parcels if item.get("parcel_role") == "development_candidate"]
    access = [item for item in parcels if item.get("parcel_role") == "access_candidate"]
    constraint = [item for item in parcels if item.get("parcel_role") == "constraint_parcel"]
    constrained_labels = {"구거", "도로", "하천", "제방", "유지"}
    guggeo_or_stream = [
        item for item in parcels if any(label in str(item.get("land_category") or "") for label in constrained_labels)
    ]
    dev_count = len(development)
    constraint_count = len(constraint)
    road_constraint_count = len(guggeo_or_stream)
    connected_hint = _has_connected_development_hint(development)

    if dev_count >= 1 and dev_count <= 3 and constraint_count <= 1 and connected_hint:
        grade, initial = "A", "단순"
    elif 4 <= dev_count <= 6 and constraint_count <= 2 and connected_hint:
        grade, initial = "B", "보통"
    elif dev_count >= 3 and (len(parcels) >= 7 or constraint_count <= 4):
        grade, initial = "C", "복잡"
    elif dev_count >= 1:
        grade, initial = "D", "어려움"
    else:
        grade, initial = "E", "어려움"
    if constraint_count >= max(4, len(parcels) // 2):
        grade, initial = ("E", "어려움") if dev_count <= 2 else ("D", "어려움")

    judgement = (
        f"주소 필지와 붙어 이어지는 표시 필지 기준 개발 후보 {dev_count}개, 제약/경계 {constraint_count}개, "
        f"구거·도로·하천 성격 {road_constraint_count}개로 필지군 난이도 {grade}로 판단했습니다."
    )
    return {
        "development_candidate_count": dev_count,
        "access_candidate_count": len(access),
        "constraint_parcel_count": constraint_count,
        "road_or_stream_parcel_count": road_constraint_count,
        "has_constraint_parcels": constraint_count > 0,
        "has_guggeo_or_stream": road_constraint_count > 0,
        "parcel_group_difficulty": grade,
        "parcel_group_initial_judgement": initial,
        "parcel_group_judgement": judgement,
        "parcel_compactness_score_cap_by_group_difficulty": calculate_parcel_group_difficulty_cap(grade),
    }


def calculate_parcel_group_difficulty_cap(grade: str) -> int:
    return {"A": 10, "B": 9, "C": 7, "D": 5, "E": 3}.get(str(grade or "E"), 3)


def build_nearby_parcel_table(parcels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for index, parcel in enumerate(parcels[:10], start=1):
        rows.append(
            {
                "index": index,
                "id": parcel.get("id"),
                "anchor_distance_m": parcel.get("anchor_distance_m"),
                "land_category": parcel.get("land_category"),
                "parcel_role": parcel.get("parcel_role"),
                "area_m2": parcel.get("area_m2"),
                "area_pyeong": parcel.get("area_pyeong"),
                "zoning": parcel.get("zoning"),
                "has_building": parcel.get("has_building"),
                "has_road_contact": parcel.get("has_road_contact"),
                "relationship_to_main": parcel.get("relationship_to_main"),
                "selection_status": parcel.get("selection_status") or ("메인 필지" if parcel.get("role") == "main" else "검토 후보"),
            }
        )
    return rows


def build_site_scenarios(parcel_group: Dict[str, Any]) -> Dict[str, Any]:
    displayed = parcel_group.get("displayed_parcels") or []
    main = parcel_group.get("main") or {}
    adjacent = parcel_group.get("adjacent") or []
    summary_main = summarize_selected(main, adjacent, [])
    summary_selected = parcel_group.get("summary") or summary_main
    difficulty = parcel_group.get("parcel_group_difficulty") or "E"
    return {
        "scenario_0": {
            "label": "연결 필지 구조",
            "total_area_m2": sum(float(item.get("area_m2") or 0) for item in displayed if item.get("parcel_role") == "development_candidate"),
            "development_candidate_count": parcel_group.get("development_candidate_count", 0),
            "constraint_parcel_count": parcel_group.get("constraint_parcel_count", 0),
            "road_contact": any(bool(item.get("has_road_contact")) for item in displayed),
            "parcel_group_difficulty": difficulty,
        },
        "scenario_a": {
            "label": "메인 필지만",
            "total_area_m2": summary_main.get("total_area_m2"),
            "development_candidate_count": summary_main.get("selected_development_parcel_count"),
            "constraint_parcel_count": summary_main.get("selected_constraint_parcel_count"),
            "road_contact": summary_main.get("road_contact_parcel_count", 0) > 0,
            "parcel_group_difficulty": difficulty,
        },
        "scenario_b": {
            "label": "편입 후보 포함",
            "total_area_m2": summary_selected.get("total_area_m2"),
            "development_candidate_count": summary_selected.get("selected_development_parcel_count"),
            "constraint_parcel_count": summary_selected.get("selected_constraint_parcel_count"),
            "road_contact": summary_selected.get("road_contact_parcel_count", 0) > 0,
            "parcel_group_difficulty": difficulty,
        },
    }


def parcel_code(parcel: Dict[str, Any]) -> str:
    return str(parcel.get("id") or parcel.get("pnu") or parcel.get("jibun") or "")


def anchor_distance_m(anchor: Dict[str, float], parcel: Dict[str, Any]) -> Optional[float]:
    polygon = parcel.get("polygon") or []
    if not polygon:
        return None
    if point_in_polygon(anchor.get("lat"), anchor.get("lng"), polygon):
        return 0.0
    distance = geometry.distance_point_to_polygon_m(anchor, polygon)
    if distance is not None:
        return distance
    centroid = parcel.get("centroid") or geometry.centroid(polygon)
    if centroid:
        return geometry.haversine_distance_m(anchor["lat"], anchor["lng"], centroid["lat"], centroid["lng"])
    return None


def parcel_distance_m(a: List[Dict[str, float]], b: List[Dict[str, float]]) -> Optional[float]:
    if len(a) < 3 or len(b) < 3:
        return None
    try:
        if Polygon:
            poly_a = Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in a])
            poly_b = Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in b])
            return float(poly_a.distance(poly_b))
    except Exception:
        pass
    ca = geometry.centroid(a)
    cb = geometry.centroid(b)
    if not ca or not cb:
        return None
    return geometry.haversine_distance_m(ca["lat"], ca["lng"], cb["lat"], cb["lng"])


def point_in_polygon(lat: Any, lng: Any, polygon: List[Dict[str, float]]) -> bool:
    if lat is None or lng is None or len(polygon) < 3:
        return False
    try:
        if Polygon and Point:
            poly = Polygon([(p["lng"], p["lat"]) for p in polygon])
            return bool(poly.contains(Point(float(lng), float(lat))))
    except Exception:
        return False
    return False


def nearest_road_distance(parcel: Dict[str, Any], road_candidates: List[Dict[str, Any]]) -> Optional[float]:
    centroid = parcel.get("centroid") or geometry.centroid(parcel.get("polygon") or [])
    if not centroid:
        return None
    distances = []
    for road in road_candidates:
        distance = _distance_to_compact_geometry(centroid, road.get("geometry") or {})
        if distance is not None:
            distances.append(distance)
    return min(distances) if distances else None


def _distance_to_compact_geometry(point: Dict[str, float], compact: Dict[str, Any]) -> Optional[float]:
    kind = compact.get("type")
    if kind == "LineString":
        return geometry.point_to_line_distance_m(point, compact.get("path") or [])
    if kind == "Polygon":
        return geometry.distance_point_to_polygon_m(point, compact.get("path") or [])
    if kind == "Point" and compact.get("point"):
        other = compact["point"]
        return geometry.haversine_distance_m(point["lat"], point["lng"], other["lat"], other["lng"])
    return None


def _display_rank(parcel: Dict[str, Any], zoning: Dict[str, Any]) -> tuple:
    role_score = {"development_candidate": 0, "access_candidate": 1, "unknown": 2, "constraint_parcel": 3}.get(
        str(parcel.get("parcel_role") or "unknown"),
        2,
    )
    anchor_score = float(parcel.get("anchor_distance_m") or 9999)
    relation_score = 0 if parcel.get("relationship_to_main") == "접함" else 1
    road_score = 0 if parcel.get("has_road_contact") else 1
    building_score = 0 if not parcel.get("has_building") else 1
    zoning_score = 0 if _zoning_text_score(str(parcel.get("zoning") or zoning.get("main_zoning") or "")) >= 2 else 1
    return (
        anchor_score,
        role_score,
        relation_score,
        road_score,
        building_score,
        zoning_score,
        -float(parcel.get("area_m2") or 0),
    )


def _prepare_anchor_parcel(parcel: Dict[str, Any], anchor: Dict[str, float]) -> Dict[str, Any]:
    parcel = dict(parcel)
    parcel["id"] = parcel_code(parcel) or f"parcel-{abs(hash(str(parcel.get('polygon', [])[:3])))}"
    parcel["parcel_role"] = parcel.get("parcel_role") or classify_parcel_role(str(parcel.get("land_category") or ""))
    parcel["main_parcel_is_development_candidate"] = parcel["parcel_role"] == "development_candidate"
    parcel["anchor_distance_m"] = _round_or_none(anchor_distance_m(anchor, parcel))
    parcel["relationship_to_anchor"] = "포함" if parcel.get("anchor_distance_m") == 0 else "주변"
    return parcel


def _dedupe_parcels(parcels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for parcel in parcels:
        code = parcel_code(parcel)
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(parcel)
    return result


def _recommend_main_parcel(hit_parcel: Optional[Dict[str, Any]], nearby: List[Dict[str, Any]]) -> Dict[str, Any]:
    if hit_parcel:
        return hit_parcel
    candidates = [item for item in rank_nearby_parcels_for_display(nearby) if item.get("parcel_role") == "development_candidate"]
    if candidates:
        return candidates[0]
    return hit_parcel or (rank_nearby_parcels_for_display(nearby)[0] if nearby else {})


def _relationship_to_main(main: Dict[str, Any], parcel: Dict[str, Any]) -> str:
    distance = parcel_distance_m(main.get("polygon") or [], parcel.get("polygon") or [])
    if distance is None:
        return "수동확인"
    if distance <= 1:
        return "접함"
    if distance <= 30:
        return "인접"
    return "이격"


def _is_connected(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    distance = parcel_distance_m(a.get("polygon") or [], b.get("polygon") or [])
    return distance is not None and distance <= CONNECTED_DISTANCE_M


def _connected_rank(parcel: Dict[str, Any]) -> tuple:
    role_score = {"development_candidate": 0, "access_candidate": 1, "unknown": 2, "constraint_parcel": 3}.get(
        str(parcel.get("parcel_role") or "unknown"),
        2,
    )
    return (
        role_score,
        float(parcel.get("distance_from_main_m") if parcel.get("distance_from_main_m") is not None else 9999),
        float(parcel.get("anchor_distance_m") if parcel.get("anchor_distance_m") is not None else 9999),
        -float(parcel.get("area_m2") or 0),
    )


def _ensure_main_in_display(parcels: List[Dict[str, Any]], main_code: str, limit: int) -> List[Dict[str, Any]]:
    selected = parcels[:limit]
    if main_code and not any(parcel_code(item) == main_code for item in selected):
        main = next((item for item in parcels if parcel_code(item) == main_code), None)
        if main:
            selected = [main, *selected[: max(0, limit - 1)]]
    return selected[:limit]


def _has_connected_development_hint(development: List[Dict[str, Any]]) -> bool:
    if len(development) <= 1:
        return bool(development)
    close_pairs = 0
    for idx, parcel in enumerate(development):
        for other in development[idx + 1 :]:
            distance = parcel_distance_m(parcel.get("polygon") or [], other.get("polygon") or [])
            if distance is not None and distance <= 30:
                close_pairs += 1
                break
    return close_pairs >= max(1, len(development) - 2)


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return round(value, 1) if value is not None else None


def _zoning_text_score(text: str) -> int:
    if any(keyword in text for keyword in ["계획관리", "공업", "준공업", "산업"]):
        return 3
    if any(keyword in text for keyword in ["보전관리", "생산관리", "관리지역"]):
        return 2
    if any(keyword in text for keyword in ["농림", "개발제한"]):
        return 0
    return 1


def _largest_polygon(geojson: Optional[Dict[str, Any]]) -> List[Dict[str, float]]:
    rings = geometry.polygon_rings_from_geojson(geojson)
    if not rings:
        return []
    return max(rings, key=geometry.polygon_area_m2)


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
