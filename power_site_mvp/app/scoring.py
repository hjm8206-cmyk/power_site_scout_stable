from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import geometry, parcel as parcel_tools, policy as policy_tools, road as road_tools, sensitive as sensitive_tools, slope as slope_tools
from .schemas import ManualInputs, TowerCandidate


CATEGORY_MAX = {
    "power_axis": 30,
    "road_access": 20,
    "permitting": 20,
    "residential_density": 10,
    "policy_location": 10,
    "slope": 5,
    "power_self": 5,
}

MIN_BUSINESS_AREA_PYEONG = 10000.0

OVERLAY_REGULATION_RULES = {
    "greenbelt": {"label": "개발제한구역", "penalty": 35, "decision": "원칙적 보류"},
    "water_source_protection": {"label": "상수원보호구역", "penalty": 40, "decision": "원칙적 보류"},
    "waterside_zone": {"label": "수변구역", "penalty": 25, "decision": "조건부 보류"},
    "paldang_daecheong_special": {"label": "팔당/대청호 특별대책지역", "penalty": 25, "decision": "조건부 보류"},
    "conservation_mountain": {"label": "보전산지", "penalty": 25, "decision": "조건부 보류"},
    "public_mountain": {"label": "공익용산지", "penalty": 35, "decision": "원칙적 보류"},
    "agricultural_promotion": {"label": "농업진흥지역", "penalty": 15, "decision": "조건부 보류"},
    "cultural_heritage": {"label": "문화재보호구역", "penalty": 25, "decision": "조건부 보류"},
    "military_protection": {"label": "군사시설보호구역", "penalty": 20, "decision": "조건부 보류"},
    "river_area": {"label": "하천구역", "penalty": 35, "decision": "원칙적 보류"},
    "flood_management": {"label": "홍수관리구역", "penalty": 20, "decision": "조건부 보류"},
    "development_permit_restricted": {"label": "개발행위허가제한지역", "penalty": 25, "decision": "조건부 보류"},
}

OVERLAY_DECISION_RANK = {
    "원칙적 보류": 3,
    "조건부 보류": 2,
}

AREA_REQUIREMENT_BLOCK_MESSAGES = [
    "대용량 수전형 데이터센터 검토 불가",
    "선택한 필지 총합 면적이 10,000평 미만입니다.",
    "부지제공·신설변전소·대용량 수전 기준상 최소 사업구역 면적 10,000평 이상이 필요합니다.",
    "인접 필지를 추가 선택한 후 다시 평가하세요.",
]

CATEGORY_LABELS = {
    "power_axis": "전력축 인접성",
    "road_access": "도로·접도·공사차량 진입",
    "permitting": "용도지역·토지이음 인허가 설명력",
    "residential_density": "민가밀집도",
    "policy_location": "정책입지 가·감점",
    "slope": "등고선·경사도",
    "power_self": "전력자립도",
}


def score_analysis(
    analysis: Dict[str, Any],
    manual: ManualInputs,
    towers: List[TowerCandidate] | List[Dict[str, Any]],
    selected_parcel_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    metrics = derive_metrics(analysis, towers, selected_parcel_ids or [], manual)
    area_requirement = evaluate_business_area_requirement(metrics)
    metrics.update(area_requirement)
    if not area_requirement["business_area_eligible"]:
        return _area_blocked_score(metrics, area_requirement)

    power_score, power_reason = calculate_power_axis_score(metrics, manual)
    road_score, road_reason = calculate_road_score(metrics, manual)
    permit_score, permit_reason = calculate_permit_score(metrics)
    residential_score, residential_reason = calculate_residential_base_score_10(metrics)
    policy_score, policy_reason = calculate_policy_location_score_10(metrics)
    slope_score, slope_reason = calculate_slope_score_5(metrics)
    power_self_score, power_self_reason = calculate_power_self_score_5(metrics)
    slope_missing = slope_score is None

    metrics.update(
        {
            "power_axis_score_30": power_score,
            "road_score_20": road_score,
            "permit_score_20": permit_score,
            "residential_score_10": residential_score,
            "policy_location_score_10": policy_score,
            "slope_score_5": None if slope_missing else slope_score,
            "power_self_score_5": power_self_score,
        }
    )

    categories = [
        _category("power_axis", power_score, power_reason),
        _category("road_access", road_score, road_reason),
        _category("permitting", permit_score, permit_reason),
        _category("residential_density", residential_score, residential_reason),
        _category("policy_location", policy_score, policy_reason),
        _category("slope", slope_score, slope_reason),
        _category("power_self", power_self_score, power_self_reason),
    ]

    base_score = calculate_base_score(categories)
    penalty_items = _penalty_items(metrics)
    penalty_score = calculate_penalty_score(penalty_items)
    provisional_score = max(0.0, min(100.0, round(base_score - penalty_score, 1)))
    fatal_cap, fatal_cap_reasons = calculate_fatal_cap(metrics)
    final_score = calculate_final_score(base_score, penalty_score, fatal_cap)
    grade, grade_label = _grade(final_score)
    decision_label = _decision_label(grade)
    overlay_hold_decision = metrics.get("overlay_regulation_hold_decision")
    if overlay_hold_decision:
        grade_label = f"{overlay_hold_decision} / 중첩 규제구역 확인"
        decision_label = str(overlay_hold_decision)
    elif metrics.get("greenbelt_detected") and not metrics.get("greenbelt_suspected"):
        grade_label = "원칙적 보류 / 특수해제 검토"
        decision_label = "원칙적 보류"
    elif metrics.get("greenbelt_suspected"):
        grade_label = "조건부 보류 / 토지이용계획확인원 확인 필요"
        decision_label = "보류"
    conditional_flags = list(metrics.get("conditional_flags") or [])
    if metrics.get("greenbelt_status") == "미확인":
        conditional_flags.append("개발제한구역 미확인 / 토지이용계획확인원 확인 필요")
    if slope_missing and "경사도 확인 필요" not in conditional_flags:
        conditional_flags.append("경사도 확인 필요")
    if conditional_flags and grade in {"A", "B"} and "조건부" not in grade_label:
        grade_label = f"조건부 {grade_label}"

    return {
        "base_score": base_score,
        "base_total": base_score,
        "penalty_score": penalty_score,
        "total_adjustment": -penalty_score,
        "pre_cap_total": provisional_score,
        "provisional_score": provisional_score,
        "fatal_cap": fatal_cap,
        "final_score_cap": fatal_cap,
        "fatal_cap_applied": fatal_cap is not None and final_score < provisional_score,
        "fatal_cap_reasons": fatal_cap_reasons,
        "total": final_score,
        "final_score": final_score,
        "grade": grade,
        "final_grade": grade,
        "grade_label": grade_label,
        "decision_label": decision_label,
        "conditional_flags": conditional_flags,
        "categories": categories,
        "adjustments": penalty_items,
        "penalty_items": penalty_items,
        "strengths": _strengths(categories, metrics),
        "weaknesses": _weaknesses(categories, metrics, penalty_items),
        "next_checks": _next_checks(metrics),
        "metrics": metrics,
    }


def derive_metrics(
    analysis: Dict[str, Any],
    towers: List[TowerCandidate] | List[Dict[str, Any]],
    selected_parcel_ids: List[str],
    manual: ManualInputs | None = None,
) -> Dict[str, Any]:
    center = analysis.get("center") or {}
    parcel_group = analysis.get("parcel_group") or {}
    main_parcel = parcel_group.get("main") or analysis.get("parcel") or {}
    adjacent = parcel_group.get("adjacent") or []
    roads = analysis.get("roads") or {}
    buildings = analysis.get("buildings") or {}
    places = analysis.get("places") or {}
    zoning = analysis.get("zoning") or {}
    overlay_regulations = analysis.get("overlay_regulations") or {}
    policy = analysis.get("policy") or {}
    permit = analysis.get("datacenter_permit") or {}
    growth = analysis.get("growth_management") or {}
    slope = analysis.get("slope") or {}
    manual_slope_degree = getattr(manual, "manual_slope_degree", None) if manual else None
    manual_slope_band = getattr(manual, "manual_slope_band", "auto") if manual else "auto"

    selected_set = {str(item) for item in (selected_parcel_ids or []) if item is not None}
    selected = [item for item in adjacent if str(item.get("id")) in selected_set]
    selected_road_context = _apply_selected_parcel_road_context(selected, roads)
    selected_summary = parcel_tools.summarize_selected(main_parcel, adjacent, selected_parcel_ids)
    polygon = main_parcel.get("polygon") or []
    parcel_center = geometry.centroid(polygon) if polygon else center
    tower_points = [_tower_to_dict(tower) for tower in towers]
    tower_points = [tower for tower in tower_points if _has_latlng(tower)]

    site_polygons = [
        item.get("polygon")
        for item in [main_parcel, *selected]
        if isinstance(item.get("polygon"), list) and len(item.get("polygon") or []) >= 3
    ]
    main_site_polygons = [polygon] if isinstance(polygon, list) and len(polygon) >= 3 else []
    anchor_point = parcel_group.get("anchor_point") or center
    transmission_profile = _power_axis_geometry_profile(site_polygons, anchor_point, tower_points)
    transmission_main_profile = _power_axis_geometry_profile(main_site_polygons, anchor_point, tower_points)
    power_axis_improved_by_selected = _power_axis_improved_by_selected_site(
        transmission_main_profile, transmission_profile, selected
    )
    nearest_tower_center = transmission_profile.get("nearest_tower_distance_from_anchor_m")
    nearest_tower_boundary = transmission_profile.get("nearest_tower_distance_from_site_boundary_m")
    line_distance_center = transmission_profile.get("line_distance_from_anchor_m")
    line_distance_boundary = transmission_profile.get("line_distance_from_site_boundary_m")

    counts = buildings.get("counts") or {}
    building_counts = {
        "150m": _first_number(buildings.get("building_count_150m"), counts.get("150m")),
        "250m": _first_number(buildings.get("building_count_250m"), counts.get("250m")),
        "350m": _first_number(buildings.get("building_count_350m"), counts.get("350m")),
        "500m": _first_number(buildings.get("building_count_500m"), counts.get("500m")),
        "1km": _first_number(buildings.get("building_count_1km"), counts.get("1km")),
        "3km": _first_number(buildings.get("building_count_3km"), counts.get("3km")),
    }
    residential_exposure = calculate_residential_exposure_index(buildings, building_counts)
    residential = _residential_profile(building_counts, residential_exposure)

    visual_road = _manual_visual_road_metrics(
        analysis.get("manual_road"),
        main_parcel,
        selected,
        adjacent,
        parcel_center,
        manual,
    )
    effective_access_path = _effective_access_path(roads, selected, manual, visual_road)
    residential_context = calculate_residential_cluster_sensitive_penalty(
        buildings,
        places=places,
        tower_points=tower_points,
        parcel_center=parcel_center,
        site_polygons=site_polygons,
        anchor_point=parcel_group.get("anchor_point") or center,
        effective_access_path=effective_access_path,
        residential_confidence=residential_exposure.get("confidence"),
    )
    residential_total_penalty = calculate_residential_penalty_total(
        residential.get("proximity_penalty_applied", residential.get("penalty_applied", 0)),
        residential_context.get("cluster_penalty", 0),
        residential_context.get("sensitive_facility_penalty", 0),
        residential_context.get("residential_complex_penalty", 0),
        residential_context.get("route_penalty", 0),
    )
    residential_fatal_cap = calculate_residential_fatal_cap(
        {"fatal_cap": residential.get("proximity_fatal_cap", residential.get("fatal_cap"))},
        residential_context,
    )
    land_categories = selected_summary.get("land_categories") or [main_parcel.get("land_category")]
    is_forest = any("임야" in str(value or "") for value in land_categories)

    official_adjustment = _int_or_none(
        policy.get("official_adjustment"),
        (policy.get("site_suitability") or {}).get("official_adjustment"),
    )
    policy_penalty, policy_cap = 0, None
    policy_judgement = (
        policy.get("site_judgement")
        or (policy.get("site_suitability") or {}).get("judgement")
        or policy_tools.calculate_policy_judgement(official_adjustment)
    )

    final_slope = slope_tools.resolve_final_slope_value(slope, manual_slope_band)
    slope_degree = _first_number(manual_slope_degree, final_slope.get("degree"))
    slope_raw_grade = "수동확인 필요" if manual_slope_band == "unknown" else slope.get("slope_grade")
    slope_profile = _slope_profile(slope_degree, slope_raw_grade, auto_ok=bool(slope.get("ok")))
    slope_status = slope_profile.get("status") or ("known" if slope_degree is not None else "unknown")
    power_self = policy.get("power_self_sufficiency") or {}
    power_self_score = _first_number(
        policy.get("power_self_internal_score"),
        power_self.get("internal_score"),
        2,
    )

    selected_incorporation = [
        item
        for item in selected
        if item.get("is_incorporation_candidate") or item.get("selection_status") == "편입 후보"
    ]
    selected_zoning_values = [
        str(item.get("zoning") or item.get("manual_zoning") or "").strip()
        for item in selected_incorporation
        if str(item.get("zoning") or item.get("manual_zoning") or "").strip()
    ]
    regulation_text_values = [
        item.get("label")
        for item in (overlay_regulations.get("items") or [])
        if item.get("detected") or item.get("status") == "일부 중첩 의심"
    ]
    zoning_text = _zoning_text(zoning, permit, [*selected_zoning_values, *regulation_text_values])
    zoning_entries = _zoning_evaluation_entries(main_parcel, zoning, permit, selected_incorporation)
    flags = _zoning_flags(zoning_text)
    greenbelt_status = overlay_regulations.get("greenbelt_status") or ("해당" if flags["greenbelt"] else "미확인")
    greenbelt_detected = bool(overlay_regulations.get("greenbelt_detected") or flags["greenbelt"])
    greenbelt_suspected = greenbelt_status == "일부 중첩 의심"
    overlay_profile = _overlay_regulation_profile(overlay_regulations)
    selected_development_count = selected_summary.get("selected_development_parcel_count", 0) or 0
    fragmentation = _fragmentation_profile(selected_development_count)

    return {
        "parcel_area_m2": main_parcel.get("area_m2"),
        "parcel_area_pyeong": main_parcel.get("area_pyeong"),
        "selected_summary": selected_summary,
        "selected_total_area_m2": selected_summary.get("total_area_m2"),
        "selected_total_area_pyeong": selected_summary.get("total_area_pyeong"),
        "minimum_business_area_pyeong": MIN_BUSINESS_AREA_PYEONG,
        "selected_parcel_count": len(selected_parcel_ids or []),
        "selected_development_parcel_count": selected_development_count,
        "selected_access_parcel_count": selected_summary.get("selected_access_parcel_count", 0),
        "selected_constraint_parcel_count": selected_summary.get("selected_constraint_parcel_count", 0),
        "selected_road_contact_applied": bool(selected_road_context.get("selected_road_contact_applied")),
        "selected_road_width_class": selected_road_context.get("selected_road_width_class"),
        "selected_road_distance_m": selected_road_context.get("selected_road_distance_m"),
        "selected_road_contact_parcel_ids": selected_road_context.get("selected_road_contact_parcel_ids") or [],
        "adjacent_total_count": len(adjacent),
        "anchor_point": parcel_group.get("anchor_point") or center,
        "anchor_lat": (parcel_group.get("anchor_point") or center or {}).get("lat"),
        "anchor_lng": (parcel_group.get("anchor_point") or center or {}).get("lng"),
        "nearby_parcel_count": len(parcel_group.get("nearby_parcels") or [main_parcel, *adjacent]),
        "displayed_parcel_count": len(parcel_group.get("displayed_parcels") or parcel_group.get("display_adjacent") or []),
        "development_candidate_count": parcel_group.get("development_candidate_count", 0),
        "access_candidate_count": parcel_group.get("access_candidate_count", 0),
        "constraint_parcel_count": parcel_group.get("constraint_parcel_count", 0),
        "has_constraint_parcels": parcel_group.get("has_constraint_parcels", False),
        "has_guggeo_or_stream": parcel_group.get("has_guggeo_or_stream", False),
        "parcel_group_difficulty": parcel_group.get("parcel_group_difficulty", "수동확인"),
        "parcel_group_initial_judgement": parcel_group.get("parcel_group_initial_judgement", "수동확인"),
        "parcel_group_judgement": parcel_group.get("parcel_group_judgement"),
        "parcel_compactness_score_cap_by_group_difficulty": parcel_group.get("parcel_compactness_score_cap_by_group_difficulty"),
        "main_parcel_role": main_parcel.get("parcel_role"),
        "main_parcel_is_development_candidate": main_parcel.get("parcel_role") == "development_candidate",
        "site_scenarios": parcel_group.get("site_scenarios") or {},
        "scenario_0_group_difficulty": (parcel_group.get("site_scenarios") or {}).get("scenario_0", {}).get("parcel_group_difficulty"),
        "scenario_a_main_only_score": None,
        "scenario_b_selected_site_score": None,
        "fragmentation_penalty": fragmentation["penalty"],
        "fragmentation_fatal_cap": fragmentation["fatal_cap"],
        "fragmentation_judgement": fragmentation["judgement"],
        "display_adjacent_count": len(parcel_group.get("display_adjacent") or []),
        "display_excluded_count": parcel_group.get("display_excluded_count", 0),
        "manual_added_parcel_count": sum(1 for item in adjacent if item.get("role") == "manual_added"),
        "main_land_category": main_parcel.get("land_category"),
        "is_forest": is_forest,
        "dadream_link": "https://www.forestland.go.kr/",
        "zoning_names": zoning.get("names") or [],
        "main_zoning": zoning.get("main_zoning"),
        "management_detail": zoning.get("management_detail"),
        "zoning_text": zoning_text,
        "zoning_evaluation_entries": zoning_entries,
        "overlay_regulations": overlay_regulations,
        "overlay_regulation_items": overlay_regulations.get("items") or [],
        "overlay_regulation_detected_labels": overlay_regulations.get("detected_labels") or [],
        "overlay_regulation_unknown_labels": overlay_regulations.get("unknown_labels") or [],
        "overlay_regulation_message": overlay_regulations.get("message"),
        "overlay_regulation_penalty_items": overlay_profile["penalty_items"],
        "overlay_regulation_penalty_total": overlay_profile["penalty_total"],
        "overlay_regulation_fatal_cap": overlay_profile["fatal_cap"],
        "overlay_regulation_hold_decision": overlay_profile["hold_decision"],
        "overlay_regulation_hold_reasons": overlay_profile["hold_reasons"],
        "overlay_regulation_manual_check_items": overlay_profile["manual_check_items"],
        "greenbelt_status": greenbelt_status,
        "greenbelt_detected": greenbelt_detected,
        "greenbelt_suspected": greenbelt_suspected,
        "greenbelt_overlap_ratio": overlay_regulations.get("greenbelt_overlap_ratio"),
        "is_greenbelt": greenbelt_detected,
        "is_agricultural": flags["agricultural"],
        "is_conservation_or_production": flags["conservation_or_production"],
        "growth_management_status": growth.get("status") if growth.get("ok") else None,
        "growth_management_ok": bool(growth.get("ok")),
        "zoning_confidence": "높음" if zoning.get("ok") else "낮음",
        "datacenter_permit_grade": permit.get("grade", "수동확인 필요"),
        "datacenter_permit_reason": permit.get("reason"),
        "zoning_group": permit.get("zoning_group") or permit.get("permit_group"),
        "permit_group": permit.get("permit_group") or permit.get("zoning_group"),
        "land_use_districts": permit.get("land_use_districts") or zoning.get("names") or [],
        "building_coverage_ratio": permit.get("building_coverage_ratio"),
        "floor_area_ratio": permit.get("floor_area_ratio"),
        "land_use_restriction_summary": permit.get("land_use_restriction_summary"),
        "telecom_facility_possible": permit.get("telecom_facility_possible"),
        "permit_confidence": permit.get("permit_confidence"),
        "manual_visual_road": visual_road,
        "manual_road_exists": visual_road.get("manual_road_exists", False),
        "manual_road_width_class": visual_road.get("manual_road_width_class"),
        "manual_road_length_m": visual_road.get("manual_road_length_m"),
        "manual_road_touching_main_parcel": visual_road.get("manual_road_touching_main_parcel", False),
        "manual_road_touching_selected_parcel": visual_road.get("manual_road_touching_selected_parcel", False),
        "manual_road_touching_access_parcel": visual_road.get("manual_road_touching_access_parcel", False),
        "manual_road_touching_parcel_count": visual_road.get("manual_road_touching_parcel_count", 0),
        "manual_road_touching_parcel_ids": visual_road.get("manual_road_touching_parcel_ids") or [],
        "road_touch_distance_m": visual_road.get("road_touch_distance_m"),
        "road_width_base_score": visual_road.get("road_width_base_score"),
        "road_connection_penalty": visual_road.get("road_connection_penalty"),
        "road_connection_type": visual_road.get("road_connection_type"),
        "road_score_source": visual_road.get("road_score_source") or "auto",
        "manual_road_applied_to_score": visual_road.get("manual_road_applied_to_score", False),
        "roads": roads,
        "roads_ok": bool(roads.get("ok")),
        "road_candidate_count_500m": roads.get("road_candidate_count_500m"),
        "road_distance_m": visual_road.get("distance_m") if visual_road.get("ok") else roads.get("nearest_road_distance_m"),
        "road_type": visual_road.get("road_type") if visual_road.get("ok") else roads.get("nearest_road_type"),
        "width_class": roads.get("width_class"),
        "final_width_class": (
            visual_road.get("width_class")
            if visual_road.get("ok") and visual_road.get("width_class") != "폭원 미확인"
            else effective_access_path.get("selected_road_width_class")
            or selected_road_context.get("selected_road_width_class")
            or roads.get("final_width_class")
            or roads.get("width_class")
        ),
        "manual_override_width_class": (
            visual_road.get("width_class") if visual_road.get("ok") else roads.get("manual_override_width_class")
        ),
        "construction_access_difficult_manual": bool(
            getattr(manual, "construction_access_difficult", False)
            or roads.get("construction_access_difficult_manual")
            or effective_access_path.get("construction_access_difficult")
        ),
        "road_access_level": roads.get("road_access_level"),
        "road_confidence": roads.get("road_confidence"),
        "access_path": roads.get("access_path") or {},
        "effective_access_path": effective_access_path,
        "building_counts": building_counts,
        "residential_exposure": residential_exposure["exposure"],
        "residential_exposure_index": residential_exposure["exposure"].get("500m"),
        "residential_exposure_150m": residential_exposure["exposure"].get("150m"),
        "residential_exposure_250m": residential_exposure["exposure"].get("250m"),
        "residential_exposure_350m": residential_exposure["exposure"].get("350m"),
        "residential_exposure_500m": residential_exposure["exposure"].get("500m"),
        "residential_confidence": residential_exposure["confidence"],
        "building_density": residential["level_500m"],
        "residential_density_level_500m": residential["level_500m"],
        "residential_score_10": residential["base_score"],
        "residential_base_score_10": residential["base_score"],
        "residential_penalty_150m": residential["penalty_150m"],
        "residential_penalty_250m": residential["penalty_250m"],
        "residential_penalty_350m": residential["penalty_350m"],
        "residential_penalty_500m": residential["penalty_500m"],
        "residential_proximity_penalty_applied": residential["proximity_penalty_applied"],
        "residential_penalty_radius": residential["proximity_penalty_radius"],
        "residential_cluster_penalty": residential_context.get("cluster_penalty", 0),
        "sensitive_facilities": residential_context.get("sensitive_facilities", []),
        "sensitive_detection_status": residential_context.get("sensitive_detection_status"),
        "sensitive_facility_count": residential_context.get("sensitive_facility_count", 0),
        "major_sensitive_facility_count": residential_context.get("major_sensitive_facility_count", 0),
        "reference_facility_count": residential_context.get("reference_facility_count", 0),
        "nearest_sensitive_facility_name": residential_context.get("nearest_sensitive_facility_name"),
        "nearest_sensitive_facility_type": residential_context.get("nearest_sensitive_facility_type"),
        "nearest_sensitive_facility_distance_m": residential_context.get("nearest_sensitive_facility_distance_m"),
        "nearest_major_sensitive_facility_name": residential_context.get("nearest_major_sensitive_facility_name"),
        "nearest_major_sensitive_facility_type": residential_context.get("nearest_major_sensitive_facility_type"),
        "nearest_major_sensitive_facility_distance_m": residential_context.get("nearest_major_sensitive_facility_distance_m"),
        "nearest_reference_facility_name": residential_context.get("nearest_reference_facility_name"),
        "nearest_reference_facility_type": residential_context.get("nearest_reference_facility_type"),
        "nearest_reference_facility_distance_m": residential_context.get("nearest_reference_facility_distance_m"),
        "sensitive_distance_from_anchor_m": residential_context.get("sensitive_distance_from_anchor_m"),
        "sensitive_distance_from_site_boundary_m": residential_context.get("sensitive_distance_from_site_boundary_m"),
        "sensitive_applied_distance_m": residential_context.get("sensitive_applied_distance_m"),
        "sensitive_facility_penalty_applied": residential_context.get("sensitive_facility_penalty_applied", False),
        "sensitive_facility_penalty": residential_context.get("sensitive_facility_penalty", 0),
        "residential_sensitive_facility_penalty": residential_context.get("sensitive_facility_penalty", 0),
        "sensitive_facility_fatal_cap": residential_context.get("sensitive_facility_fatal_cap"),
        "sensitive_facility_source": residential_context.get("sensitive_facility_source"),
        "sensitive_facility_confidence": residential_context.get("sensitive_facility_confidence"),
        "major_sensitive_facility_penalty": residential_context.get("major_sensitive_facility_penalty", 0),
        "reference_facility_penalty": residential_context.get("reference_facility_penalty", 0),
        "reference_facility_manual_check": residential_context.get("reference_facility_manual_check", False),
        "reference_facility_judgement": residential_context.get("reference_facility_judgement"),
        "residential_complexes": residential_context.get("residential_complexes", []),
        "residential_complex_detection_status": residential_context.get("residential_complex_detection_status"),
        "residential_complex_count": residential_context.get("residential_complex_count", 0),
        "nearest_residential_complex_name": residential_context.get("nearest_residential_complex_name"),
        "nearest_residential_complex_distance_m": residential_context.get("nearest_residential_complex_distance_m"),
        "residential_complex_penalty": residential_context.get("residential_complex_penalty", 0),
        "residential_complex_fatal_cap": residential_context.get("residential_complex_fatal_cap"),
        "residential_complex_source": residential_context.get("residential_complex_source"),
        "residential_complex_confidence": residential_context.get("residential_complex_confidence"),
        "residential_large_complex_detected": residential_context.get("residential_large_complex_detected", False),
        "residential_large_complex_reason": residential_context.get("residential_large_complex_reason"),
        "residential_large_complex_confidence": residential_context.get("residential_large_complex_confidence", "불명확"),
        "residential_large_complex_source": residential_context.get("residential_large_complex_source", "불명확"),
        "sensitive_facility_detected": residential_context.get("sensitive_facility_detected", False),
        "residential_reference_only_1km": True,
        "residential_penalty_not_applied_reason": residential_context.get("penalty_not_applied_reason")
        or residential.get("penalty_not_applied_reason"),
        "manual_residential_override_penalty": residential_context.get("manual_residential_override_penalty", 0),
        "manual_residential_override_fatal_cap": residential_context.get("manual_residential_override_fatal_cap"),
        "residential_route_penalty": residential_context.get("route_penalty", 0),
        "residential_cluster_sensitive_penalty": residential_context.get("penalty", 0),
        "residential_penalty_total": residential_total_penalty,
        "residential_penalty_applied": residential_total_penalty,
        "residential_fatal_cap": residential_fatal_cap,
        "residential_judgement": build_residential_judgement(residential, residential_context),
        "residential_penalty_judgement": residential_context.get("judgement") or residential["penalty_judgement"],
        "residential_penalty_applied_to_final_score": residential_total_penalty > 0,
        "policy": policy,
        "official_location_bonus": official_adjustment,
        "policy_location_score_10": policy.get("site_internal_score") or policy.get("internal_score"),
        "policy_penalty_modifier": policy_penalty,
        "policy_fatal_cap": policy_cap,
        "policy_judgement": policy_judgement,
        "policy_score_applied_to_total": True,
        "policy_match_status": policy.get("policy_reference_match_status")
        or ("정책입지 기준자료 자동매칭 성공" if policy.get("ok") else "정책입지 기준자료 없음 / 정책자료 업데이트 필요"),
        "slope": slope,
        "slope_degree": slope_degree,
        "slope_degree_average": slope.get("slope_degree_average") or slope.get("average_slope_degree"),
        "slope_degree_max": slope.get("slope_degree_max"),
        "slope_auto_status": slope.get("slope_auto_status") or ("자동계산 성공" if slope.get("ok") else "자동조회 실패"),
        "slope_status": slope_status,
        "slope_score_apply_method": (
            "미확인 / 점수 미반영"
            if slope_status == "unknown"
            else ("수동입력" if final_slope.get("basis") == "수동" else "자동계산")
        ),
        "slope_manual_value": final_slope.get("manual_value") or (manual_slope_degree if manual_slope_degree is not None else None),
        "slope_final_degree": slope_degree,
        "slope_apply_basis": final_slope.get("basis"),
        "slope_confidence": final_slope.get("confidence") or slope.get("slope_confidence"),
        "slope_grade": slope_profile["grade"],
        "slope_score_5": slope_profile["base_score"],
        "slope_base_score_5": slope_profile["base_score"],
        "slope_penalty": slope_profile["penalty"],
        "slope_fatal_cap": slope_profile["fatal_cap"],
        "slope_judgement": slope_profile["judgement"],
        "slope_source": final_slope.get("source") or slope.get("slope_source") or ("수동입력" if manual_slope_degree is not None else "DEM/등고선 자료 없음"),
        "power_self_sufficiency_rate": policy.get("power_self_sufficiency_rate") or power_self.get("power_self_sufficiency_rate"),
        "official_power_self_score": policy.get("official_power_self_score") or power_self.get("official_power_self_score"),
        "power_self_score_5": power_self_score,
        "power_self_internal_score": power_self_score,
        "power_self_updated_year": policy.get("power_self_updated_year") or power_self.get("updated_year"),
        "power_self_source_note": policy.get("power_self_source_note") or power_self.get("source_note"),
        "power_self_judgement": policy.get("power_self_judgement") or power_self.get("judgement"),
        "power_self_match_status": "CSV 자동매칭 성공" if power_self.get("ok") or policy.get("power_self_sufficiency_rate") is not None else "전력자립도 자료 없음 / 수동확인 필요",
        "transmission": {
            "tower_count": len(tower_points),
            "line_axis_count": 1 if len(tower_points) >= 2 else 0,
            "voltage": getattr(manual, "power_voltage", "unknown") if manual else "unknown",
            "nearest_tower_distance_from_center_m": _round_or_none(nearest_tower_center),
            "nearest_tower_distance_from_parcel_m": _round_or_none(nearest_tower_boundary),
            "line_distance_from_center_m": _round_or_none(line_distance_center),
            "line_distance_from_parcel_m": _round_or_none(line_distance_boundary),
            "best_distance_m": _round_or_none(transmission_profile.get("applied_distance_m")),
            "power_axis_relation": transmission_profile.get("relation"),
            "power_axis_relation_label": transmission_profile.get("relation_label"),
            "power_axis_distance_from_site_boundary_m": _round_or_none(
                transmission_profile.get("distance_from_site_boundary_m")
            ),
            "power_axis_main_only_distance_m": _round_or_none(transmission_main_profile.get("applied_distance_m")),
            "power_axis_selected_site_distance_m": _round_or_none(transmission_profile.get("applied_distance_m")),
            "power_axis_improved_by_added_parcel": bool(power_axis_improved_by_selected),
            "power_axis_site_polygon_count": len(site_polygons),
            "power_axis_selected_parcel_count": len(selected),
            "power_axis_distance_from_anchor_m": _round_or_none(transmission_profile.get("distance_from_anchor_m")),
            "power_axis_applied_distance_m": _round_or_none(transmission_profile.get("applied_distance_m")),
            "power_axis_distance_basis": transmission_profile.get("distance_basis"),
            "transmission_line_crosses_site": bool(transmission_profile.get("line_crosses_site")),
            "transmission_tower_inside_site": bool(transmission_profile.get("tower_inside_site")),
            "transmission_axis_boundary_touch": bool(transmission_profile.get("axis_boundary_touch")),
            "power_axis_needs_safety_review": bool(transmission_profile.get("needs_safety_review")),
        },
        "lookup_status": {
            "parcel_ok": bool(main_parcel.get("ok")),
            "zoning_ok": bool(zoning.get("ok")),
            "roads_ok": bool(roads.get("ok")),
            "buildings_ok": bool(buildings.get("ok")),
            "policy_ok": bool(policy.get("ok")),
        "slope_ok": bool(slope.get("ok")),
        "conditional_flags": ["경사도 확인 필요"] if slope_status == "unknown" else [],
        },
    }


def calculate_power_axis_score(metrics: Dict[str, Any], manual: ManualInputs | None = None) -> Tuple[float, str]:
    transmission = metrics.get("transmission") or {}
    distance = transmission.get("power_axis_applied_distance_m", transmission.get("best_distance_m"))
    relation = transmission.get("power_axis_relation") or "no_marking"
    tower_count = transmission.get("tower_count") or 0
    if not tower_count:
        location_score = 0
        voltage_score = 0
        reason = "송전탑·송전선 후보가 아직 수동마킹되지 않아 전력축 위치점수와 전압점수를 0점으로 처리했습니다."
    else:
        relation_scores = {
            "line_crosses_site": 20,
            "tower_inside_site": 20,
            "line_touches_boundary": 20,
            "tower_on_boundary": 20,
            "within_50m": 15,
            "within_150m": 10,
            "within_500m": 5,
            "over_500m": 2,
        }
        location_score = relation_scores.get(relation)
        if location_score is None:
            if distance is None:
                location_score = 0
            elif distance <= 50:
                location_score = 15
            elif distance <= 150:
                location_score = 10
            elif distance <= 500:
                location_score = 5
            else:
                location_score = 2
        voltage = getattr(manual, "power_voltage", transmission.get("voltage", "unknown")) if manual else transmission.get("voltage", "unknown")
        voltage_score = {"345kv": 10, "154kv": 10, "unknown": 4}.get(voltage, 4)
        reason = _power_axis_reason(relation, distance, transmission.get("power_axis_distance_basis"))
    power_score = min(30, location_score + voltage_score)
    transmission["distance_score"] = location_score
    transmission["location_score"] = location_score
    transmission["power_axis_location_score_20"] = location_score
    transmission["voltage_score"] = voltage_score
    transmission["power_voltage_score_10"] = voltage_score
    transmission["power_axis_score_30"] = power_score
    metrics["power_axis_location_score_20"] = location_score
    metrics["power_voltage_score_10"] = voltage_score
    metrics["power_axis_relation"] = relation
    metrics["power_axis_distance_from_site_boundary_m"] = transmission.get("power_axis_distance_from_site_boundary_m")
    metrics["power_axis_distance_from_anchor_m"] = transmission.get("power_axis_distance_from_anchor_m")
    metrics["power_axis_needs_safety_review"] = transmission.get("power_axis_needs_safety_review")
    return power_score, reason


def calculate_road_score(metrics: Dict[str, Any], manual: ManualInputs | None = None) -> Tuple[float, str]:
    if manual and getattr(manual, "construction_access_difficult", False):
        return 0, "진입도로가 협소하거나 장거리라 공사차량 진입이 어렵다고 수동확인되어 도로 점수는 0점으로 반영했습니다."
    visual = metrics.get("manual_visual_road") or {}
    if visual.get("ok"):
        return _score_visual_road(visual)
    if manual and getattr(manual, "actual_road_10m", False):
        return 20, "수동보정값 10m 이상 도로를 우선 적용했습니다."
    if manual and getattr(manual, "actual_road_6m", False):
        return 15, "수동보정값 6m 이상 도로를 우선 적용했습니다."
    if manual and getattr(manual, "actual_road_4m", False):
        return 5, "수동보정값 4m 이상 도로는 대형 공사차량 진입이 제한적인 조건으로 반영했습니다."
    if manual and getattr(manual, "farm_or_unpaved_road", False):
        return 0, "농로 또는 비포장로는 개발 진입도로로 보지 않아 도로 점수에서 제외했습니다."

    path = metrics.get("effective_access_path") or {}
    method = str(path.get("method") or "")
    grade = path.get("grade")
    width_rank = _width_rank(metrics.get("final_width_class") or metrics.get("width_class"))
    road_type = str(metrics.get("road_type") or "")
    selected_improved = bool(path.get("selected_access_improvement"))

    if selected_improved and "직접" in method:
        if width_rank >= 10:
            return 19, "편입 후보 포함 후 10m 이상 도로 직접 접도로 반영했습니다."
        if width_rank >= 6:
            return 17, "편입 후보 포함 후 6m 이상 도로 직접 접도로 반영했습니다."
    if grade == "A":
        return 20, "10m 이상 공식도로 직접 접도 기준으로 반영했습니다."
    if grade == "B":
        return 18 if width_rank >= 6 else 14, "도로 직접 접도 기준으로 반영했습니다."
    if grade == "C":
        if width_rank >= 6:
            return 15, "1필지 경유로 6m 이상 도로 연결 가능성을 반영했습니다."
        return 13, "1필지 경유로 4m 이상 도로 연결 가능성을 반영했습니다."
    if grade == "D":
        if width_rank >= 6:
            return 12, "2필지 경유로 6m 이상 도로 연결 가능성을 반영했습니다."
        return 10, "2필지 경유로 4m 이상 도로 연결 가능성을 반영했습니다."
    if grade == "E":
        if "3필지" in method:
            return 8, "3필지 경유 접도 가능성으로 반영했습니다."
        if "농로" in road_type or "농로" in method:
            return 0, "농로 또는 농로추정은 개발 진입도로로 보지 않아 도로 점수에서 제외했습니다."
        return 4, "임도추정 또는 확폭 필요 구간으로 반영했습니다."
    if "농로" in road_type:
        return 0, "농로 또는 농로추정은 개발 진입도로로 보지 않아 도로 점수에서 제외했습니다."
    if "임도" in road_type or "확폭" in method:
        return 4, "임도추정 또는 확폭 필요 구간으로 반영했습니다."
    if grade == "F":
        return 1, "접도 불명확으로 반영했습니다."
    return 0, "500m 내 도로 연결 구조 확인 불가로 반영했습니다."


def calculate_permit_score(metrics: Dict[str, Any]) -> Tuple[float, str]:
    entries = metrics.get("zoning_evaluation_entries") or [
        {
            "scope": "기준 필지",
            "parcel_id": "",
            "zoning": metrics.get("zoning_text") or "미확인",
            "area_m2": metrics.get("parcel_area_m2"),
        }
    ]
    scored_entries = []
    for entry in entries:
        score, reason = _permit_score_for_zoning_text(str(entry.get("zoning") or "미확인"))
        penalty = 25 if _contains_any(str(entry.get("zoning") or ""), ["개발제한"]) else 10 if _contains_any(str(entry.get("zoning") or ""), ["농림"]) else 0
        scored_entries.append({**entry, "score": score, "reason": reason, "penalty": penalty})

    if not scored_entries:
        scored_entries = [{"scope": "기준 필지", "parcel_id": "", "zoning": "미확인", "score": 0, "reason": "용도지역 미확인", "penalty": 0}]

    agricultural_profile = _agricultural_mix_profile(scored_entries)
    metrics.update(agricultural_profile)
    if agricultural_profile.get("agricultural_mixed_risk"):
        non_agricultural_entries = [
            item for item in scored_entries if not _contains_any(str(item.get("zoning") or ""), ["농림"])
        ]
        lowest = min(non_agricultural_entries or scored_entries, key=lambda item: float(item.get("score") or 0))
        reason = agricultural_profile.get("agricultural_mixed_judgement") or (
            "농림지역 일부 혼입은 별도 리스크 감점으로 처리하고, 주된 용도지역 점수를 통합 용도지역 점수로 적용했습니다."
        )
    else:
        lowest = min(scored_entries, key=lambda item: float(item.get("score") or 0))
        reason = str(lowest.get("reason") or "용도지역 기준 점수를 반영했습니다.")
        if agricultural_profile.get("agricultural_dominant"):
            reason = agricultural_profile.get("agricultural_dominant_judgement") or reason
    metrics["zoning_score_items"] = scored_entries
    metrics["integrated_zoning_score"] = lowest.get("score")
    metrics["integrated_zoning_reason"] = reason
    metrics["integrated_zoning_source"] = lowest.get("scope")
    metrics["integrated_zoning_parcel_id"] = lowest.get("parcel_id")

    if lowest.get("scope") != "기준 필지":
        return float(lowest.get("score") or 0), reason
    return float(lowest.get("score") or 0), reason


def _agricultural_mix_profile(scored_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_area = 0.0
    agricultural_area = 0.0
    has_agricultural = False
    has_non_agricultural = False
    non_agricultural_best_score: Optional[float] = None

    for item in scored_entries:
        zoning_text = str(item.get("zoning") or "")
        is_agricultural = _contains_any(zoning_text, ["농림"])
        area = _number(item.get("area_m2"), None)
        if is_agricultural:
            has_agricultural = True
        else:
            has_non_agricultural = True
            score = _number(item.get("score"), None)
            if score is not None:
                non_agricultural_best_score = (
                    score if non_agricultural_best_score is None else min(non_agricultural_best_score, score)
                )
        if area is None or area <= 0:
            continue
        total_area += area
        if is_agricultural:
            agricultural_area += area

    ratio = None
    if total_area > 0 and agricultural_area > 0:
        ratio = round((agricultural_area / total_area) * 100, 1)

    mixed_risk = bool(
        has_agricultural
        and has_non_agricultural
        and ratio is not None
        and ratio < 30
        and (non_agricultural_best_score is None or non_agricultural_best_score > 4)
    )
    dominant = bool(has_agricultural and (not has_non_agricultural or (ratio is not None and ratio >= 30)))

    judgement = None
    dominant_judgement = None
    if mixed_risk:
        judgement = (
            f"전체 취합면적 중 농림지역 비율이 {ratio:g}%로 30% 미만입니다. "
            "인허가 가능성이 높은 용도지역이 주된 면적을 차지하므로 기본 인허가 점수는 낮추지 않고, "
            "농림지역 혼입 리스크 감점 -10점만 별도 적용했습니다."
        )
    elif dominant:
        ratio_text = f"{ratio:g}%" if ratio is not None else "비율 미산정"
        dominant_judgement = (
            f"전체 취합면적 중 농림지역 비율이 {ratio_text}로 30% 이상이거나 농림지역이 주된 면적입니다. "
            "따라서 통합 용도지역 점수는 농림지역 기준 4 / 20점으로 적용했습니다."
        )

    return {
        "agricultural_area_m2": round(agricultural_area, 2) if agricultural_area else 0,
        "agricultural_area_ratio": ratio,
        "agricultural_mixed_risk": mixed_risk,
        "agricultural_mixed_penalty": 10 if mixed_risk else 0,
        "agricultural_mixed_judgement": judgement,
        "agricultural_dominant": dominant,
        "agricultural_dominant_judgement": dominant_judgement,
    }


def _permit_score_for_zoning_text(text: str) -> Tuple[float, str]:
    if _contains_any(text, ["개발제한"]):
        return 0, "개발제한구역은 일반적인 데이터센터 인허가 설명력이 매우 낮아 별도 해제, 도시관리계획 변경, 공공성·정책성 검토가 필요합니다."
    if _contains_any(text, ["자연환경보전", "상수원보호"]):
        return 0, "자연환경보전지역 또는 상수원보호구역은 인허가 설명력 최악 구간으로 처리했습니다."
    if _contains_any(text, ["농림"]):
        return 4, "농림지역은 낮은 점수로 보되 전력·도로·정책 조건이 우수하면 전략검토 여지를 남깁니다."
    if _contains_any(text, ["계획관리", "자연녹지", "일반공업", "준공업", "전용공업", "중심상업", "일반상업", "근린상업", "유통상업", "준주거"]):
        return 20, "계획관리지역 또는 그 이상으로 인허가 설명력이 높은 구간으로 평가했습니다."
    if _contains_any(text, ["생산관리", "보전관리", "생산녹지"]):
        return 17, "보전관리지역·생산관리지역은 데이터센터/방송통신시설 검토 가능성이 있는 구간으로 보아 검토 가능 점수로 반영했습니다."
    if _contains_any(text, ["제1종일반주거", "제2종일반주거", "제3종일반주거"]):
        return 15, "일반주거지역은 인허가 설명력이 제한적이므로 15점 구간으로 반영했습니다."
    if _contains_any(text, ["보전녹지"]):
        return 10, "보전녹지지역은 제한 가능성이 있어 중간 이하 점수로 반영했습니다."
    return 0, "용도지역 미확인 또는 자동조회 실패로 인허가 설명력 점수는 0점으로 처리했습니다."


def calculate_residential_base_score_10(metrics: Dict[str, Any]) -> Tuple[float, str]:
    return (
        metrics.get("residential_score_10", 5),
        "민가밀집 기본점수는 500m 이내 주거노출지수 또는 건물 수 기준으로 산정했습니다.",
    )


def calculate_residential_exposure_index(
    buildings: Dict[str, Any],
    building_counts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_exposure = buildings.get("residential_exposure") or {}
    exposure = {
        "150m": _first_number(buildings.get("residential_exposure_150m"), raw_exposure.get("150m")),
        "250m": _first_number(buildings.get("residential_exposure_250m"), raw_exposure.get("250m")),
        "350m": _first_number(buildings.get("residential_exposure_350m"), raw_exposure.get("350m")),
        "500m": _first_number(buildings.get("residential_exposure_500m"), raw_exposure.get("500m")),
    }
    confidence = buildings.get("residential_confidence")
    if all(value is not None for value in exposure.values()):
        return {"exposure": exposure, "confidence": confidence or "중간"}

    candidates = buildings.get("candidates") or []
    if candidates:
        computed = {"150m": 0.0, "250m": 0.0, "350m": 0.0, "500m": 0.0}
        known = 0
        for item in candidates:
            distance = _number(item.get("distance_m"), None)
            if distance is None or distance > 500:
                continue
            use_text = str(item.get("building_use") or "")
            props = item.get("properties") or {}
            weight = _number(item.get("residential_weight"), None)
            if weight is None:
                use_text = use_text or _candidate_building_use(props)
                weight = _residential_use_weight(use_text)
            weighted_exposure = _first_number(
                item.get("residential_exposure_weight"),
                (weight or 0) * _residential_distance_weight(distance),
            )
            if use_text and use_text != "용도 미상":
                known += 1
            if distance <= 150:
                computed["150m"] += weighted_exposure or 0
            if distance <= 250:
                computed["250m"] += weighted_exposure or 0
            if distance <= 350:
                computed["350m"] += weighted_exposure or 0
            computed["500m"] += weighted_exposure or 0
        exposure = {key: round(value, 1) for key, value in computed.items()}
        ratio = known / max(1, len([item for item in candidates if _number(item.get("distance_m"), 9999) <= 500]))
        if known == 0:
            counts = building_counts or {}
            exposure = {
                "150m": _number(counts.get("150m"), None),
                "250m": _number(counts.get("250m"), None),
                "350m": _number(counts.get("350m"), None),
                "500m": _number(counts.get("500m"), None),
            }
        return {"exposure": exposure, "confidence": confidence or _confidence_from_ratio(ratio)}

    counts = building_counts or {}
    exposure = {
        "150m": _number(counts.get("150m"), None),
        "250m": _number(counts.get("250m"), None),
        "350m": _number(counts.get("350m"), None),
        "500m": _number(counts.get("500m"), None),
    }
    return {"exposure": exposure, "confidence": confidence or "낮음"}


def calculate_residential_penalty_candidates(exposure: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    c150 = _number(exposure.get("150m"), None)
    c250 = _number(exposure.get("250m"), None)
    c350 = _number(exposure.get("350m"), None)
    c500 = _number(exposure.get("500m"), None)
    return {
        "150m": _residential_radius_penalty("150m", c150),
        "250m": _residential_radius_penalty("250m", c250),
        "350m": _residential_radius_penalty("350m", c350),
        "500m": _residential_radius_penalty("500m", c500),
    }


def calculate_residential_proximity_penalty(exposure: Dict[str, Any]) -> Dict[str, Any]:
    return calculate_residential_penalty_applied(calculate_residential_penalty_candidates(exposure))


def calculate_residential_penalty_applied(candidates: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    radius_rank = {"150m": 0, "250m": 1, "350m": 2, "500m": 3}
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            float(item.get("penalty") or 0),
            -radius_rank.get(str(item.get("radius")), 9),
            -float(item.get("fatal_cap") or 999),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else {"radius": None, "penalty": 0, "fatal_cap": None, "judgement": ""}


def calculate_residential_cluster_sensitive_penalty(
    buildings: Dict[str, Any],
    places: Optional[Dict[str, Any]] = None,
    tower_points: Optional[List[Dict[str, Any]]] = None,
    parcel_center: Optional[Dict[str, Any]] = None,
    site_polygons: Optional[List[List[Dict[str, float]]]] = None,
    anchor_point: Optional[Dict[str, Any]] = None,
    effective_access_path: Optional[Dict[str, Any]] = None,
    residential_confidence: Optional[str] = None,
) -> Dict[str, Any]:
    places = places or {}
    candidates = []
    for item in buildings.get("candidates") or []:
        distance = _number(item.get("distance_m"), None)
        if distance is not None and distance <= 1000 and item.get("lat") is not None and item.get("lng") is not None:
            candidates.append(item)
    residential_points = [
        item
        for item in candidates
        if (_number(item.get("distance_m"), 999999) or 999999) <= 500
        and _is_residential_like_use(str(item.get("building_use") or ""))
    ]
    detection_failed = not bool(places.get("ok")) and not (
        places.get("sensitive_facilities") or places.get("residential_complexes")
    )
    distance_anchor = anchor_point or parcel_center
    sensitive_points = [
        sensitive_tools.calculate_distance_to_site_boundary(item, site_polygons or [], distance_anchor)
        for item in sensitive_tools.merge_duplicate_facilities(detect_sensitive_facilities(buildings, places))
    ]
    complex_points = [
        sensitive_tools.calculate_distance_to_site_boundary(item, site_polygons or [], distance_anchor)
        for item in sensitive_tools.merge_duplicate_facilities(detect_residential_complexes(buildings, places))
    ]
    sensitive_points.sort(key=lambda item: _number(item.get("applied_distance_m"), 999999) or 999999)
    complex_points.sort(key=lambda item: _number(item.get("applied_distance_m"), 999999) or 999999)

    cluster_250 = _largest_residential_cluster(residential_points, radius_m=250)
    cluster_350 = _largest_residential_cluster(residential_points, radius_m=350)
    cluster_penalty = 0
    cluster_reason = ""
    if not _is_low_residential_confidence(residential_confidence) and cluster_250 >= 20:
        cluster_penalty = 5
        cluster_reason = "250m 안에 주거성 건물 10개 이상 마을군이 형성된 것으로 추정됩니다."
    elif not _is_low_residential_confidence(residential_confidence) and cluster_350 >= 40:
        cluster_penalty = 5
        cluster_reason = "350m 안에 주거성 건물 20개 이상 마을군이 형성된 것으로 추정됩니다."

    sensitive_profile = sensitive_tools.calculate_sensitive_facility_penalty(
        sensitive_points,
        detection_failed=detection_failed,
        message=str(places.get("message") or ""),
    )
    complex_profile = sensitive_tools.calculate_residential_complex_penalty(
        complex_points,
        detection_failed=detection_failed,
        message=str(places.get("message") or ""),
    )

    route_penalty = 0
    route_cap = None
    route_reason = ""
    route_lines = _residential_route_lines(tower_points or [], parcel_center, effective_access_path or {})
    if route_lines and residential_points:
        for line in route_lines:
            near_route_count = 0
            for item in residential_points:
                distance_to_route = geometry.point_to_line_distance_m({"lat": item.get("lat"), "lng": item.get("lng")}, line)
                if distance_to_route is not None and distance_to_route <= 30:
                    near_route_count += 1
            if near_route_count >= 8:
                route_penalty = 25
                route_cap = 65
                route_reason = "예상 송전선 또는 진입로 경로가 마을군을 통과하는 것으로 추정됩니다."
                break

    cluster_sensitive_penalty = (
        cluster_penalty
        + sensitive_profile["penalty"]
        + complex_profile["penalty"]
        + route_penalty
    )
    caps = [
        value
        for value in [
            sensitive_profile.get("fatal_cap"),
            complex_profile.get("fatal_cap"),
            route_cap,
        ]
        if value is not None
    ]
    reasons = [
        reason
        for reason in [
            cluster_reason,
            sensitive_profile.get("judgement"),
            complex_profile.get("judgement"),
            route_reason,
        ]
        if reason
    ]
    return {
        "penalty": cluster_sensitive_penalty,
        "cluster_penalty": cluster_penalty,
        "sensitive_facility_penalty": sensitive_profile["penalty"],
        "sensitive_facility_fatal_cap": sensitive_profile.get("fatal_cap"),
        "sensitive_facility_count": len(sensitive_points),
        "major_sensitive_facility_count": sensitive_profile.get("major_count", 0),
        "reference_facility_count": sensitive_profile.get("reference_count", 0),
        "sensitive_facilities": sensitive_points[:40],
        "nearest_sensitive_facility_name": sensitive_profile.get("nearest_name"),
        "nearest_sensitive_facility_type": sensitive_profile.get("nearest_type"),
        "nearest_sensitive_facility_distance_m": sensitive_profile.get("nearest_distance_m"),
        "nearest_major_sensitive_facility_name": sensitive_profile.get("nearest_major_name"),
        "nearest_major_sensitive_facility_type": sensitive_profile.get("nearest_major_type"),
        "nearest_major_sensitive_facility_distance_m": sensitive_profile.get("nearest_major_distance_m"),
        "nearest_reference_facility_name": sensitive_profile.get("nearest_reference_name"),
        "nearest_reference_facility_type": sensitive_profile.get("nearest_reference_type"),
        "nearest_reference_facility_distance_m": sensitive_profile.get("nearest_reference_distance_m"),
        "sensitive_detection_status": sensitive_profile.get("detection_status"),
        "sensitive_distance_from_anchor_m": sensitive_profile.get("distance_from_anchor_m"),
        "sensitive_distance_from_site_boundary_m": sensitive_profile.get("distance_from_site_boundary_m"),
        "sensitive_applied_distance_m": sensitive_profile.get("applied_distance_m"),
        "sensitive_facility_penalty_applied": sensitive_profile.get("penalty_applied", False),
        "sensitive_facility_source": sensitive_profile.get("source"),
        "sensitive_facility_confidence": sensitive_profile.get("confidence"),
        "major_sensitive_facility_penalty": sensitive_profile.get("major_penalty", 0),
        "reference_facility_penalty": sensitive_profile.get("reference_penalty", 0),
        "reference_facility_manual_check": sensitive_profile.get("reference_manual_check", False),
        "reference_facility_judgement": sensitive_profile.get("reference_judgement"),
        "residential_complex_penalty": complex_profile["penalty"],
        "residential_complex_fatal_cap": complex_profile.get("fatal_cap"),
        "residential_complex_count": len(complex_points),
        "residential_complexes": complex_points[:40],
        "residential_complex_detection_status": complex_profile.get("detection_status"),
        "nearest_residential_complex_name": complex_profile.get("nearest_name"),
        "nearest_residential_complex_distance_m": complex_profile.get("nearest_distance_m"),
        "residential_complex_source": complex_profile.get("source"),
        "residential_complex_confidence": complex_profile.get("confidence"),
        "residential_large_complex_detected": complex_profile.get("large_complex_detected", False),
        "residential_large_complex_reason": complex_profile.get("reason"),
        "residential_large_complex_confidence": complex_profile.get("confidence", "불명확"),
        "residential_large_complex_source": complex_profile.get("source", "불명확"),
        "sensitive_facility_detected": bool(sensitive_points),
        "penalty_not_applied_reason": complex_profile.get("not_applied_reason"),
        "manual_residential_override_penalty": 0,
        "manual_residential_override_fatal_cap": None,
        "route_penalty": route_penalty,
        "fatal_cap": min(caps) if caps else None,
        "judgement": " ".join(reasons),
        "cluster_250m_count": cluster_250,
        "cluster_350m_count": cluster_350,
        "sensitive_facility_nearest_m": sensitive_profile.get("nearest_distance_m"),
    }


def detect_sensitive_facilities(buildings: Dict[str, Any], places: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in (places or {}).get("sensitive_facilities") or []:
        normalized = _normalize_place_item(item, "kakao_keyword")
        if normalized and _add_seen(normalized, seen):
            items.append(normalized)
    for item in buildings.get("candidates") or []:
        text = _candidate_place_text(item)
        if not _is_sensitive_facility_use(text):
            continue
        normalized = _normalize_place_item(item, "vworld_building")
        if normalized and _add_seen(normalized, seen):
            items.append(normalized)
    items.sort(key=lambda item: item.get("distance_m") if item.get("distance_m") is not None else 999999)
    return items


def calculate_sensitive_facility_penalty(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    nearest = items[0] if items else None
    distance = _number((nearest or {}).get("distance_m"), None)
    penalty = 0
    fatal_cap = None
    judgement = ""
    if distance is not None and distance <= 250:
        penalty = 30
        fatal_cap = 55
        judgement = "민감시설이 250m 이내에 있어 직접 영향권 리스크로 강하게 반영했습니다."
    elif distance is not None and distance <= 500:
        penalty = 15
        fatal_cap = 75
        judgement = "민감시설이 500m 이내에 있어 주민수용성 확인 리스크로 반영했습니다."
    elif distance is not None and distance <= 1000:
        judgement = "민감시설이 500m 밖 1km 이내에 있어 참고값으로만 표시하고 자동감점하지 않았습니다."
    return {
        "penalty": penalty,
        "fatal_cap": fatal_cap,
        "nearest_name": (nearest or {}).get("name"),
        "nearest_type": (nearest or {}).get("category") or (nearest or {}).get("type"),
        "nearest_distance_m": _round_or_none(distance),
        "judgement": judgement,
    }

    nearest = items[0] if items else None
    distance = _number((nearest or {}).get("distance_m"), None)
    penalty = 0
    fatal_cap = None
    judgement = ""
    if distance is not None and distance <= 250:
        penalty = 30
        fatal_cap = 55
        judgement = "학교·유치원·어린이집·요양시설 등 민감시설이 250m 이내에 있어 치명조건으로 반영했습니다."
    elif distance is not None and distance <= 500:
        penalty = 15
        fatal_cap = 75
        judgement = "학교·유치원·어린이집·요양시설 등 민감시설이 500m 이내에 있어 강한 감점요소로 반영했습니다."
    elif distance is not None and distance <= 1000:
        penalty = 0
        fatal_cap = None
        judgement = "학교·유치원·어린이집·요양시설 등 민감시설이 1km 이내에 있어 주의 감점으로 반영했습니다."
    return {
        "penalty": penalty,
        "fatal_cap": fatal_cap,
        "nearest_name": (nearest or {}).get("name"),
        "nearest_type": (nearest or {}).get("category") or (nearest or {}).get("type"),
        "nearest_distance_m": _round_or_none(distance),
        "judgement": judgement,
    }


def detect_residential_complexes(buildings: Dict[str, Any], places: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in (places or {}).get("residential_complexes") or []:
        profile = _residential_complex_match_profile(_candidate_place_text(item))
        if not profile["match"]:
            continue
        normalized = _normalize_place_item(item, "kakao_keyword")
        if normalized and _add_seen(normalized, seen):
            normalized.update(profile)
            items.append(normalized)
    for item in buildings.get("candidates") or []:
        text = _candidate_place_text(item)
        profile = _residential_complex_match_profile(text)
        if not profile["match"]:
            continue
        normalized = _normalize_place_item(item, "vworld_building")
        if normalized and _add_seen(normalized, seen):
            normalized.update(profile)
            items.append(normalized)
    items.sort(key=lambda item: item.get("distance_m") if item.get("distance_m") is not None else 999999)
    return items


def calculate_residential_complex_penalty(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    reference_items = sorted(items, key=lambda item: item.get("distance_m") if item.get("distance_m") is not None else 999999)
    clear_items = [
        item
        for item in reference_items
        if (_number(item.get("distance_m"), 999999) or 999999) <= 500
        and not _is_low_residential_confidence(item.get("confidence"))
    ]
    nearest_reference = reference_items[0] if reference_items else None
    nearest = clear_items[0] if clear_items else None
    distance = _number((nearest or {}).get("distance_m"), None)
    reference_distance = _number((nearest_reference or {}).get("distance_m"), None)
    count_500m = len(clear_items)
    penalty = 0
    fatal_cap = None
    judgement = ""
    reason = (nearest or nearest_reference or {}).get("reason")
    source = (nearest or nearest_reference or {}).get("source") or "불명확"
    confidence = (nearest or nearest_reference or {}).get("confidence") or "불명확"
    not_applied_reason = ""

    if distance is not None and distance <= 250:
        penalty = 25
        fatal_cap = 60
        judgement = "명확한 아파트단지 또는 공동주택단지가 250m 이내에 있어 주민수용성 리스크를 반영했습니다."
    elif distance is not None and distance <= 500:
        penalty = 15
        fatal_cap = 75
        judgement = "명확한 아파트단지 또는 공동주택단지가 500m 이내에 있어 주민수용성 확인 리스크를 반영했습니다."
    elif reference_distance is not None and reference_distance <= 1000:
        judgement = "1km 이내 주거단지 정보는 참고값으로만 표시하고 자동감점에는 반영하지 않았습니다."
        not_applied_reason = "1km 참고권역 정보이거나 대규모 주거단지 근거가 불명확해 자동감점하지 않았습니다."

    if count_500m >= 5:
        penalty = max(penalty, 35)
        fatal_cap = min(_number(fatal_cap, 100) or 100, 55)
        judgement = (judgement + " 500m 이내 명확한 공동주택단지가 5개 이상 확인되어 상한을 적용했습니다.").strip()
    elif count_500m >= 3:
        penalty = max(penalty, 25)
        fatal_cap = min(_number(fatal_cap, 100) or 100, 65)
        judgement = (judgement + " 500m 이내 명확한 공동주택단지가 3개 이상 확인되어 상한을 적용했습니다.").strip()

    if not clear_items and reference_items and not not_applied_reason:
        not_applied_reason = "탐지명 또는 거리가 대규모 주거단지 자동감점 기준에 미달하여 수동확인 대상으로 표시했습니다."

    return {
        "penalty": penalty,
        "fatal_cap": None if fatal_cap == 100 else fatal_cap,
        "nearest_distance_m": _round_or_none(reference_distance),
        "count_500m": count_500m,
        "large_complex_detected": bool(clear_items),
        "reason": reason or ("명확한 500m 이내 공동주택단지 확인" if clear_items else "자동감점 근거 불명확"),
        "confidence": confidence if clear_items else "낮음",
        "source": source,
        "not_applied_reason": not_applied_reason,
        "judgement": judgement,
    }

    nearest = items[0] if items else None
    distance = _number((nearest or {}).get("distance_m"), None)
    count_500m = sum(1 for item in items if (_number(item.get("distance_m"), 999999) or 999999) <= 500)
    penalty = 0
    fatal_cap = None
    judgement = ""
    if distance is not None and distance <= 250:
        penalty = 30
        fatal_cap = 55
        judgement = "아파트단지 또는 공동주택단지가 250m 이내에 있어 주민수용성 리스크를 크게 반영했습니다."
    elif distance is not None and distance <= 500:
        penalty = 20
        fatal_cap = 65
        judgement = "아파트단지 또는 공동주택단지가 500m 이내에 있어 전자파·소음·공사차량 리스크를 반영했습니다."
    elif distance is not None and distance <= 1000:
        penalty = 8
        judgement = "대규모 주거단지가 1km 이내에 있어 주의 감점으로 반영했습니다."
    if count_500m >= 5:
        fatal_cap = min(_number(fatal_cap, 100) or 100, 50)
        judgement = (judgement + " 500m 이내 주거단지가 5개 이상 탐지되어 상한을 강화했습니다.").strip()
    elif count_500m >= 3:
        fatal_cap = min(_number(fatal_cap, 100) or 100, 60)
        judgement = (judgement + " 500m 이내 주거단지가 3개 이상 탐지되어 상한을 적용했습니다.").strip()
    return {
        "penalty": penalty,
        "fatal_cap": None if fatal_cap == 100 else fatal_cap,
        "nearest_distance_m": _round_or_none(distance),
        "count_500m": count_500m,
        "judgement": judgement,
    }


def calculate_manual_residential_override_penalty(manual: ManualInputs | None) -> Dict[str, Any]:
    del manual
    return {"penalty": 0, "fatal_cap": None, "judgement": ""}
    if not manual:
        return {"penalty": 0, "fatal_cap": None, "judgement": ""}
    updated_options = []
    if getattr(manual, "apartment_250m", False):
        updated_options.append((25, 60, "수동보정: 250m 이내 명확한 아파트단지 존재를 반영했습니다."))
    if getattr(manual, "apartment_500m", False):
        updated_options.append((15, 75, "수동보정: 500m 이내 명확한 아파트단지 존재를 반영했습니다."))
    if getattr(manual, "school_250m", False):
        updated_options.append((30, 55, "수동보정: 250m 이내 학교·유치원·어린이집 존재를 반영했습니다."))
    if getattr(manual, "school_500m", False):
        updated_options.append((15, 75, "수동보정: 500m 이내 학교·유치원·어린이집 존재를 반영했습니다."))
    if getattr(manual, "dense_residential_500m", False):
        updated_options.append((20, 75, "수동보정: 500m 이내 주거밀집 매우 높음을 반영했습니다."))
    if getattr(manual, "route_through_residential", False):
        updated_options.append((25, 65, "수동보정: 송전선 또는 진입로가 마을·아파트단지를 통과하는 리스크를 반영했습니다."))
    if getattr(manual, "residential_low_confirmed", False):
        updated_options.append((0, None, "수동확인: 실제 민가밀집 낮음으로 확인되었습니다. 자동 감점은 고급설정에서만 조정하세요."))
    if not updated_options:
        return {"penalty": 0, "fatal_cap": None, "judgement": ""}
    updated_penalty = max(item[0] for item in updated_options)
    updated_caps = [item[1] for item in updated_options if item[1] is not None]
    return {
        "penalty": updated_penalty,
        "fatal_cap": min(updated_caps) if updated_caps else None,
        "judgement": " ".join(item[2] for item in updated_options),
    }
    options = []
    if getattr(manual, "apartment_250m", False):
        options.append((30, 55, "수동보정: 250m 이내 아파트단지 존재를 반영했습니다."))
    if getattr(manual, "apartment_500m", False):
        options.append((20, 65, "수동보정: 500m 이내 아파트단지 존재를 반영했습니다."))
    if getattr(manual, "school_250m", False):
        options.append((35, 50, "수동보정: 250m 이내 학교·유치원·어린이집 존재를 반영했습니다."))
    if getattr(manual, "school_500m", False):
        options.append((25, 60, "수동보정: 500m 이내 학교·유치원·어린이집 존재를 반영했습니다."))
    if getattr(manual, "dense_residential_500m", False):
        options.append((25, 60, "수동보정: 500m 이내 주거밀집 매우 높음을 반영했습니다."))
    if getattr(manual, "route_through_residential", False):
        options.append((30, 55, "수동보정: 송전선 또는 진입로가 마을·아파트단지를 통과하는 리스크를 반영했습니다."))
    if getattr(manual, "residential_low_confirmed", False):
        options.append((0, None, "수동확인: 실제 민가밀집 낮음으로 확인되었지만 자동 감점은 해제하지 않습니다."))
    if not options:
        return {"penalty": 0, "fatal_cap": None, "judgement": ""}
    penalty = max(item[0] for item in options)
    caps = [item[1] for item in options if item[1] is not None]
    return {
        "penalty": penalty,
        "fatal_cap": min(caps) if caps else None,
        "judgement": " ".join(item[2] for item in options),
    }


def calculate_residential_penalty_total(
    proximity_penalty: Any,
    cluster_penalty: Any = 0,
    sensitive_facility_penalty: Any = 0,
    residential_complex_penalty: Any = 0,
    route_penalty: Any = 0,
    manual_residential_override_penalty: Any = 0,
) -> float:
    total = (
        (_number(proximity_penalty, 0) or 0)
        + (_number(cluster_penalty, 0) or 0)
        + (_number(sensitive_facility_penalty, 0) or 0)
        + (_number(residential_complex_penalty, 0) or 0)
        + (_number(route_penalty, 0) or 0)
        + (_number(manual_residential_override_penalty, 0) or 0)
    )
    return min(50.0, total)


def calculate_residential_fatal_cap(*items: Dict[str, Any]) -> Optional[float]:
    caps = [_number((item or {}).get("fatal_cap"), None) for item in items]
    caps = [cap for cap in caps if cap is not None]
    return min(caps) if caps else None


def calculate_policy_location_score_10(metrics: Dict[str, Any]) -> Tuple[float, str]:
    policy = metrics.get("policy") or {}
    score = policy.get("site_internal_score")
    if score is None:
        score = policy.get("internal_score")
    if score is None:
        score = policy_tools.convert_policy_bonus_to_internal_score(metrics.get("official_location_bonus"))
    return float(score), "정책입지는 공식 전평 가·감점과 분리해 앱 내부 10점 점수로 환산해 기본점수에 반영했습니다."


def calculate_policy_penalty(adjustment: Optional[int]) -> float:
    return 0


def calculate_policy_fatal_cap(adjustment: Optional[int]) -> Optional[float]:
    return None


def evaluate_business_area_requirement(metrics: Dict[str, Any]) -> Dict[str, Any]:
    summary = metrics.get("selected_summary") or {}
    total_pyeong = _number(
        metrics.get("selected_total_area_pyeong", summary.get("total_area_pyeong")),
        None,
    )
    total_m2 = _number(
        metrics.get("selected_total_area_m2", summary.get("total_area_m2")),
        None,
    )
    if total_pyeong is None and total_m2 is not None:
        total_pyeong = geometry.area_to_pyeong(total_m2)
    if total_m2 is None and total_pyeong is not None:
        total_m2 = total_pyeong * 3.305785

    eligible = total_pyeong is not None and total_pyeong >= MIN_BUSINESS_AREA_PYEONG
    shortage = None if total_pyeong is None else max(0.0, MIN_BUSINESS_AREA_PYEONG - total_pyeong)
    return {
        "minimum_business_area_pyeong": MIN_BUSINESS_AREA_PYEONG,
        "business_area_total_m2": round(total_m2, 2) if total_m2 is not None else None,
        "business_area_total_pyeong": round(total_pyeong, 2) if total_pyeong is not None else None,
        "business_area_shortage_pyeong": round(shortage, 2) if shortage is not None else None,
        "business_area_eligible": eligible,
        "business_area_gate_applied": not eligible,
        "business_area_requirement_message": " / ".join(AREA_REQUIREMENT_BLOCK_MESSAGES) if not eligible else "최소 사업구역 면적 10,000평 이상 충족",
        "business_area_block_messages": [] if eligible else list(AREA_REQUIREMENT_BLOCK_MESSAGES),
    }


def _area_blocked_score(metrics: Dict[str, Any], area_requirement: Dict[str, Any]) -> Dict[str, Any]:
    categories = [
        _category(
            key,
            None,
            "최소 사업구역 면적 10,000평 이상일 때만 전력·인허가·민원·정책입지·기반시설 종합점수를 산정합니다.",
        )
        for key in CATEGORY_MAX
    ]
    messages = list(area_requirement.get("business_area_block_messages") or AREA_REQUIREMENT_BLOCK_MESSAGES)
    total_pyeong = area_requirement.get("business_area_total_pyeong")
    shortage = area_requirement.get("business_area_shortage_pyeong")
    area_line = (
        f"현재 선택 필지 총합 면적은 {round(total_pyeong, 1):,}평이며, 최소 기준까지 {round(shortage or 0, 1):,}평이 부족합니다."
        if total_pyeong is not None
        else "선택 필지 총합 면적을 확인할 수 없어 최소 사업구역 면적 충족 여부를 판단할 수 없습니다."
    )
    return {
        "base_score": None,
        "base_total": None,
        "penalty_score": 0,
        "total_adjustment": 0,
        "pre_cap_total": None,
        "provisional_score": None,
        "fatal_cap": None,
        "final_score_cap": None,
        "fatal_cap_applied": False,
        "fatal_cap_reasons": [],
        "total": None,
        "final_score": None,
        "grade": "-",
        "final_grade": "-",
        "grade_label": "대용량 수전형 데이터센터 검토 불가",
        "score_status": "area_requirement_blocked",
        "evaluation_blocked": True,
        "business_area_eligible": False,
        "area_requirement": area_requirement,
        "blocking_messages": messages,
        "conditional_flags": ["최소 사업구역 면적 10,000평 미달"],
        "categories": categories,
        "adjustments": [],
        "penalty_items": [],
        "strengths": [],
        "weaknesses": messages[:3] + [area_line],
        "next_checks": [messages[-1], area_line],
        "metrics": metrics,
    }


def calculate_slope_score_5(metrics: Dict[str, Any]) -> Tuple[Optional[float], str]:
    if metrics.get("slope_status") == "unknown" and metrics.get("slope_score_5") is None:
        return None, "경사도 자동계산 실패: 점수 감점은 적용하지 않았으며, 현장측량 또는 수동 경사도 입력이 필요합니다."
    return metrics.get("slope_score_5", 2), metrics.get("slope_judgement") or "경사도는 등고선 또는 DEM 기반 1차 추정입니다."


def calculate_slope_penalty(metrics: Dict[str, Any]) -> float:
    return _number(metrics.get("slope_penalty"), 0) or 0


def calculate_slope_fatal_cap(metrics: Dict[str, Any]) -> Optional[float]:
    return _number(metrics.get("slope_fatal_cap"), None)


def calculate_power_self_score_5(metrics: Dict[str, Any]) -> Tuple[float, str]:
    return metrics.get("power_self_score_5", 2), metrics.get("power_self_judgement") or "전력자립도는 내부 총점에 5점으로 약하게 반영합니다."


def _overlay_regulation_profile(overlay_regulations: Dict[str, Any]) -> Dict[str, Any]:
    penalty_items: List[Dict[str, Any]] = []
    manual_check_items: List[str] = []
    hold_reasons: List[str] = []
    hold_decision: Optional[str] = None

    for item in overlay_regulations.get("items") or []:
        key = str(item.get("key") or "")
        rule = OVERLAY_REGULATION_RULES.get(key)
        if not rule:
            continue
        label = str(item.get("label") or rule["label"])
        suspected = bool(item.get("suspected")) or "의심" in str(item.get("status") or "")
        detected = bool(item.get("detected")) and not suspected

        if suspected:
            manual_check_items.append(f"{label}: 중첩 의심 / 수동 확인 필요")
            item["overlay_penalty"] = 0
            item["overlay_decision"] = "수동확인 필요"
            item["overlay_penalty_reason"] = "중첩비율 계산이 어려워 감점 대신 수동 확인 필요로 표시했습니다."
            continue

        if not detected:
            item["overlay_penalty"] = 0
            item["overlay_decision"] = None
            continue

        base_penalty = float(rule["penalty"])
        ratio = _number(item.get("overlap_ratio"), None)
        factor = 0.5 if ratio is not None and ratio < 30 else 1.0
        applied_penalty = round(base_penalty * factor, 1)
        reason = f"{label} 중첩 확인"
        if ratio is not None:
            reason += f" / 중첩비율 {ratio:g}%"
            if factor < 1:
                reason += " / 30% 미만으로 기준 감점의 50% 적용"
        penalty_items.append(
            {
                "key": key,
                "label": label,
                "base_penalty": base_penalty,
                "penalty": applied_penalty,
                "decision": rule.get("decision"),
                "reason": reason,
                "overlap_ratio": ratio,
            }
        )
        item["overlay_penalty"] = applied_penalty
        item["overlay_decision"] = rule.get("decision")
        item["overlay_penalty_reason"] = reason
        if rule.get("decision"):
            hold_reasons.append(f"{label}: {rule['decision']}")
            hold_decision = _stronger_overlay_decision(hold_decision, str(rule["decision"]))

    return {
        "penalty_items": penalty_items,
        "penalty_total": round(sum(float(item["penalty"]) for item in penalty_items), 1),
        "fatal_cap": None,
        "hold_decision": hold_decision,
        "hold_reasons": hold_reasons,
        "manual_check_items": manual_check_items,
    }


def _stronger_overlay_decision(current: Optional[str], candidate: str) -> str:
    if not current:
        return candidate
    return candidate if OVERLAY_DECISION_RANK.get(candidate, 0) > OVERLAY_DECISION_RANK.get(current, 0) else current


def calculate_base_score(categories: List[Dict[str, Any]]) -> float:
    available_score = 0.0
    available_max = 0.0
    for item in categories:
        if item.get("score") is None:
            continue
        available_score += float(item.get("score") or 0)
        available_max += float(item.get("max") or 0)
    if available_max and available_max < 100:
        return round((available_score / available_max) * 100, 1)
    return round(available_score, 1)


def calculate_penalty_score(penalty_items: List[Dict[str, Any]]) -> float:
    return round(sum(float(item.get("score") or 0) for item in penalty_items), 1)


def calculate_fatal_cap(metrics: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    caps: List[Tuple[float, str]] = []
    cap_map = [
        ("policy_fatal_cap", "정책입지 감점구간 상한"),
        ("residential_fatal_cap", "민가 과밀 치명조건 상한"),
        ("slope_fatal_cap", "경사도 토목 리스크 상한"),
        ("overlay_regulation_fatal_cap", "중첩 규제구역 상한"),
        ("greenbelt_fatal_cap", "개발제한구역 상한"),
        ("agricultural_fatal_cap", "농림지역 상한"),
        ("road_fatal_cap", "도로 연결 구조 확인 불가 상한"),
        ("power_marking_fatal_cap", "송전탑 수동마킹 없음 상한"),
        ("fragmentation_fatal_cap", "필지 분산도 상한"),
    ]
    for key, label in cap_map:
        cap = _number(metrics.get(key), None)
        if cap is not None:
            caps.append((cap, f"{label} {cap:g}점"))
    if not caps:
        return None, []
    cap_value = min(cap for cap, _ in caps)
    reasons = [reason for cap, reason in caps if cap == cap_value] or [reason for _, reason in caps]
    return cap_value, reasons


def calculate_final_score(base_score: float, penalty_score: float, fatal_cap: Optional[float]) -> float:
    score = max(0.0, min(100.0, round(base_score - penalty_score, 1)))
    if fatal_cap is not None:
        score = min(score, float(fatal_cap))
    return max(0.0, min(100.0, round(score, 1)))


def _penalty_items(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    def add(key: str, label: str, score: Any, reason: str) -> None:
        value = _number(score, 0) or 0
        if value > 0:
            items.append({"key": key, "label": label, "score": value, "signed_score": -value, "reason": reason})

    official = metrics.get("official_location_bonus")
    add(
        "policy_location_penalty",
        "정책입지 감점",
        metrics.get("policy_penalty_modifier"),
        metrics.get("policy_judgement") or f"정책입지 지침서 기준 {official}점 감점구간입니다.",
    )
    add(
        "residential_penalty",
        "민가 관련 감점",
        metrics.get("residential_penalty_total", metrics.get("residential_penalty_applied")),
        metrics.get("residential_penalty_judgement") or "근거리 주거노출, 마을군, 민감시설 또는 경로 리스크 기준 민가 감점을 적용했습니다.",
    )
    add("slope_penalty", "경사도 감점", calculate_slope_penalty(metrics), metrics.get("slope_judgement") or "경사도 리스크를 반영했습니다.")
    add(
        "fragmentation_penalty",
        "필지 분산도 감점",
        metrics.get("fragmentation_penalty"),
        metrics.get("fragmentation_judgement") or "필지 수는 권리관계 정리 난이도 참고값으로 반영했습니다.",
    )

    overlay_penalties = metrics.get("overlay_regulation_penalty_items") or []
    metrics["overlay_regulation_penalty_total"] = round(sum(float(item.get("penalty") or 0) for item in overlay_penalties), 1)
    metrics["greenbelt_penalty"] = 0
    for item in overlay_penalties:
        label = item.get("label") or OVERLAY_REGULATION_RULES.get(str(item.get("key") or ""), {}).get("label") or "중첩 규제구역"
        penalty = item.get("penalty") or 0
        add(
            f"overlay_regulation_{item.get('key') or label}",
            f"{label} 감점",
            penalty,
            item.get("reason") or f"{label} 중첩 규제구역 감점을 반영했습니다.",
        )
        if item.get("key") == "greenbelt":
            metrics["greenbelt_penalty"] = penalty

    if metrics.get("greenbelt_detected") and not metrics.get("greenbelt_suspected") and not metrics.get("greenbelt_penalty"):
        greenbelt_penalty = OVERLAY_REGULATION_RULES["greenbelt"]["penalty"]
        metrics["greenbelt_penalty"] = greenbelt_penalty
        metrics["overlay_regulation_penalty_total"] = round(
            (_number(metrics.get("overlay_regulation_penalty_total"), 0) or 0) + greenbelt_penalty,
            1,
        )
        add(
            "overlay_regulation_greenbelt",
            "개발제한구역 감점",
            greenbelt_penalty,
            "개발제한구역으로 확인되어 중첩규제구역 감점을 별도 반영했습니다.",
        )

    if metrics.get("agricultural_mixed_risk"):
        metrics["agricultural_penalty"] = 10
        metrics["agricultural_fatal_cap"] = None
        add(
            "agricultural_mixed_penalty",
            "농림지역 혼입 리스크 감점",
            10,
            metrics.get("agricultural_mixed_judgement")
            or "농림지역 비율이 30% 미만으로 일부 혼입되어 기본 인허가 점수는 유지하고 혼입 리스크만 별도 감점했습니다.",
        )
    elif metrics.get("is_agricultural"):
        metrics["agricultural_penalty"] = 10
        metrics["agricultural_fatal_cap"] = 75
        add(
            "agricultural_penalty",
            "농림지역 감점",
            10,
            "농림지역으로 확인되어 인허가 설명력은 낮게 평가합니다. 다만 전력·도로·정책 조건이 우수하면 전략검토 후보로 남길 수 있습니다.",
        )
    else:
        metrics["agricultural_penalty"] = 0

    road_score = _number(metrics.get("road_score_20"), 0) or 0
    road_count = _number(metrics.get("road_candidate_count_500m"), None)
    manual_road = (
        bool(metrics.get("manual_override_width_class"))
        or bool((metrics.get("manual_visual_road") or {}).get("ok"))
        or bool(metrics.get("construction_access_difficult_manual"))
    )
    if road_score <= 0 and not manual_road and (road_count in (None, 0) or not metrics.get("roads_ok")):
        metrics["road_penalty"] = 20
        metrics["road_fatal_cap"] = 60
        add("road_penalty", "도로 불량 감점", 20, "500m 내 도로 후보 또는 연결 구조를 확인하지 못해 큰 감점을 적용했습니다.")
    elif road_score <= 1 and not manual_road:
        metrics["road_penalty"] = 15
        add("road_penalty", "도로 불량 감점", 15, "도로 연결 구조가 불명확해 별도 감점을 적용했습니다.")
    else:
        metrics["road_penalty"] = 0

    tower_count = (metrics.get("transmission") or {}).get("tower_count") or 0
    if not tower_count:
        metrics["power_marking_penalty"] = 10
        metrics["power_marking_fatal_cap"] = 70
        add(
            "power_marking_penalty",
            "송전탑 수동마킹 없음 감점",
            10,
            "송전탑·송전선 후보가 수동마킹되지 않아 전력축 불확실성 감점과 70점 상한을 적용했습니다.",
        )
    else:
        metrics["power_marking_penalty"] = 0

    metrics.setdefault("greenbelt_penalty", 0)
    metrics.setdefault("agricultural_penalty", 0)
    metrics.setdefault("road_penalty", 0)
    metrics.setdefault("power_marking_penalty", 0)
    return items


def _effective_access_path(
    roads: Dict[str, Any],
    selected: List[Dict[str, Any]],
    manual: ManualInputs | None,
    visual_road: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base = dict(roads.get("access_path") or {})
    selected_contact = [item for item in selected if item.get("has_road_contact")]
    selected_contribution = [item for item in selected if item.get("road_connection_contribution")]
    selected_width_class = _best_selected_road_width_class(selected)
    width_rank = _width_rank(selected_width_class or roads.get("final_width_class") or roads.get("width_class"))

    if visual_road and visual_road.get("ok"):
        return {
            **base,
            "method": visual_road.get("road_connection_type") or visual_road.get("method") or "수동도로 접도 확인",
            "grade": visual_road.get("grade") or "F",
            "via_parcels": visual_road.get("via_parcels") or [],
            "selected_access_improvement": bool(visual_road.get("selected_access_improvement")),
            "manual_visual_road": True,
            "manual_road_applied_to_score": visual_road.get("manual_road_applied_to_score"),
            "manual_road_touching_parcel_ids": visual_road.get("manual_road_touching_parcel_ids") or [],
            "road_contact_point": (visual_road.get("points") or [None])[0],
        }
        visual_rank = _width_rank(visual_road.get("width_class"))
        distance = visual_road.get("distance_m")
        if distance is not None and distance <= 10:
            grade = "A" if visual_rank >= 10 else ("B" if visual_rank >= 6 else "D" if visual_rank >= 4 else "E")
            method = "위성사진 수동 도로 직접 접도"
        elif distance is not None and distance <= 100:
            grade = "C" if visual_rank >= 6 else ("D" if visual_rank >= 4 else "E")
            method = "위성사진 수동 도로 근접"
        else:
            grade = "E" if visual_rank else "F"
            method = "위성사진 수동 도로 수동확인"
        return {
            **base,
            "method": method,
            "grade": grade,
            "via_parcels": [],
            "selected_access_improvement": True,
            "manual_visual_road": True,
            "road_contact_point": (visual_road.get("points") or [None])[0],
        }

    if selected_contact:
        grade = "A" if width_rank >= 10 else ("B" if width_rank >= 6 else "D" if width_rank >= 4 else "E")
        return {
            **base,
            "method": "편입 후보 포함 직접 접도",
            "grade": grade,
            "via_parcels": selected_contact[:3],
            "selected_access_improvement": True,
            "selected_road_width_class": selected_width_class,
            "selected_road_contact_parcel_ids": [item.get("id") for item in selected_contact[:3]],
        }

    if selected_contribution:
        hop_count = min(3, len(selected_contribution))
        if hop_count == 1:
            method = "1필지 경유 접도"
            grade = "C" if width_rank >= 6 else "D"
        elif hop_count == 2:
            method = "2필지 경유 접도"
            grade = "D"
        else:
            method = "3필지 경유 접도"
            grade = "E"
        return {
            **base,
            "method": method,
            "grade": grade,
            "via_parcels": selected_contribution[:3],
            "selected_access_improvement": True,
            "selected_road_width_class": selected_width_class,
            "selected_road_contact_parcel_ids": [item.get("id") for item in selected_contribution[:3]],
        }

    return base or {"method": "접도 불명확", "grade": "F", "via_parcels": []}


def _apply_selected_parcel_road_context(selected: List[Dict[str, Any]], roads: Dict[str, Any]) -> Dict[str, Any]:
    candidates = roads.get("candidates") or []
    touched_ids: List[Any] = []
    best_width_class = None
    best_width_rank = -1
    best_distance = None
    for parcel in selected:
        polygon = parcel.get("polygon") or []
        if len(polygon) < 3:
            continue
        nearest = _nearest_road_candidate_for_polygon(polygon, candidates)
        if not nearest:
            continue
        distance, candidate = nearest
        width_class = candidate.get("width_class")
        parcel["nearest_road_distance_m"] = round(distance, 1)
        if width_class:
            parcel["selected_road_width_class"] = width_class
        if distance <= 5:
            parcel["has_road_contact"] = True
            parcel["road_connection_contribution"] = True
            touched_ids.append(parcel.get("id"))
        elif distance <= 100:
            parcel["road_connection_contribution"] = True
        width_rank = _width_rank(width_class)
        if width_rank > best_width_rank or (width_rank == best_width_rank and (best_distance is None or distance < best_distance)):
            best_width_rank = width_rank
            best_width_class = width_class
            best_distance = distance
    return {
        "selected_road_contact_applied": bool(touched_ids),
        "selected_road_width_class": best_width_class,
        "selected_road_distance_m": round(best_distance, 1) if best_distance is not None else None,
        "selected_road_contact_parcel_ids": touched_ids,
    }


def _nearest_road_candidate_for_polygon(
    polygon: List[Dict[str, float]], candidates: List[Dict[str, Any]]
) -> Optional[Tuple[float, Dict[str, Any]]]:
    best = None
    for candidate in candidates:
        distance = road_tools.distance_site_to_compact(polygon, candidate.get("geometry") or {})
        if distance is None:
            continue
        if best is None or distance < best[0]:
            best = (float(distance), candidate)
    return best


def _best_selected_road_width_class(selected: List[Dict[str, Any]]) -> Optional[str]:
    best_width = None
    best_rank = -1
    for parcel in selected:
        if not (parcel.get("has_road_contact") or parcel.get("road_connection_contribution")):
            continue
        width_class = parcel.get("selected_road_width_class")
        rank = _width_rank(width_class)
        if rank > best_rank:
            best_rank = rank
            best_width = width_class
    return best_width


def _manual_visual_road_metrics(
    manual_road: Any,
    main_parcel: Dict[str, Any],
    selected: List[Dict[str, Any]],
    adjacent: List[Dict[str, Any]],
    parcel_center: Dict[str, Any],
    manual: ManualInputs | None,
) -> Dict[str, Any]:
    if not isinstance(manual_road, dict):
        return {"ok": False}
    road_input = dict(manual_road)
    if not road_input.get("width_class"):
        road_input["width_class"] = _manual_width_class(manual)
    tolerance_m = _number(road_input.get("tolerance_m"), 5) or 5
    return road_tools.calculate_road_score_from_manual_road(
        road_input,
        main_parcel,
        selected,
        adjacent,
        tolerance_m=tolerance_m,
    )
    points = [
        {"lat": _number(point.get("lat"), None), "lng": _number(point.get("lng"), None)}
        for point in manual_road.get("points") or []
        if isinstance(point, dict)
    ]
    points = [point for point in points if point["lat"] is not None and point["lng"] is not None]
    if len(points) < 2:
        return {"ok": False}
    distance = geometry.distance_polygon_to_line_m(polygon, points) if polygon else None
    if distance is None and parcel_center:
        distance = geometry.point_to_line_distance_m(parcel_center, points)
    width_class = _manual_width_class(manual)
    road_type = "농로추정" if width_class == "농로" else "위성사진수동도로"
    return {
        "ok": True,
        "source": "카카오 스카이뷰/하이브리드 수동 도로",
        "points": points,
        "distance_m": _round_or_none(distance),
        "width_class": width_class,
        "road_type": road_type,
        "confidence": "수동마킹",
    }


def _score_visual_road(visual: Dict[str, Any]) -> Tuple[float, str]:
    if "road_score_20" in visual:
        return float(visual.get("road_score_20") or 0), visual.get("message") or "수동마킹 도로 접도 판정 결과를 도로점수에 우선 반영했습니다."
    width_rank = _width_rank(visual.get("width_class"))
    distance = visual.get("distance_m")
    if visual.get("road_type") == "농로추정":
        return 0, "위성사진 수동 판독 결과 농로 또는 비포장로는 개발 진입도로로 보지 않아 도로 점수에서 제외했습니다."
    if distance is None:
        return 6, "위성사진 수동 도로를 표시했지만 거리는 수동확인이 필요합니다."
    if distance <= 10:
        if width_rank >= 10:
            return 20, "위성사진 수동 10m 이상 도로 직접 접도 가능성을 반영했습니다."
        if width_rank >= 6:
            return 15, "위성사진 수동 6m 이상 도로 직접 접도 가능성을 반영했습니다."
        if width_rank >= 4:
            return 5, "위성사진 수동 4m 이상 도로는 대형 공사차량 진입이 제한적인 조건으로 반영했습니다."
        return 8, "위성사진 수동 도로 직접 접도 가능성은 있으나 폭원 미확인입니다."
    if distance <= 50:
        if width_rank >= 10:
            return 17, "위성사진 수동 10m 이상 도로가 50m 이내입니다."
        if width_rank >= 6:
            return 15, "위성사진 수동 6m 이상 도로가 50m 이내입니다."
        if width_rank >= 4:
            return 5, "위성사진 수동 4m 이상 도로가 50m 이내이나 제한적으로 반영했습니다."
        return 7, "위성사진 수동 도로가 50m 이내이나 폭원 미확인입니다."
    if distance <= 100:
        if width_rank >= 6:
            return 11, "위성사진 수동 6m 이상 도로가 100m 이내입니다."
        if width_rank >= 4:
            return 5, "위성사진 수동 4m 이상 도로가 100m 이내이나 제한적으로 반영했습니다."
        return 5, "위성사진 수동 도로가 100m 이내이나 폭원 미확인입니다."
    return 4, "위성사진 수동 도로와 부지 간 거리가 있어 접도 보완 확인이 필요합니다."


def _category(key: str, score: Optional[float], reason: str) -> Dict[str, Any]:
    rendered_score = None if score is None else round(float(score), 1)
    return {"key": key, "label": CATEGORY_LABELS[key], "max": CATEGORY_MAX[key], "score": rendered_score, "reason": reason}


def _grade(total: float) -> Tuple[str, str]:
    if total >= 85:
        return "A", "최우선 현장답사"
    if total >= 70:
        return "B", "우선 검토"
    if total >= 55:
        return "C", "보류 후 추가확인"
    return "D", "낮은 우선순위"


def _decision_label(grade: str) -> str:
    return {"A": "우선검토", "B": "검토가능", "C": "추가확인", "D": "낮은 우선순위"}.get(
        str(grade or "").upper(),
        "미확인",
    )


def _strengths(categories: List[Dict[str, Any]], metrics: Dict[str, Any]) -> List[str]:
    strengths = [
        f"{item['label']} 점수가 양호합니다."
        for item in categories
        if item.get("score") is not None and item["score"] / item["max"] >= 0.75
    ]
    official = _number(metrics.get("official_location_bonus"), 0) or 0
    if official >= 10:
        strengths.append("정책입지 가·감점이 매우 강한 가점구간입니다.")
    elif official >= 5:
        strengths.append("정책입지 가·감점이 의미 있는 가점구간입니다.")
    exposure_500m = metrics.get("residential_exposure_500m")
    if exposure_500m is not None and exposure_500m <= 30:
        strengths.append("500m 기준 주거노출이 낮아 민원 리스크 관리에 유리합니다.")
    if (metrics.get("slope_score_5") or 0) >= 5:
        strengths.append("경사도 15도 이하 구간으로 부지조성 측면에서 양호합니다.")
    if (metrics.get("effective_access_path") or {}).get("grade") in {"A", "B", "C"}:
        strengths.append("직접 접도 또는 편입 후보를 통한 도로 연결 구조가 비교적 좋습니다.")
    return strengths[:6] or ["자동조회와 수동마킹 값을 보강하면 후보지 판단이 더 명확해집니다."]


def _weaknesses(categories: List[Dict[str, Any]], metrics: Dict[str, Any], penalties: List[Dict[str, Any]]) -> List[str]:
    weaknesses = [
        f"{item['label']} 점수가 낮아 추가 확인이 필요합니다."
        for item in categories
        if item.get("score") is not None and item["score"] / item["max"] <= 0.35
    ]
    weaknesses.extend(item.get("reason") for item in penalties if item.get("reason"))
    overlay_reasons = [
        item.get("reason")
        for item in (metrics.get("overlay_regulation_penalty_items") or [])
        if item.get("reason")
    ]
    for reason in reversed(overlay_reasons):
        weaknesses.insert(0, f"중첩 규제구역 확인: {reason}")
    for item in reversed(metrics.get("overlay_regulation_manual_check_items") or []):
        weaknesses.insert(0, item)
    if metrics.get("greenbelt_detected"):
        weaknesses.insert(0, "개발제한구역 중첩 — 대규모 데이터센터 개발 중대 제한으로 최종판정을 낮췄습니다.")
    elif metrics.get("greenbelt_status") == "미확인":
        weaknesses.append("개발제한구역 미확인 상태이므로 토지이용계획확인원 확인이 필요합니다.")
    if metrics.get("is_forest"):
        weaknesses.append("지목이 임야인 필지가 있어 산지전용·다드림 확인이 필요합니다.")
    return weaknesses[:8] or ["MVP 자동조회만으로는 제한사항을 확정할 수 없으므로 관계기관 확인이 필요합니다."]


def _next_checks(metrics: Dict[str, Any]) -> List[str]:
    checks = [
        "한전 계통연계 가능용량, 실제 전압, 소유, 접속점 후보를 확인하세요.",
        "정책입지 CSV 값은 실제 지침서·통계자료로 교체해 검증하세요.",
        "전력자립도는 내부 5점으로 약하게 반영한 참고 지표이므로 공식 자료 기준연도를 확인하세요.",
        "민가밀집은 건물 수 기반 1차 지표이므로 실제 주거 여부와 주민수용성을 현장 확인하세요.",
        "도로폭, 회전반경, 대형 공사차량 진입 가능성은 현장과 지자체 도로대장으로 확인하세요.",
        "토지이음에서 용도지역·지구·구역 및 행위제한을 최종 확인하세요.",
        "경사도는 현장측량과 토목설계 검토가 필요합니다.",
    ]
    if metrics.get("is_forest"):
        checks.append("임야 또는 산지 가능성이 있어 다드림 산지정보 확인이 필요합니다.")
    for item in metrics.get("overlay_regulation_hold_reasons") or []:
        checks.insert(0, f"중첩 규제구역 확인 필요: {item}")
    for item in metrics.get("overlay_regulation_manual_check_items") or []:
        checks.insert(0, item)
    if metrics.get("greenbelt_detected") or metrics.get("greenbelt_status") == "미확인":
        checks.append("토지이용계획확인원에서 개발제한구역 등 중첩 규제구역을 최종 확인하세요.")
    if metrics.get("reference_facility_manual_check"):
        checks.insert(0, "요양시설·마을회관·소규모 종교시설 등 주민수용성 참고시설은 공사동선과 민원 가능성을 수동 확인하세요.")
    return checks[:9]


def _power_axis_geometry_profile(
    site_polygons: List[List[Dict[str, float]]],
    anchor_point: Dict[str, Any],
    tower_points: List[Dict[str, float]],
) -> Dict[str, Any]:
    if not tower_points:
        return {
            "relation": "no_marking",
            "relation_label": "수동마킹 없음",
            "distance_basis": "미적용",
            "nearest_tower_distance_from_anchor_m": None,
            "nearest_tower_distance_from_site_boundary_m": None,
            "line_distance_from_anchor_m": None,
            "line_distance_from_site_boundary_m": None,
            "distance_from_anchor_m": None,
            "distance_from_site_boundary_m": None,
            "applied_distance_m": None,
            "line_crosses_site": False,
            "tower_inside_site": False,
            "axis_boundary_touch": False,
            "needs_safety_review": False,
        }

    nearest_tower_anchor = _nearest_point_distance(anchor_point, tower_points) if anchor_point else None
    line_anchor = (
        geometry.point_to_line_distance_m(anchor_point, tower_points)
        if anchor_point and len(tower_points) >= 2
        else None
    )
    anchor_distances = [value for value in [nearest_tower_anchor, line_anchor] if value is not None]
    distance_from_anchor = min(anchor_distances) if anchor_distances else None

    nearest_tower_boundary = _nearest_site_polygon_point_distance(site_polygons, tower_points)
    line_boundary = _nearest_site_polygon_line_distance(site_polygons, tower_points) if len(tower_points) >= 2 else None
    boundary_distances = [value for value in [nearest_tower_boundary, line_boundary] if value is not None]
    distance_from_boundary = min(boundary_distances) if boundary_distances else None
    applied_distance = distance_from_boundary if distance_from_boundary is not None else distance_from_anchor
    distance_basis = "부지경계" if distance_from_boundary is not None else "기준점 임시"

    line_crosses = len(tower_points) >= 2 and _line_crosses_any_site(site_polygons, tower_points)
    tower_inside = _tower_inside_any_site(site_polygons, tower_points)
    line_boundary_touch = len(tower_points) >= 2 and _line_touches_any_site_boundary(site_polygons, tower_points)
    tower_boundary_touch = _tower_on_any_site_boundary(site_polygons, tower_points)
    axis_boundary_touch = line_boundary_touch or tower_boundary_touch

    if line_crosses:
        relation = "line_crosses_site"
    elif tower_inside:
        relation = "tower_inside_site"
    elif line_boundary_touch:
        relation = "line_touches_boundary"
    elif tower_boundary_touch:
        relation = "tower_on_boundary"
    else:
        relation = _power_axis_relation_from_distance(applied_distance)

    return {
        "relation": relation,
        "relation_label": _power_axis_relation_label(relation),
        "distance_basis": distance_basis,
        "nearest_tower_distance_from_anchor_m": nearest_tower_anchor,
        "nearest_tower_distance_from_site_boundary_m": nearest_tower_boundary,
        "line_distance_from_anchor_m": line_anchor,
        "line_distance_from_site_boundary_m": line_boundary,
        "distance_from_anchor_m": distance_from_anchor,
        "distance_from_site_boundary_m": distance_from_boundary,
        "applied_distance_m": applied_distance,
        "line_crosses_site": line_crosses,
        "tower_inside_site": tower_inside,
        "axis_boundary_touch": axis_boundary_touch,
        "needs_safety_review": relation in {
            "line_crosses_site",
            "tower_inside_site",
            "line_touches_boundary",
            "tower_on_boundary",
        },
    }


def _nearest_site_polygon_point_distance(
    site_polygons: List[List[Dict[str, float]]], points: List[Dict[str, float]]
) -> Optional[float]:
    distances = []
    for polygon in site_polygons:
        distances.extend(
            distance
            for distance in (geometry.distance_point_to_polygon_m(point, polygon) for point in points)
            if distance is not None
        )
    return min(distances) if distances else None


def _nearest_site_polygon_line_distance(
    site_polygons: List[List[Dict[str, float]]], line: List[Dict[str, float]]
) -> Optional[float]:
    distances = [geometry.distance_polygon_to_line_m(polygon, line) for polygon in site_polygons]
    distances = [distance for distance in distances if distance is not None]
    return min(distances) if distances else None


def _tower_inside_any_site(site_polygons: List[List[Dict[str, float]]], points: List[Dict[str, float]]) -> bool:
    try:
        if geometry.Polygon and geometry.Point:
            for polygon in site_polygons:
                poly = geometry.Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in polygon])
                for point in points:
                    projected = geometry.Point(*geometry.to_projected(point["lng"], point["lat"]))
                    if poly.contains(projected):
                        return True
    except Exception:
        pass
    return False


def _tower_on_any_site_boundary(
    site_polygons: List[List[Dict[str, float]]], points: List[Dict[str, float]], tolerance_m: float = 5
) -> bool:
    try:
        if geometry.Polygon and geometry.Point:
            for polygon in site_polygons:
                poly = geometry.Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in polygon])
                for point in points:
                    projected = geometry.Point(*geometry.to_projected(point["lng"], point["lat"]))
                    if not poly.contains(projected) and projected.distance(poly.boundary) <= tolerance_m:
                        return True
    except Exception:
        pass
    return False


def _line_crosses_any_site(site_polygons: List[List[Dict[str, float]]], line: List[Dict[str, float]]) -> bool:
    try:
        if geometry.Polygon and geometry.LineString:
            projected_line = geometry.LineString([geometry.to_projected(p["lng"], p["lat"]) for p in line])
            for polygon in site_polygons:
                poly = geometry.Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in polygon])
                if projected_line.crosses(poly) or projected_line.within(poly):
                    return True
                if projected_line.intersects(poly) and not projected_line.touches(poly):
                    return True
    except Exception:
        pass
    return False


def _line_touches_any_site_boundary(
    site_polygons: List[List[Dict[str, float]]], line: List[Dict[str, float]], tolerance_m: float = 5
) -> bool:
    try:
        if geometry.Polygon and geometry.LineString:
            projected_line = geometry.LineString([geometry.to_projected(p["lng"], p["lat"]) for p in line])
            for polygon in site_polygons:
                poly = geometry.Polygon([geometry.to_projected(p["lng"], p["lat"]) for p in polygon])
                if projected_line.touches(poly) or projected_line.distance(poly.boundary) <= tolerance_m:
                    return True
    except Exception:
        pass
    return False


def _power_axis_relation_from_distance(distance: Optional[float]) -> str:
    if distance is None:
        return "over_500m"
    if distance <= 50:
        return "within_50m"
    if distance <= 150:
        return "within_150m"
    if distance <= 500:
        return "within_500m"
    return "over_500m"


def _power_axis_profile_location_score(profile: Dict[str, Any]) -> int:
    relation_scores = {
        "line_crosses_site": 20,
        "tower_inside_site": 20,
        "line_touches_boundary": 20,
        "tower_on_boundary": 20,
        "within_50m": 15,
        "within_150m": 10,
        "within_500m": 5,
        "over_500m": 2,
        "no_marking": 0,
    }
    return relation_scores.get(str(profile.get("relation") or "no_marking"), 0)


def _power_axis_improved_by_selected_site(
    main_profile: Dict[str, Any], selected_profile: Dict[str, Any], selected: List[Dict[str, Any]]
) -> bool:
    if not selected:
        return False
    if _power_axis_profile_location_score(selected_profile) > _power_axis_profile_location_score(main_profile):
        return True
    main_distance = main_profile.get("applied_distance_m")
    selected_distance = selected_profile.get("applied_distance_m")
    if main_distance is None or selected_distance is None:
        return False
    return float(selected_distance) + 0.5 < float(main_distance)


def _power_axis_relation_label(relation: str) -> str:
    return {
        "line_crosses_site": "송전선 후보축 부지 내부통과",
        "tower_inside_site": "송전탑 후보 부지 내부",
        "line_touches_boundary": "송전선 후보축 경계접함",
        "tower_on_boundary": "송전탑 후보 경계접함",
        "within_50m": "부지경계 50m 이내",
        "within_150m": "부지경계 50~150m",
        "within_500m": "부지경계 150~500m",
        "over_500m": "부지경계 500m 초과",
        "no_marking": "수동마킹 없음",
    }.get(relation, relation or "-")


def _power_axis_reason(relation: str, distance: Optional[float], basis: Optional[str]) -> str:
    if relation in {"line_crosses_site", "tower_inside_site", "line_touches_boundary", "tower_on_boundary"}:
        return (
            "송전탑 또는 송전선 후보축이 부지 내부 또는 경계부에 있어 전력축 인접성은 매우 우수하게 평가했습니다. "
            "다만 선하지, 안전거리, 점용, 이설 가능성, 보호구역, 전자파 민원, 한전 협의 및 계통연계 검토가 필요합니다."
        )
    if relation == "within_50m":
        return f"{basis or '부지경계'} 기준 50m 이내로 우수한 전력축 인접성으로 평가했습니다."
    if relation == "within_150m":
        return f"{basis or '부지경계'} 기준 50~150m 이내로 검토 가능한 전력축 인접성으로 평가했습니다."
    if relation == "within_500m":
        return (
            "송전탑·송전선 후보가 150m 초과 500m 이내에 있어 참고 가능한 전력축 인접성은 있으나, "
            "부지 내부 또는 경계부 인접 수준의 강한 점수로 보지는 않았습니다."
        )
    if relation == "over_500m":
        return "송전탑·송전선 후보가 500m를 초과하여 강한 전력축 인접성으로 보지 않았습니다."
    if distance is not None:
        return f"{basis or '기준점'} 기준 전력축 후보 거리 {round(distance, 1)}m를 반영했습니다."
    return "송전탑·송전선 후보 거리 산정값이 없어 전력축 위치점수를 낮게 처리했습니다."


def _nearest_point_distance(point: Dict[str, Any], candidates: List[Dict[str, float]]) -> Optional[float]:
    if not point or not candidates:
        return None
    distances = [geometry.haversine_distance_m(point["lat"], point["lng"], item["lat"], item["lng"]) for item in candidates]
    return min(distances) if distances else None


def _nearest_polygon_distance(polygon: List[Dict[str, float]], candidates: List[Dict[str, float]]) -> Optional[float]:
    distances = [geometry.distance_point_to_polygon_m(item, polygon) for item in candidates]
    distances = [distance for distance in distances if distance is not None]
    return min(distances) if distances else None


def _tower_to_dict(tower: TowerCandidate | Dict[str, Any]) -> Dict[str, float]:
    if isinstance(tower, TowerCandidate):
        return {"lat": tower.lat, "lng": tower.lng}
    return {"lat": tower.get("lat"), "lng": tower.get("lng")}


def _has_latlng(value: Dict[str, Any]) -> bool:
    return isinstance(value.get("lat"), (int, float)) and isinstance(value.get("lng"), (int, float))


def _number(value: Any, default: Optional[float] = 0) -> Optional[float]:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(*values: Any) -> Optional[int]:
    for value in values:
        number = _number(value, None)
        if number is not None:
            return int(number)
    return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _number(value, default=None)
        if number is not None:
            return number
    return None


def _round_or_none(value: Optional[float]) -> Optional[float]:
    return round(value, 1) if value is not None else None


def _zoning_text(zoning: Dict[str, Any], permit: Dict[str, Any], extra_zoning_values: Optional[List[str]] = None) -> str:
    parts = [zoning.get("main_zoning"), *(zoning.get("names") or []), *(permit.get("land_use_districts") or [])]
    parts.extend(extra_zoning_values or [])
    return " ".join(str(value or "") for value in parts)


def _zoning_evaluation_entries(
    main_parcel: Dict[str, Any],
    zoning: Dict[str, Any],
    permit: Dict[str, Any],
    selected_incorporation: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    base_zoning = zoning.get("main_zoning") or " ".join(zoning.get("names") or []) or "미확인"
    entries = [
        {
            "scope": "기준 필지",
            "parcel_id": str(main_parcel.get("id") or main_parcel.get("pnu") or ""),
            "zoning": base_zoning or "미확인",
            "area_m2": main_parcel.get("area_m2"),
        }
    ]
    for index, parcel in enumerate(selected_incorporation, start=1):
        entries.append(
            {
                "scope": f"추가필지 {index}",
                "parcel_id": str(parcel.get("id") or parcel.get("pnu") or index),
                "zoning": str(parcel.get("zoning") or parcel.get("manual_zoning") or "미확인"),
                "area_m2": parcel.get("area_m2"),
            }
        )
    return entries


def _zoning_flags(text: str) -> Dict[str, bool]:
    return {
        "greenbelt": "개발제한" in text,
        "agricultural": "농림" in text,
        "conservation_or_production": "보전관리" in text or "생산관리" in text,
    }


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _fragmentation_profile(development_parcel_count: Any) -> Dict[str, Any]:
    count = int(_number(development_parcel_count, 0) or 0)
    notice = "필지 수는 권리관계 정리 난이도 참고값이며, 실제 매입 가능성은 소유자 수, 협의 가능성, 지분관계 확인이 필요합니다. 대면적 후보지 기준에서 1~7필지는 양호한 범위로 봅니다."
    if count <= 7:
        return {"penalty": 0, "fatal_cap": None, "judgement": f"선택 개발부지 필지 수가 {count}개로 양호합니다. {notice}"}
    if count <= 15:
        return {"penalty": 1, "fatal_cap": None, "judgement": f"선택 개발부지 필지 수가 {count}개로 권리관계 확인이 필요합니다. {notice}"}
    if count <= 30:
        return {"penalty": 3, "fatal_cap": None, "judgement": f"선택 개발부지 필지 수가 {count}개로 협의 난이도가 증가합니다. {notice}"}
    if count <= 50:
        return {"penalty": 5, "fatal_cap": None, "judgement": f"선택 개발부지 필지 수가 {count}개로 권리관계가 복잡한 구간입니다. {notice}"}
    return {"penalty": 8, "fatal_cap": None, "judgement": f"선택 개발부지 필지 수가 {count}개 이상으로 강한 확인이 필요합니다. {notice}"}


def _candidate_building_use(props: Dict[str, Any]) -> str:
    lower = {str(key).lower(): value for key, value in props.items()}
    keys = [
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
    ]
    for key in keys:
        value = props.get(key, lower.get(key.lower()))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _residential_use_weight(building_use: str) -> float:
    text = str(building_use or "")
    if _is_sensitive_facility_use(text):
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


def _is_sensitive_facility_use(building_use: str) -> bool:
    return any(
        keyword in str(building_use or "")
        for keyword in [
            "학교",
            "병원",
            "요양",
            "어린이집",
            "유치원",
            "보육",
            "의료",
            "어린이공원",
            "노인복지",
            "마을회관",
            "경로당",
            "노인정",
            "교회",
            "성당",
            "사찰",
            "종교",
            "근린",
        ]
    )


def _is_residential_like_use(building_use: str) -> bool:
    text = str(building_use or "")
    return any(keyword in text for keyword in ["단독주택", "공동주택", "다가구", "다세대", "연립", "아파트", "상가주택"])


def _is_residential_complex_text(text: str) -> bool:
    return any(
        keyword in str(text or "")
        for keyword in ["아파트", "주공", "자이", "푸르지오", "래미안", "힐스테이트", "e편한세상", "더샵", "롯데캐슬", "마을", "단지", "빌라", "연립", "다세대", "공동주택"]
    )


def _residential_complex_match_profile(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    lowered = value.lower()
    if not value:
        return {"match": False, "confidence": "낮음", "reason": "명칭 없음"}

    excluded = [
        "마을회관",
        "경로당",
        "노인정",
        "창고",
        "축사",
        "비닐하우스",
        "공장",
        "주유소",
        "충전소",
        "공동묘지",
        "묘지",
        "사찰",
        "절",
        "농가",
        "농업",
        "농장",
        "마을입구",
        "마을길",
    ]
    if any(keyword in value for keyword in excluded):
        return {"match": False, "confidence": "낮음", "reason": "대규모 주거단지 제외 키워드"}

    strong = [
        "아파트",
        "공동주택",
        "주공",
        "자이",
        "푸르지오",
        "래미안",
        "힐스테이트",
        "e편한세상",
        "이편한세상",
        "더샵",
        "롯데캐슬",
        "아이파크",
        "두산위브",
        "apt",
    ]
    if any(keyword.lower() in lowered for keyword in strong):
        return {"match": True, "confidence": "높음", "reason": "명확한 아파트·공동주택단지 키워드"}

    medium = ["연립주택", "다세대주택", "빌라단지", "주택단지", "공동주택단지"]
    if any(keyword in value for keyword in medium):
        return {"match": True, "confidence": "중간", "reason": "공동주택 성격 키워드"}

    return {"match": False, "confidence": "낮음", "reason": "마을명 또는 일반 시설명은 대규모 주거단지로 보지 않음"}


def _is_low_residential_confidence(confidence: Any) -> bool:
    text = str(confidence or "").lower()
    return not text or "낮" in text or "low" in text or "불명확" in text or "??" in text


def _candidate_place_text(item: Dict[str, Any]) -> str:
    props = item.get("properties") or {}
    return " ".join(
        str(value or "")
        for value in [
            item.get("name"),
            item.get("building_use"),
            item.get("category"),
            props.get("BD_NM"),
            props.get("buld_nm"),
            props.get("BULD_NM"),
            props.get("A1"),
            props.get("A5"),
            props.get("A6"),
        ]
    )


def _normalize_place_item(item: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    lat = _number(item.get("lat"), None)
    lng = _number(item.get("lng"), None)
    distance = _number(item.get("distance_m"), None)
    if lat is None or lng is None or distance is None:
        return None
    text = _candidate_place_text(item)
    return {
        "id": str(item.get("id") or f"{item.get('name') or text}:{lat:.6f}:{lng:.6f}"),
        "name": item.get("name") or item.get("building_use") or item.get("keyword") or "후보",
        "type": item.get("type") or ("sensitive" if _is_sensitive_facility_use(text) else "complex"),
        "category": item.get("category") or item.get("building_use"),
        "lat": lat,
        "lng": lng,
        "distance_m": round(distance, 1),
        "source": item.get("source") or source,
    }


def _add_seen(item: Dict[str, Any], seen: set[str]) -> bool:
    key = str(item.get("id") or f"{item.get('name')}:{item.get('lat')}:{item.get('lng')}")
    if key in seen:
        return False
    seen.add(key)
    return True


def _confidence_from_ratio(ratio: float) -> str:
    if ratio >= 0.7:
        return "높음"
    if ratio >= 0.3:
        return "중간"
    return "낮음"


def _residential_profile(building_counts: Dict[str, Any], residential_exposure: Dict[str, Any]) -> Dict[str, Any]:
    exposure = residential_exposure.get("exposure") or {}
    confidence = residential_exposure.get("confidence") or "낮음"
    value_500m = _number(exposure.get("500m"), None)
    if value_500m is None:
        base_score = 5
        level = "수동확인"
        judgement = "500m 주거노출지수 자동조회 실패로 수동확인이 필요합니다."
    elif value_500m <= 30:
        base_score = 10
        level = "낮음"
        judgement = "500m 이내 주거노출이 낮아 민원 리스크가 낮은 후보지로 평가됩니다."
    elif value_500m <= 70:
        base_score = 8
        level = "보통"
        judgement = "500m 이내 주거노출이 보통 수준이며 실제 주거 여부는 현장확인이 필요합니다."
    elif value_500m <= 150:
        base_score = 6
        level = "주의"
        judgement = "500m 이내 주거노출이 다소 있어 민원 리스크 검토가 필요합니다."
    elif value_500m <= 300:
        base_score = 4
        level = "높음"
        judgement = "500m 이내 주거노출이 높은 편으로 주민수용성 검토가 필요합니다."
    elif value_500m <= 500:
        base_score = 2
        level = "매우 높음"
        judgement = "500m 이내 주거노출이 높아 민원·보상·주민수용성 리스크를 주의해야 합니다."
    else:
        base_score = 0
        level = "과밀"
        judgement = "500m 이내 주거노출이 매우 높아 후보지 우선순위 판단 시 별도 검토가 필요합니다."

    candidates = calculate_residential_penalty_candidates(exposure)
    applied = calculate_residential_penalty_applied(candidates)
    not_applied_reason = ""
    if _is_low_residential_confidence(confidence) and (applied.get("penalty") or 0) > 0:
        not_applied_reason = "건물 용도 구분 신뢰도가 낮아 근거리 건물 수 감점은 자동 적용하지 않고 수동확인 대상으로 표시했습니다."
        applied = {"radius": applied.get("radius"), "penalty": 0, "fatal_cap": None, "judgement": not_applied_reason}

    return {
        "level_500m": level,
        "base_score": base_score,
        "exposure_150m": exposure.get("150m"),
        "exposure_250m": exposure.get("250m"),
        "exposure_350m": exposure.get("350m"),
        "exposure_500m": exposure.get("500m"),
        "confidence": confidence,
        "penalty_150m": candidates["150m"]["penalty"],
        "penalty_250m": candidates["250m"]["penalty"],
        "penalty_350m": candidates["350m"]["penalty"],
        "penalty_500m": candidates["500m"]["penalty"],
        "proximity_penalty_applied": applied.get("penalty", 0),
        "proximity_penalty_radius": applied.get("radius"),
        "proximity_fatal_cap": calculate_residential_fatal_cap(applied),
        "judgement": judgement,
        "penalty_judgement": applied.get("judgement") or "",
        "penalty_not_applied_reason": not_applied_reason,
    }

    exposure = residential_exposure.get("exposure") or {}
    value_500m = _number(exposure.get("500m"), None)
    if value_500m is None:
        base_score = 5
        level = "수동확인"
        judgement = "500m 주거노출지수 자동조회 실패로 수동확인이 필요합니다."
    elif value_500m <= 20:
        base_score = 10
        level = "낮음"
        judgement = "주변 주거노출이 낮아 민원 리스크가 낮은 후보지로 평가됩니다."
    elif value_500m <= 50:
        base_score = 8
        level = "보통"
        judgement = "주변 주거노출이 일부 존재하므로 현장확인이 필요합니다."
    elif value_500m <= 100:
        base_score = 5
        level = "주의"
        judgement = "주변 주거노출이 높아 데이터센터 입지로서 주민수용성 리스크가 큽니다."
    elif value_500m <= 200:
        base_score = 2
        level = "높음"
        judgement = "주변 주거노출이 높아 데이터센터 입지로서 주민수용성 리스크가 큽니다."
    else:
        base_score = 0
        level = "과밀"
        judgement = "주변 주거노출이 매우 높아 데이터센터 입지로서 주민수용성 리스크가 큽니다."

    candidates = calculate_residential_penalty_candidates(exposure)
    applied = calculate_residential_penalty_applied(candidates)
    return {
        "level_500m": level,
        "base_score": base_score,
        "exposure_150m": exposure.get("150m"),
        "exposure_250m": exposure.get("250m"),
        "exposure_350m": exposure.get("350m"),
        "exposure_500m": exposure.get("500m"),
        "confidence": residential_exposure.get("confidence") or "낮음",
        "penalty_150m": candidates["150m"]["penalty"],
        "penalty_250m": candidates["250m"]["penalty"],
        "penalty_350m": candidates["350m"]["penalty"],
        "penalty_500m": candidates["500m"]["penalty"],
        "proximity_penalty_applied": applied.get("penalty", 0),
        "proximity_penalty_radius": applied.get("radius"),
        "proximity_fatal_cap": calculate_residential_fatal_cap(applied),
        "judgement": judgement,
        "penalty_judgement": applied.get("judgement") or "",
    }


def _residential_radius_penalty(radius: str, count: Optional[float]) -> Dict[str, Any]:
    if count is None:
        return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
    if radius == "150m":
        if count <= 10:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 30:
            return {"radius": radius, "penalty": 5, "fatal_cap": None, "judgement": "150m 이내 직접 영향권의 주거노출이 일부 있어 확인이 필요합니다."}
        if count <= 60:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "150m 이내 직접 영향권의 주거노출이 높아 주민수용성 검토가 필요합니다."}
        return {"radius": radius, "penalty": 20, "fatal_cap": 75, "judgement": "150m 이내 직접 영향권의 주거노출이 매우 높아 상한을 적용했습니다."}
    if radius == "250m":
        if count <= 30:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 80:
            return {"radius": radius, "penalty": 5, "fatal_cap": None, "judgement": "250m 이내 근거리 영향권의 주거노출이 일부 있어 확인이 필요합니다."}
        if count <= 150:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "250m 이내 근거리 영향권의 주거노출이 높아 주민수용성 검토가 필요합니다."}
        return {"radius": radius, "penalty": 20, "fatal_cap": 78, "judgement": "250m 이내 근거리 영향권의 주거노출이 매우 높아 상한을 적용했습니다."}
    if radius == "350m":
        if count <= 80:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 180:
            return {"radius": radius, "penalty": 5, "fatal_cap": None, "judgement": "350m 이내 생활권 영향권의 주거노출이 일부 있어 확인이 필요합니다."}
        if count <= 350:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "350m 이내 생활권 영향권의 주거노출이 높아 입지 리스크로 반영했습니다."}
        return {"radius": radius, "penalty": 20, "fatal_cap": 82, "judgement": "350m 이내 생활권 영향권의 주거노출이 매우 높아 상한을 적용했습니다."}
    if count <= 150:
        return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
    if count <= 350:
        return {"radius": radius, "penalty": 5, "fatal_cap": None, "judgement": "500m 이내 주거노출이 일부 있어 민원 리스크 확인이 필요합니다."}
    if count <= 700:
        return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "500m 이내 주거노출이 높아 민원 리스크 관리계획이 필요합니다."}
    return {"radius": radius, "penalty": 20, "fatal_cap": 85, "judgement": "500m 이내 주거노출이 매우 높아 상한을 적용했습니다."}

    if count is None:
        return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
    if radius == "150m":
        if count <= 3:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 10:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "150m 이내 직접 영향권에 주거노출이 있어 강한 민원 리스크로 반영했습니다."}
        if count <= 20:
            return {"radius": radius, "penalty": 20, "fatal_cap": None, "judgement": "150m 이내 직접 영향권에 주거노출이 높아 데이터센터 입지 리스크로 반영했습니다."}
        return {"radius": radius, "penalty": 35, "fatal_cap": 55, "judgement": "150m 이내 직접 영향권에 주거노출이 매우 높아 치명조건으로 반영했습니다."}
    if radius == "250m":
        if count <= 10:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 30:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "250m 이내 근거리 영향권에 주거노출이 있어 강한 민원 리스크로 반영했습니다."}
        if count <= 60:
            return {"radius": radius, "penalty": 20, "fatal_cap": None, "judgement": "250m 이내 근거리 영향권의 주거노출이 높아 주민수용성 리스크로 반영했습니다."}
        return {"radius": radius, "penalty": 35, "fatal_cap": 60, "judgement": "250m 이내 근거리 영향권의 주거노출이 매우 높아 치명조건으로 반영했습니다."}
    if radius == "350m":
        if count <= 30:
            return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
        if count <= 80:
            return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "350m 이내 생활권 영향권에 주거노출이 있어 민원 리스크로 반영했습니다."}
        if count <= 150:
            return {"radius": radius, "penalty": 20, "fatal_cap": None, "judgement": "350m 이내 생활권 영향권의 주거노출이 높아 데이터센터 입지 리스크로 반영했습니다."}
        return {"radius": radius, "penalty": 30, "fatal_cap": 65, "judgement": "350m 이내 생활권 영향권의 주거노출이 매우 높아 치명조건으로 반영했습니다."}
    if count <= 50:
        return {"radius": radius, "penalty": 0, "fatal_cap": None, "judgement": ""}
    if count <= 150:
        return {"radius": radius, "penalty": 10, "fatal_cap": None, "judgement": "500m 이내 주거노출이 높아 민원 리스크 관리계획이 필요합니다."}
    if count <= 300:
        return {"radius": radius, "penalty": 20, "fatal_cap": None, "judgement": "500m 이내 주거노출이 높아 데이터센터 입지 리스크로 반영했습니다."}
    return {"radius": radius, "penalty": 35, "fatal_cap": 65, "judgement": "500m 이내 주거노출이 매우 높아 치명조건으로 반영했습니다."}


def build_residential_judgement(residential: Dict[str, Any], context: Dict[str, Any]) -> str:
    parts = [str(residential.get("judgement") or "").strip()]
    if residential.get("penalty_judgement"):
        parts.append(str(residential["penalty_judgement"]).strip())
    if context.get("judgement"):
        parts.append(str(context["judgement"]).strip())
    if not parts:
        return "민가밀집은 건물 수 및 건물 용도 기반 1차 지표이며 현장확인이 필요합니다."
    return " ".join(part for part in parts if part)


def _largest_residential_cluster(candidates: List[Dict[str, Any]], radius_m: float) -> int:
    points = [
        item
        for item in candidates
        if _number(item.get("distance_m"), None) is not None
        and (_number(item.get("distance_m"), None) or 0) <= radius_m
        and item.get("lat") is not None
        and item.get("lng") is not None
    ]
    if not points:
        return 0
    parent = list(range(len(points)))

    def find(idx: int) -> int:
        while parent[idx] != idx:
            parent[idx] = parent[parent[idx]]
            idx = parent[idx]
        return idx

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, point in enumerate(points):
        for j in range(i + 1, len(points)):
            other = points[j]
            distance = geometry.haversine_distance_m(point["lat"], point["lng"], other["lat"], other["lng"])
            if distance <= 80:
                union(i, j)

    cluster_sizes: Dict[int, int] = {}
    for idx in range(len(points)):
        root = find(idx)
        cluster_sizes[root] = cluster_sizes.get(root, 0) + 1
    return max(cluster_sizes.values(), default=0)


def _residential_route_lines(
    tower_points: List[Dict[str, Any]],
    parcel_center: Optional[Dict[str, Any]],
    effective_access_path: Dict[str, Any],
) -> List[List[Dict[str, float]]]:
    lines: List[List[Dict[str, float]]] = []
    if len(tower_points) >= 2:
        lines.append([{"lat": float(item["lat"]), "lng": float(item["lng"])} for item in tower_points if _has_latlng(item)])

    access_points: List[Dict[str, float]] = []
    if parcel_center and _has_latlng(parcel_center):
        access_points.append({"lat": float(parcel_center["lat"]), "lng": float(parcel_center["lng"])})
    for parcel in effective_access_path.get("via_parcels") or []:
        centroid = parcel.get("centroid")
        if centroid and _has_latlng(centroid):
            access_points.append({"lat": float(centroid["lat"]), "lng": float(centroid["lng"])})
    road_point = effective_access_path.get("road_contact_point")
    if road_point and _has_latlng(road_point):
        access_points.append({"lat": float(road_point["lat"]), "lng": float(road_point["lng"])})
    if len(access_points) >= 2:
        lines.append(access_points)
    return lines


def _slope_profile(degree: Optional[float], raw_grade: Any = None, auto_ok: bool = False) -> Dict[str, Any]:
    if degree is None:
        grade = str(raw_grade or "")
        if grade in {"매우 양호", "낮음"}:
            return {"grade": "매우 양호", "base_score": 5, "penalty": 0, "fatal_cap": None, "judgement": "경사도가 완만한 구간으로 부지조성 측면에서 양호합니다."}
        if grade in {"보통", "중간"}:
            return {"grade": "보통", "base_score": 3, "penalty": 3, "fatal_cap": None, "judgement": "경사도는 보통 수준으로 일부 토목 보완이 필요할 수 있습니다."}
        if grade in {"불리", "높음"}:
            return {"grade": "불리", "base_score": 1, "penalty": 12, "fatal_cap": 70, "judgement": "경사도가 높은 구간으로 절성토·진입도로·부지조성 리스크가 큽니다."}
        return {
            "grade": "조건부 / 경사도 확인 필요",
            "base_score": None,
            "penalty": 0,
            "fatal_cap": None,
            "status": "unknown",
            "judgement": "DEM/등고선 자료를 읽지 못해 경사도 자동계산에 실패했습니다. 이는 부지 경사가 높다는 의미가 아니며, 현장측량 또는 수동확인이 필요합니다. 경사도 감점은 적용하지 않았습니다.",
        }
    if degree <= 15:
        return {"grade": "매우 양호", "base_score": 5, "penalty": 0, "fatal_cap": None, "judgement": "경사도가 15도 이하로 토목공사와 부지조성 측면에서 매우 양호한 후보지로 평가됩니다."}
    if degree <= 20:
        return {"grade": "보통", "base_score": 3, "penalty": 3, "fatal_cap": None, "judgement": "경사도가 15도를 초과하여 일부 토목 보완이 필요할 수 있습니다."}
    if degree <= 25:
        return {"grade": "불리", "base_score": 1, "penalty": 12, "fatal_cap": 70, "judgement": "경사도가 20도를 초과하여 절성토·진입도로·부지조성 리스크가 큽니다."}
    return {"grade": "최악", "base_score": 0, "penalty": 30, "fatal_cap": 55, "judgement": "경사도가 25도를 초과하여 데이터센터 부지조성 관점에서 최악 수준의 토목 리스크로 평가됩니다."}


def _manual_width_class(manual: ManualInputs | None) -> str:
    if not manual:
        return "폭원 미확인"
    if getattr(manual, "actual_road_10m", False):
        return "10m 이상"
    if getattr(manual, "actual_road_6m", False):
        return "6m 이상 10m 미만"
    if getattr(manual, "actual_road_4m", False):
        return "4m 이상 6m 미만"
    return "폭원 미확인"


def _width_rank(width_class: str | None) -> int:
    text = str(width_class or "").lower().replace(" ", "")
    if text.startswith("10"):
        return 10
    if text.startswith("6"):
        return 6
    if text.startswith("4"):
        return 4
    if "농로" in text:
        return 1
    return 0
