from __future__ import annotations

from typing import Any, Dict, List, Optional


SLOPE_NOTICE = (
    "경사도 자동계산은 현재 MVP에서 비활성화했습니다. "
    "고급설정에서 수동 경사도 등급을 선택하면 해당 배점과 감점을 적용합니다."
)


def analyze_slope(parcel_group: Dict[str, Any]) -> Dict[str, Any]:
    """Keep slope automatic calculation disabled for the MVP."""
    main = parcel_group.get("main") or {}
    land = str(main.get("land_category") or "")
    message = SLOPE_NOTICE
    if "임야" in land:
        message += " 지목이 임야일 가능성이 있어 산지정보 및 현장측량 확인이 필요합니다."

    return {
        "ok": False,
        "slope_auto_status": "자동계산 비활성화",
        "slope_degree_average": None,
        "average_slope_degree": None,
        "slope_degree_max": None,
        "slope_degree": None,
        "slope_grade": "수동확인 필요",
        "slope_score": None,
        "slope_source": "수동 경사도 선택",
        "slope_confidence": "수동확인 필요",
        "slope_judgement": "경사도 자동계산은 비활성화되어 감점과 상한을 적용하지 않았습니다. 고급설정에서 수동 경사도 등급을 선택하면 점수에 반영됩니다.",
        "contour_overlay_available": False,
        "message": message,
        "notice": SLOPE_NOTICE,
    }


def calculate_slope_from_dem(polygon: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"ok": False, "source": "DEM 미사용", "reason": "DEM automatic slope calculation is disabled"}


def calculate_slope_from_contours(polygon: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"ok": False, "source": "등고선 미사용", "reason": "Contour automatic slope calculation is disabled"}


def build_slope_result(source_result: Dict[str, Any], source_name: str) -> Dict[str, Any]:
    average = _number(source_result.get("slope_degree_average"), source_result.get("average_slope_degree"))
    maximum = _number(source_result.get("slope_degree_max"), source_result.get("max_slope_degree"), average)
    grade = slope_grade(average)
    return {
        "ok": True,
        "slope_auto_status": "자동계산 성공",
        "slope_degree_average": average,
        "average_slope_degree": average,
        "slope_degree_max": maximum,
        "slope_degree": average,
        "slope_grade": grade,
        "slope_source": source_name,
        "slope_confidence": source_result.get("confidence", "중간"),
        "slope_judgement": build_slope_judgement(average, True),
        "contour_overlay_available": False,
        "message": f"{source_name} 기반으로 경사도를 1차 산정했습니다.",
        "notice": SLOPE_NOTICE,
    }


def resolve_final_slope_value(auto_result: Dict[str, Any], manual_band: str = "auto") -> Dict[str, Any]:
    manual_map = {
        "low": (10.0, "낮음 / 0~15도"),
        "medium": (17.0, "중간 / 15~20도"),
        "high": (22.0, "높음 / 20~25도"),
        "worst": (26.0, "최악 / 25도 초과"),
    }
    if manual_band in manual_map:
        degree, label = manual_map[manual_band]
        return {
            "degree": degree,
            "manual_value": label,
            "basis": "수동",
            "source": "사용자 수동입력",
            "confidence": "수동확인",
        }
    if manual_band == "unknown":
        return {
            "degree": None,
            "manual_value": "미확인",
            "basis": "미확인",
            "source": "사용자 수동입력",
            "confidence": "낮음",
        }
    return {
        "degree": None,
        "manual_value": None,
        "basis": "미확인",
        "source": "수동 경사도 선택",
        "confidence": "수동확인 필요",
    }


def slope_grade(degree: Optional[float]) -> str:
    if degree is None:
        return "수동확인 필요"
    if degree <= 15:
        return "매우 양호"
    if degree <= 20:
        return "보통"
    if degree <= 25:
        return "불리"
    return "최악"


def build_slope_judgement(degree: Optional[float], auto_ok: bool = False) -> str:
    if degree is None:
        return "경사도 자동계산은 비활성화되어 감점과 상한을 적용하지 않았습니다. 수동 경사도 등급 선택 또는 현장측량 확인이 필요합니다."
    if degree <= 15:
        return "경사도가 15도 이하로 토목공사와 부지조성 측면에서 양호한 후보지로 평가됩니다."
    if degree <= 20:
        return "경사도가 15도를 초과하여 일부 토목 보완이 필요할 수 있습니다."
    if degree <= 25:
        return "경사도가 20도를 초과하여 절성토·진입도로·부지조성 리스크가 큽니다."
    return "경사도가 25도를 초과하여 데이터센터 부지조성 관점에서 치명적인 토목 리스크로 평가됩니다."


def _number(*values: Any) -> Optional[float]:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
