from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import geometry


SENSITIVE_KEYWORDS = [
    "어린이집",
    "유치원",
    "초등학교",
    "중학교",
    "고등학교",
    "특수학교",
    "병원",
    "요양병원",
    "요양원",
    "노인복지시설",
    "어린이공원",
    "마을회관",
    "경로당",
    "교회",
    "성당",
    "사찰",
]

REFERENCE_ACCEPTANCE_KEYWORDS = [
    "요양병원",
    "요양원",
    "노인복지",
    "마을회관",
    "경로당",
    "노인정",
    "교회",
    "성당",
    "사찰",
    "절",
    "종교",
    "근린생활",
    "근린시설",
]

MAJOR_SENSITIVE_KEYWORDS = [
    "어린이집",
    "유치원",
    "초등학교",
    "중학교",
    "고등학교",
    "특수학교",
    "종합병원",
    "대학병원",
    "상급종합",
    "의료원",
    "응급의료",
    "대형병원",
    "어린이공원",
    "문화재보호",
]

RESIDENTIAL_COMPLEX_STRONG = [
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
    "센트럴",
]

RESIDENTIAL_COMPLEX_EXCLUDE = [
    "마을회관",
    "경로당",
    "농가",
    "창고",
    "축사",
    "비닐하우스",
    "공장",
    "주유소",
    "공동묘지",
    "묘지",
    "사찰",
    "농업시설",
]


def search_sensitive_facilities_kakao(*_: Any, **__: Any) -> Dict[str, Any]:
    """Kakao search is performed in geocode.py; this hook keeps the module extensible."""
    return {"ok": False, "items": [], "message": "Use geocode.search_residential_risk_places()."}


def search_residential_complexes_kakao(*_: Any, **__: Any) -> Dict[str, Any]:
    """Kakao search is performed in geocode.py; this hook keeps the module extensible."""
    return {"ok": False, "items": [], "message": "Use geocode.search_residential_risk_places()."}


def merge_duplicate_facilities(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for item in items or []:
        lat = _num(item.get("lat"))
        lng = _num(item.get("lng"))
        if lat is None or lng is None:
            continue
        name = str(item.get("name") or item.get("building_use") or item.get("keyword") or "").strip()
        key_name = _normalize_name(name)
        duplicate = None
        for existing in merged:
            if _normalize_name(existing.get("name")) != key_name:
                continue
            distance = geometry.haversine_distance_m(lat, lng, float(existing["lat"]), float(existing["lng"]))
            if distance <= 30:
                duplicate = existing
                break
        if duplicate:
            sources = set(duplicate.get("source_list") or [duplicate.get("source") or "unknown"])
            sources.add(str(item.get("source") or "unknown"))
            duplicate["source_list"] = sorted(sources)
            duplicate["source"] = "/".join(sorted(sources))
            continue
        new_item = dict(item)
        new_item["lat"] = lat
        new_item["lng"] = lng
        new_item["name"] = name or "시설 후보"
        new_item["source_list"] = [str(item.get("source") or "unknown")]
        merged.append(new_item)
    merged.sort(key=lambda value: _num(value.get("distance_m"), 999999) or 999999)
    return merged


def calculate_distance_to_site_boundary(
    item: Dict[str, Any],
    site_polygons: Sequence[Sequence[Dict[str, float]]] | None,
    anchor_point: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    enriched = dict(item)
    point = {"lat": _num(item.get("lat")), "lng": _num(item.get("lng"))}
    if point["lat"] is None or point["lng"] is None:
        return enriched

    anchor_distance = _num(item.get("distance_m"))
    if anchor_distance is None and anchor_point and anchor_point.get("lat") is not None and anchor_point.get("lng") is not None:
        anchor_distance = geometry.haversine_distance_m(
            float(anchor_point["lat"]), float(anchor_point["lng"]), float(point["lat"]), float(point["lng"])
        )

    boundary_distances = []
    for polygon in site_polygons or []:
        distance = geometry.distance_point_to_polygon_m(point, polygon)
        if distance is not None:
            boundary_distances.append(distance)
    boundary_distance = min(boundary_distances) if boundary_distances else None

    applied_distance = boundary_distance if boundary_distance is not None else anchor_distance
    enriched["distance_from_anchor_m"] = _round(anchor_distance)
    enriched["distance_from_site_boundary_m"] = _round(boundary_distance)
    enriched["applied_distance_m"] = _round(applied_distance)
    enriched["distance_basis"] = "부지경계" if boundary_distance is not None else "기준점 임시"
    return enriched


def classify_sensitive_facility(item_or_text: Any) -> str:
    text = _text(item_or_text)
    if is_reference_acceptance_facility(item_or_text):
        return "주민수용성 참고시설"
    if any(keyword in text for keyword in ["어린이집", "유치원", "초등학교", "특수학교"]):
        return "어린이집·유치원·초등학교"
    if any(keyword in text for keyword in ["중학교", "고등학교", "학교"]):
        return "학교"
    if any(keyword in text for keyword in ["종합병원", "대학병원", "상급종합", "의료원", "응급의료", "대형병원"]):
        return "대형 병원"
    if "병원" in text:
        return "병원(규모 확인 필요)"
    if "어린이공원" in text or ("공원" in text and "어린이" in text):
        return "어린이공원"
    return "민감시설"


def is_reference_acceptance_facility(item_or_text: Any) -> bool:
    text = _text(item_or_text)
    if "병원" in text and not any(
        keyword in text for keyword in ["종합병원", "대학병원", "상급종합", "의료원", "응급의료", "대형병원"]
    ):
        return True
    return any(keyword in text for keyword in REFERENCE_ACCEPTANCE_KEYWORDS)


def is_major_sensitive_facility(item_or_text: Any) -> bool:
    text = _text(item_or_text)
    if is_reference_acceptance_facility(item_or_text):
        return False
    if any(keyword in text for keyword in MAJOR_SENSITIVE_KEYWORDS):
        return True
    if "학교" in text:
        return True
    return False


def _reference_acceptance_penalty(distance: Optional[float]) -> Dict[str, Any]:
    if distance is None:
        return {"penalty": 0, "judgement": "", "manual_check": False}
    if distance <= 100:
        return {
            "penalty": 1,
            "judgement": "주민수용성 참고시설이 100m 이내에 있어 약한 확인 감점으로 반영했습니다.",
            "manual_check": True,
        }
    if distance <= 300:
        return {
            "penalty": 0.5,
            "judgement": "주민수용성 참고시설이 100~300m 이내에 있어 약한 확인 감점으로 반영했습니다.",
            "manual_check": True,
        }
    if distance <= 500:
        return {
            "penalty": 0,
            "judgement": "주민수용성 참고시설이 300~500m 이내에 있어 수동 확인 필요 항목으로만 표시합니다.",
            "manual_check": True,
        }
    return {
        "penalty": 0,
        "judgement": "주민수용성 참고시설이 500m 밖에 있어 자동감점은 적용하지 않았습니다.",
        "manual_check": False,
    }


def calculate_sensitive_facility_penalty(
    items: List[Dict[str, Any]],
    detection_failed: bool = False,
    message: str = "",
) -> Dict[str, Any]:
    if detection_failed and not items:
        return {
            "detection_status": "민감시설 자동조회 실패 / 수동확인 필요",
            "penalty": 0,
            "fatal_cap": None,
            "penalty_applied": False,
            "judgement": "민감시설 자동조회에 실패했습니다. 감점은 적용하지 않았으며, 현장확인이 필요합니다.",
            "message": message,
        }

    all_reference_items = [item for item in items if (_num(item.get("applied_distance_m")) or 999999) <= 1000]
    all_reference_items.sort(key=lambda item: _num(item.get("applied_distance_m"), 999999) or 999999)
    major_items = [item for item in all_reference_items if is_major_sensitive_facility(item)]
    reference_acceptance_items = [
        item for item in all_reference_items if is_reference_acceptance_facility(item)
    ]
    nearest = all_reference_items[0] if all_reference_items else None
    nearest_major = major_items[0] if major_items else None
    nearest_reference = reference_acceptance_items[0] if reference_acceptance_items else None
    distance = _num((nearest_major or {}).get("applied_distance_m"))
    reference_distance = _num((nearest_reference or {}).get("applied_distance_m"))

    major_penalty = 0
    fatal_cap = None
    judgements: List[str] = []
    if distance is not None and distance <= 250:
        major_penalty = 30
        fatal_cap = 55
        judgements.append("중대 민감시설이 부지경계 기준 250m 이내에 있어 주민수용성 리스크로 강하게 감점했습니다.")
    elif distance is not None and distance <= 500:
        major_penalty = 15
        fatal_cap = 75
        judgements.append("중대 민감시설이 부지경계 기준 500m 이내에 있어 주민수용성 리스크로 감점했습니다.")
    elif distance is not None and distance <= 1000:
        judgements.append("중대 민감시설이 500m 초과 1km 이내에 있어 참고값으로 표시합니다. 자동감점은 적용하지 않았습니다.")

    reference_profile = _reference_acceptance_penalty(reference_distance)
    reference_penalty = reference_profile["penalty"]
    if reference_profile["judgement"]:
        judgements.append(str(reference_profile["judgement"]))

    penalty = major_penalty + reference_penalty

    return {
        "detection_status": "자동탐지 완료" if all_reference_items else "자동탐지 결과 없음",
        "penalty": penalty,
        "fatal_cap": fatal_cap,
        "penalty_applied": penalty > 0,
        "nearest": nearest,
        "nearest_name": (nearest or {}).get("name"),
        "nearest_type": classify_sensitive_facility(nearest or {}),
        "nearest_distance_m": _round(_num((nearest or {}).get("applied_distance_m"))),
        "distance_from_anchor_m": (nearest_major or nearest_reference or nearest or {}).get("distance_from_anchor_m"),
        "distance_from_site_boundary_m": (nearest_major or nearest_reference or nearest or {}).get("distance_from_site_boundary_m"),
        "applied_distance_m": _round(distance if distance is not None else reference_distance),
        "source": _source(nearest_major or nearest),
        "confidence": "높음" if nearest_major else ("중간" if nearest_reference else "낮음"),
        "judgement": " ".join(judgements),
        "major_count": len(major_items),
        "reference_count": len(reference_acceptance_items),
        "nearest_major_name": (nearest_major or {}).get("name"),
        "nearest_major_type": classify_sensitive_facility(nearest_major or {}),
        "nearest_major_distance_m": _round(distance),
        "major_penalty": major_penalty,
        "reference_penalty": reference_penalty,
        "reference_manual_check": reference_profile["manual_check"],
        "reference_judgement": reference_profile["judgement"],
        "nearest_reference_name": (nearest_reference or {}).get("name"),
        "nearest_reference_type": classify_sensitive_facility(nearest_reference or {}),
        "nearest_reference_distance_m": _round(reference_distance),
    }


def calculate_residential_complex_penalty(
    items: List[Dict[str, Any]],
    detection_failed: bool = False,
    message: str = "",
) -> Dict[str, Any]:
    if detection_failed and not items:
        return {
            "detection_status": "주거단지 자동조회 실패 / 수동확인 필요",
            "penalty": 0,
            "fatal_cap": None,
            "judgement": "주거단지 자동조회에 실패했습니다. 감점은 적용하지 않았으며, 현장확인이 필요합니다.",
            "message": message,
        }

    clear_items = [item for item in items if is_clear_residential_complex(item)]
    reference_items = [item for item in clear_items if (_num(item.get("applied_distance_m")) or 999999) <= 1000]
    reference_items.sort(key=lambda item: _num(item.get("applied_distance_m"), 999999) or 999999)
    nearest = reference_items[0] if reference_items else None
    distance = _num((nearest or {}).get("applied_distance_m"))
    count_500 = sum(1 for item in clear_items if (_num(item.get("applied_distance_m")) or 999999) <= 500)

    penalty = 0
    fatal_cap = None
    judgement = ""
    if distance is not None and distance <= 250:
        penalty = 25
        fatal_cap = 60
        judgement = "명확한 아파트·공동주택단지가 부지경계 기준 250m 이내에 있어 감점했습니다."
    elif distance is not None and distance <= 500:
        penalty = 15
        fatal_cap = 75
        judgement = "명확한 아파트·공동주택단지가 부지경계 기준 500m 이내에 있어 감점했습니다."
    elif distance is not None and distance <= 1000:
        judgement = "아파트·공동주택단지가 500m 초과 1km 이내에 있어 참고값으로 표시합니다. 자동감점은 적용하지 않았습니다."

    if count_500 >= 5:
        penalty = max(penalty, 35)
        fatal_cap = min(_num(fatal_cap, 100) or 100, 55)
        judgement = (judgement + " 500m 이내 명확한 공동주택단지가 5개 이상 확인되어 상한을 강화했습니다.").strip()
    elif count_500 >= 3:
        penalty = max(penalty, 25)
        fatal_cap = min(_num(fatal_cap, 100) or 100, 65)
        judgement = (judgement + " 500m 이내 명확한 공동주택단지가 3개 이상 확인되어 상한을 적용했습니다.").strip()

    not_applied_reason = ""
    if reference_items and penalty == 0:
        not_applied_reason = "1km 참고권역 정보이므로 자동감점하지 않았습니다."
    elif items and not reference_items:
        not_applied_reason = "대규모 주거단지 판정 근거가 불명확하거나 500m 자동감점 기준에 미달해 수동확인 대상으로 표시했습니다."

    return {
        "detection_status": "자동탐지 완료" if items else "자동탐지 결과 없음",
        "penalty": penalty,
        "fatal_cap": None if fatal_cap == 100 else fatal_cap,
        "count_500m": count_500,
        "nearest": nearest,
        "nearest_name": (nearest or {}).get("name"),
        "nearest_distance_m": _round(distance),
        "large_complex_detected": count_500 > 0,
        "reason": (nearest or {}).get("reason") or ("명확한 500m 이내 공동주택단지 확인" if count_500 else "자동감점 근거 불명확"),
        "confidence": (nearest or {}).get("confidence") or ("높음" if count_500 else "낮음"),
        "source": _source(nearest),
        "not_applied_reason": not_applied_reason,
        "judgement": judgement,
    }


def build_sensitive_facility_summary(
    sensitive_items: List[Dict[str, Any]],
    complex_items: List[Dict[str, Any]],
    detection_failed: bool = False,
    message: str = "",
) -> Dict[str, Any]:
    sensitive_profile = calculate_sensitive_facility_penalty(sensitive_items, detection_failed, message)
    complex_profile = calculate_residential_complex_penalty(complex_items, detection_failed, message)
    return {"sensitive": sensitive_profile, "complex": complex_profile}


def is_clear_residential_complex(item: Dict[str, Any]) -> bool:
    text = _text(item)
    if any(keyword in text for keyword in RESIDENTIAL_COMPLEX_EXCLUDE):
        return False
    if any(keyword.lower() in text.lower() for keyword in RESIDENTIAL_COMPLEX_STRONG):
        item["confidence"] = item.get("confidence") or "높음"
        item["reason"] = item.get("reason") or "명확한 아파트·공동주택단지 키워드"
        return True
    if ("마을" in text or "단지" in text) and ("아파트" in text or "공동주택" in text):
        item["confidence"] = item.get("confidence") or "중간"
        item["reason"] = item.get("reason") or "마을/단지와 공동주택 키워드 조합"
        return True
    return False


def _normalize_name(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def _text(item_or_text: Any) -> str:
    if isinstance(item_or_text, dict):
        props = item_or_text.get("properties") or {}
        return " ".join(
            str(value or "")
            for value in [
                item_or_text.get("name"),
                item_or_text.get("building_use"),
                item_or_text.get("keyword"),
                item_or_text.get("category"),
                item_or_text.get("type"),
                props.get("BD_NM"),
                props.get("buld_nm"),
                props.get("BULD_NM"),
                props.get("A1"),
                props.get("A5"),
                props.get("A6"),
            ]
        )
    return str(item_or_text or "")


def _source(item: Optional[Dict[str, Any]]) -> str:
    if not item:
        return "-"
    values = item.get("source_list") or [item.get("source") or "unknown"]
    return "/".join(str(value) for value in values if value)


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any) -> Optional[float]:
    number = _num(value)
    if number is None:
        return None
    return round(number, 1)
