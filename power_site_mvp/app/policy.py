from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


POLICY_COLUMNS = [
    "sido",
    "sigungu",
    "lagging_index",
    "lagging_rank",
    "population_density",
    "fiscal_independence_rate",
    "updated_year",
    "lagging_source",
    "population_source",
    "fiscal_source",
    "match_key",
]

POLICY_SCORE_TABLE_FILENAME = "power_grid_policy_score_table_merged.json"

POWER_SELF_COLUMNS = [
    "sido",
    "power_self_sufficiency_rate",
    "official_power_self_score",
    "updated_year",
    "source_note",
]

POLICY_NOTICE = (
    "정책입지 자료는 data/power_grid_policy_score_table_merged.json 표를 우선 적용하고, 없으면 data/policy_reference.csv 저장자료를 주소의 시도·시군구와 자동 매칭해 반영합니다. "
    "자료가 없으면 정책자료 업데이트 필요로 표시하고 공식 0점 구간에 해당하는 중립 임시점수를 적용합니다."
)

PERMIT_NOTICE = (
    "본 인허가 등급은 용도지역·지구·구역 및 방송통신시설 허용 가능성 기반의 1차 자동등급입니다. "
    "최종 인허가는 지자체 해석 및 개별 법령 검토가 필요합니다."
)


def evaluate_policy(
    address: str,
    geocode: Dict[str, Any],
    manual: Any,
    data_path: Path,
    power_self_path: Optional[Path] = None,
) -> Dict[str, Any]:
    del manual
    region = extract_region(address, geocode)
    site = evaluate_site_suitability(region, data_path)
    power = evaluate_power_self_sufficiency(
        region, power_self_path or data_path.with_name("power_self_sufficiency_reference.csv")
    )
    ok = bool(site.get("ok"))

    return {
        "ok": ok,
        "admin_region": region.get("admin_region"),
        "sido": normalize_sido(region.get("sido", "")),
        "sigungu": normalize_sigungu(region.get("sigungu", "")),
        "match_key": build_match_key(region.get("sido", ""), region.get("sigungu", "")),
        "site_suitability": site,
        "power_self_sufficiency": power,
        "internal_score": site.get("internal_score", 6),
        "max_score": 10,
        "message": "정책입지 기준자료 자동매칭 성공" if ok else "정책입지 기준자료 없음 / 정책자료 업데이트 필요",
        "notice": POLICY_NOTICE,
        **_flatten_site(site),
        **_flatten_power(power),
    }


def evaluate_site_suitability(region: Dict[str, str], data_path: Path) -> Dict[str, Any]:
    table_row = find_policy_score_table_row(region, data_path.with_name(POLICY_SCORE_TABLE_FILENAME))
    row = find_policy_row(region, data_path)
    normalized_sido = normalize_sido(region.get("sido", ""))
    normalized_sigungu = normalize_sigungu(region.get("sigungu", ""))
    match_key = build_match_key(normalized_sido, normalized_sigungu)
    if table_row:
        table_result = evaluate_site_suitability_from_score_table(table_row, region, match_key)
        return merge_policy_reference_raw_values(table_result, row)
    if not row:
        return {
            "ok": False,
            "admin_region": region.get("admin_region"),
            "sido": normalized_sido,
            "sigungu": normalized_sigungu,
            "match_key": match_key,
            "message": "정책입지 기준자료 없음 / 정책자료 업데이트 필요",
            "internal_score": 6,
            "max_score": 10,
            "official_adjustment": 0,
            "regional_score_sum": None,
            "source": "policy_reference.csv 매칭 실패",
            "source_note": "정책자료 미확인 임시점수 적용",
            "match_status": "정책입지 기준자료 없음 / 정책자료 업데이트 필요",
            "judgement": "정책자료 미확인으로 공식 0점 구간에 해당하는 중립 임시점수를 적용했습니다. 정책자료 업데이트가 필요합니다.",
            "reflected_in_total": True,
        }

    lagging = to_float(row.get("lagging_index"))
    density = to_float(row.get("population_density"))
    fiscal = to_float(row.get("fiscal_independence_rate"))
    source_note = combine_source_note(row)
    if lagging is None or density is None or fiscal is None:
        return {
            "ok": False,
            "admin_region": f"{row.get('sido', '')} {row.get('sigungu', '')}".strip(),
            "sido": row.get("sido") or normalized_sido,
            "sigungu": row.get("sigungu") or normalized_sigungu,
            "match_key": row.get("match_key") or match_key,
            "lagging_index": lagging,
            "lagging_rank": row.get("lagging_rank"),
            "message": "정책입지 기준자료 값 누락 / 정책자료 업데이트 필요",
            "internal_score": 6,
            "max_score": 10,
            "official_adjustment": 0,
            "source": "policy_reference.csv 값 누락",
            "source_note": source_note,
            "updated_year": row.get("updated_year"),
            "lagging_source": row.get("lagging_source"),
            "population_source": row.get("population_source"),
            "fiscal_source": row.get("fiscal_source"),
            "match_status": "정책입지 기준자료 값 누락 / 정책자료 업데이트 필요",
            "judgement": "정책자료 값 누락으로 공식 0점 구간에 해당하는 중립 임시점수를 적용했습니다.",
            "reflected_in_total": True,
        }

    lagging_score, lagging_band = regional_lagging_score(lagging)
    density_score, density_band = population_density_score(density)
    fiscal_score, fiscal_band = fiscal_independence_score(fiscal)
    regional_sum = round(lagging_score + density_score + fiscal_score, 3)
    adjustment = calculate_official_location_bonus(regional_sum)
    internal_score = convert_policy_bonus_to_internal_score(adjustment)

    return {
        "ok": True,
        "admin_region": f"{row.get('sido', '')} {row.get('sigungu', '')}".strip() or region.get("admin_region"),
        "sido": row.get("sido") or normalized_sido,
        "sigungu": row.get("sigungu") or normalized_sigungu,
        "match_key": row.get("match_key") or match_key,
        "lagging_index": lagging,
        "lagging_rank": row.get("lagging_rank"),
        "lagging_score": lagging_score,
        "regional_lagging_score": lagging_score,
        "lagging_band": lagging_band,
        "population_density": density,
        "population_density_score": density_score,
        "population_density_band": density_band,
        "fiscal_independence_rate": fiscal,
        "fiscal_score": fiscal_score,
        "fiscal_independence_score": fiscal_score,
        "fiscal_band": fiscal_band,
        "regional_score_sum": regional_sum,
        "official_adjustment": adjustment,
        "internal_score": internal_score,
        "max_score": 10,
        "judgement": calculate_policy_judgement(adjustment),
        "updated_year": row.get("updated_year"),
        "lagging_source": row.get("lagging_source"),
        "population_source": row.get("population_source"),
        "fiscal_source": row.get("fiscal_source"),
        "source_note": source_note,
        "source": "policy_reference.csv 자동매칭",
        "match_status": "CSV 자동매칭 성공",
        "reflected_in_total": True,
    }


def evaluate_site_suitability_from_score_table(row: Dict[str, Any], region: Dict[str, str], match_key: str) -> Dict[str, Any]:
    lagging = to_float(row.get("지역낙후도지수"))
    lagging_rank = row.get("지역낙후도순위")
    lagging_score = to_float(row.get("지역낙후도배점"))
    density_score = to_float(row.get("인구밀도_전평배점"))
    fiscal_score = to_float(row.get("재정자립도_전평배점"))
    regional_sum = to_float(row.get("입지적정성합산"))
    adjustment_raw = to_float(row.get("전평_최종가감점"))
    adjustment = int(adjustment_raw) if adjustment_raw is not None else calculate_official_location_bonus(regional_sum or 0)
    internal_score = convert_policy_bonus_to_internal_score(adjustment)
    source_year = clean_policy_source_year(row.get("원본_통계연도") or row.get("?먮낯_?듦퀎?곕룄"))
    source_note = (
        f"전력계통영향평가 정책입지 병합표 적용 / "
        f"{row.get('PIMAC_매칭방식') or '매칭방식 미확인'} / "
        f"원본 통계연도 {source_year or '미확인'} / "
        f"앱사용코드 {row.get('앱사용코드') or row.get('지역명') or '-'}"
    )

    return {
        "ok": True,
        "admin_region": row.get("지역명") or f"{row.get('시도', '')} {row.get('시군구', '')}".strip() or region.get("admin_region"),
        "sido": normalize_sido(row.get("시도") or region.get("sido", "")),
        "sigungu": normalize_sigungu(row.get("시군구") or region.get("sigungu", "")),
        "match_key": match_key,
        "lagging_index": lagging,
        "lagging_rank": lagging_rank,
        "lagging_score": lagging_score,
        "regional_lagging_score": lagging_score,
        "lagging_band": _score_table_band("지역낙후도", lagging_score),
        "population_density": None,
        "population_density_score": density_score,
        "population_density_band": _score_table_band("인구밀도", density_score),
        "fiscal_independence_rate": None,
        "fiscal_score": fiscal_score,
        "fiscal_independence_score": fiscal_score,
        "fiscal_band": _score_table_band("재정자립도", fiscal_score),
        "regional_score_sum": regional_sum,
        "official_adjustment": adjustment,
        "internal_score": internal_score,
        "max_score": 10,
        "judgement": calculate_policy_judgement(adjustment),
        "updated_year": source_year,
        "lagging_source": f"KDI PIMAC 지역낙후도지수 {row.get('지역낙후도지수')} / 순위 {row.get('지역낙후도순위')}",
        "population_source": f"병합표 인구밀도 전평배점 {row.get('인구밀도_전평배점')} / {row.get('인구밀도_기존판정') or '-'}",
        "fiscal_source": f"병합표 재정자립도 전평배점 {row.get('재정자립도_전평배점')} / {row.get('재정자립도_기존판정') or '-'}",
        "source_note": source_note,
        "source": POLICY_SCORE_TABLE_FILENAME,
        "match_status": "정책입지 병합표 자동매칭 성공",
        "reflected_in_total": True,
        "policy_table_region_name": row.get("지역명"),
        "policy_table_judgement": row.get("전평_판정"),
        "policy_table_match_method": row.get("PIMAC_매칭방식"),
    }


def merge_policy_reference_raw_values(result: Dict[str, Any], row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep the official policy table score, but display saved CSV raw values when available."""
    if not row:
        return result
    merged = dict(result)
    raw_values = {
        "lagging_index": to_float(row.get("lagging_index")),
        "lagging_rank": row.get("lagging_rank"),
        "population_density": to_float(row.get("population_density")),
        "fiscal_independence_rate": to_float(row.get("fiscal_independence_rate")),
    }
    for key, value in raw_values.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    if not merged.get("updated_year") and row.get("updated_year"):
        merged["updated_year"] = row.get("updated_year")

    csv_source_note = combine_source_note(row)
    if csv_source_note:
        merged["policy_reference_source_note"] = csv_source_note
        if not merged.get("source_note"):
            merged["source_note"] = csv_source_note
    return merged


def evaluate_power_self_sufficiency(region: Dict[str, str], data_path: Path) -> Dict[str, Any]:
    row = find_power_self_row(region, data_path)
    if not row:
        return {
            "ok": False,
            "sido": normalize_sido(region.get("sido", "")),
            "message": "전력자립도 자동매칭 실패 / 수동확인 필요",
            "source": "자동매칭 실패",
            "internal_score": 2,
            "max_score": 5,
            "judgement": "전력자립도 자료가 없어 내부 총점에는 임시 2점을 적용합니다.",
        }

    rate = to_float(row.get("power_self_sufficiency_rate"))
    official = to_float(row.get("official_power_self_score"))
    if official is None:
        official = official_power_self_score(rate)

    return {
        "ok": True,
        "sido": row.get("sido") or normalize_sido(region.get("sido", "")),
        "power_self_sufficiency_rate": rate,
        "official_power_self_score": official,
        "internal_score": internal_power_self_score(official),
        "max_score": 5,
        "judgement": power_self_judgement(rate, official),
        "updated_year": row.get("updated_year"),
        "source_note": row.get("source_note"),
        "source": "CSV 자동매칭",
    }


def evaluate_datacenter_permit(zoning: Dict[str, Any], growth: Dict[str, Any]) -> Dict[str, Any]:
    names = " ".join(zoning.get("names") or [zoning.get("main_zoning") or ""])
    growth_status = growth.get("status") or ""
    has_growth = bool(growth.get("ok")) and (
        "성장관리" in names or "성장관리" in growth_status or "포함" in growth_status
    )
    industrial_growth = has_growth and any(keyword in names for keyword in ["산업", "유통"])

    if not zoning.get("ok"):
        grade = "수동확인 필요"
        reason = "용도지역 자동조회가 불명확합니다."
        telecom = "수동확인 필요"
        group = "주의구간 / 행위제한 확인 필요"
    elif _contains(names, ["개발제한"]):
        grade = "특수해제 필요 또는 제한구역"
        reason = "개발제한구역은 일반적인 데이터센터 인허가 설명력이 매우 낮아 별도 해제, 도시관리계획 변경, 공공성·정책성 검토가 필요합니다."
        telecom = "특수해제 필요 또는 제한구역"
        group = "개발제한구역 / 특수검토 구간"
    elif _contains(names, ["농림"]):
        grade = "제한 가능성 높음"
        reason = "농림지역으로 인허가 설명력은 낮으나 전략검토 여지는 별도 확인합니다."
        telecom = "제한 가능성 높음"
        group = "농림지역 / 낮은 점수 구간"
    elif _contains(names, ["계획관리", "자연녹지", "일반공업", "준공업", "전용공업", "중심상업", "일반상업", "근린상업", "유통상업", "준주거", "산업"]) or industrial_growth:
        grade = "검토 가능성 높음"
        reason = "계획관리지역 또는 그 이상으로 인허가 설명력이 높은 구간으로 평가했습니다."
        telecom = "검토 가능성 높음"
        group = "계획관리 이상 / 고점수 구간"
    elif _contains(names, ["보전관리", "생산관리", "생산녹지"]):
        grade = "검토 가능성 높음" if has_growth else "검토 가능"
        reason = "보전관리지역·생산관리지역은 데이터센터/방송통신시설 검토 가능성이 있는 구간으로 보아 인허가 설명력에서 검토 가능 점수로 반영했습니다. 최종 인허가는 토지이음 행위제한, 지자체 조례, 개발행위허가, 건폐율·용적률 및 기반시설 조건 확인이 필요합니다."
        telecom = grade
        group = "보전관리·생산관리 / 검토 가능 구간"
    elif _contains(names, ["자연환경보전", "상수원보호"]):
        grade = "제한 가능성 높음"
        reason = "자연환경보전지역 또는 상수원보호구역은 일반적인 데이터센터 인허가 설명력이 매우 낮은 구간으로 평가했습니다."
        telecom = "제한 가능성 높음"
        group = "최악 구간 / 제한구역"
    elif _contains(names, ["제1종일반주거", "제2종일반주거", "제3종일반주거"]):
        grade = "보통"
        reason = "일반주거지역은 인허가 설명력이 제한적이므로 주변 조건과 지자체 해석 확인이 필요합니다."
        telecom = "보통"
        group = "주거지역 / 제한 검토 구간"
    elif _contains(names, ["문화재", "보전녹지", "주거"]):
        grade = "주의 필요"
        reason = "환경·문화재·상수원·주거 성격의 제한 가능성 확인이 필요합니다."
        telecom = "주의 필요"
        group = "주의구간 / 행위제한 확인 필요"
    else:
        grade = "수동확인 필요"
        reason = "용도지역명만으로 인허가 설명력을 자동 확정하기 어렵습니다."
        telecom = "수동확인 필요"
        group = "주의구간 / 행위제한 확인 필요"

    ratios = land_use_ratios(names)
    restrictions = restriction_summary(names, has_growth)
    return {
        "grade": grade,
        "reason": reason,
        "permit_group": group,
        "zoning_group": group,
        "notice": PERMIT_NOTICE,
        "land_use_link": "https://www.eum.go.kr/",
        "land_use_districts": zoning.get("names") or [],
        "building_coverage_ratio": ratios.get("building_coverage_ratio"),
        "floor_area_ratio": ratios.get("floor_area_ratio"),
        "land_use_restriction_summary": restrictions,
        "telecom_facility_possible": telecom,
        "permit_confidence": "중간" if zoning.get("ok") else "낮음",
        "manual_check_item": "토지이음에서 용도지역·지구·구역 및 행위제한을 최종 확인하세요.",
    }


def evaluate_growth_management(zoning: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(zoning.get("names") or []) + " " + str(zoning.get("records") or "")
    if "성장관리" in text:
        return {
            "ok": True,
            "status": "포함 가능성",
            "confidence": "중간",
            "message": "용도지역 속성에서 성장관리계획구역 관련 문구를 감지했습니다.",
        }
    return {
        "ok": False,
        "status": None,
        "confidence": None,
        "message": "",
    }


def upsert_policy_reference(data_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    data_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(_read_policy_rows(data_path))
    source_note = str(data.get("source_note") or "사용자 수동 저장").strip()
    new_row = {
        "sido": normalize_sido(str(data.get("sido", ""))),
        "sigungu": normalize_sigungu(str(data.get("sigungu", ""))),
        "lagging_index": str(data.get("lagging_index", "")).strip(),
        "lagging_rank": str(data.get("lagging_rank", "")).strip(),
        "population_density": str(data.get("population_density", "")).strip(),
        "fiscal_independence_rate": str(data.get("fiscal_independence_rate", "")).strip(),
        "updated_year": str(data.get("updated_year", "")).strip(),
        "lagging_source": str(data.get("lagging_source") or source_note).strip(),
        "population_source": str(data.get("population_source") or source_note).strip(),
        "fiscal_source": str(data.get("fiscal_source") or source_note).strip(),
    }
    new_row["match_key"] = build_match_key(new_row["sido"], new_row["sigungu"])
    updated = False
    for idx, row in enumerate(rows):
        if row_match_key(row) == new_row["match_key"]:
            rows[idx] = new_row
            updated = True
            break
    if not updated:
        rows.append(new_row)
    with data_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POLICY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return {"ok": True, "updated": updated, "row": new_row}


def extract_region(address: str, geocode: Dict[str, Any]) -> Dict[str, str]:
    text = geocode.get("region") or geocode.get("road_address") or geocode.get("jibun_address") or address
    parts = [part for part in str(text).split() if part]
    return {
        "sido": parts[0] if len(parts) >= 1 else "",
        "sigungu": parts[1] if len(parts) >= 2 else "",
        "admin_region": " ".join(parts[:2]),
    }


def find_policy_row(region: Dict[str, str], data_path: Path) -> Optional[Dict[str, Any]]:
    if not data_path.exists():
        return None
    target = build_match_key(region.get("sido", ""), region.get("sigungu", ""))
    for row in _read_policy_rows(data_path):
        if row_match_key(row) == target:
            return row
    return None


def find_policy_score_table_row(region: Dict[str, str], table_path: Path) -> Optional[Dict[str, Any]]:
    if not table_path.exists():
        return None
    target = build_match_key(region.get("sido", ""), region.get("sigungu", ""))
    try:
        rows = json.loads(table_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_key = build_match_key(str(row.get("시도") or ""), str(row.get("시군구") or ""))
        app_code_key = _policy_table_app_code_key(row.get("앱사용코드") or row.get("지역명"))
        if row_key == target or app_code_key == target:
            return row
    return None


def find_power_self_row(region: Dict[str, str], data_path: Path) -> Optional[Dict[str, Any]]:
    if not data_path.exists():
        return None
    target_sido = normalize_sido(region.get("sido", ""))
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if normalize_sido(row.get("sido", "")) == target_sido:
                return row
    return None


def normalize_sido(value: str) -> str:
    text = str(value or "").strip()
    aliases = {
        "서울특별시": "서울",
        "부산광역시": "부산",
        "대구광역시": "대구",
        "인천광역시": "인천",
        "광주광역시": "광주",
        "대전광역시": "대전",
        "울산광역시": "울산",
        "세종특별자치시": "세종",
        "경기도": "경기",
        "강원특별자치도": "강원",
        "강원도": "강원",
        "충청북도": "충북",
        "충청남도": "충남",
        "전북특별자치도": "전북",
        "전라북도": "전북",
        "전라남도": "전남",
        "경상북도": "경북",
        "경상남도": "경남",
        "제주특별자치도": "제주",
    }
    return aliases.get(text, text)


def normalize_sigungu(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for suffix in ["시", "군", "구"]:
        if text.endswith(suffix) and len(text) > 2:
            return text[:-1]
    return text


def build_match_key(sido: str, sigungu: str) -> str:
    normalized_sido = normalize_sido(sido)
    normalized_sigungu = normalize_sigungu(sigungu)
    return f"{normalized_sido}|{normalized_sigungu}".strip("|")


def row_match_key(row: Dict[str, Any]) -> str:
    return str(row.get("match_key") or build_match_key(row.get("sido", ""), row.get("sigungu", ""))).strip()


def _policy_table_app_code_key(value: Any) -> str:
    parts = [part for part in str(value or "").split() if part]
    if len(parts) >= 2:
        return build_match_key(parts[0], parts[1])
    return ""


def _score_table_band(label: str, score: Optional[float]) -> str:
    if score is None:
        return f"{label} 병합표 값 없음"
    return f"{label} 병합표 배점 {score:g}"


def regional_lagging_score(value: Optional[float]) -> Tuple[float, str]:
    if value is None:
        return 0.2, "자료 없음"
    if value >= 1.0:
        return 0.05, "1.0 이상"
    if value >= 0.5:
        return 0.2, "0.5 이상 1.0 미만"
    if value >= 0:
        return 0.35, "0 이상 0.5 미만"
    return 0.5, "0 미만"


def population_density_score(value: Optional[float]) -> Tuple[float, str]:
    if value is None:
        return 0.2, "자료 없음"
    if value >= 2000:
        return 0.05, "2,000 이상"
    if value >= 1000:
        return 0.2, "1,000 이상 2,000 미만"
    if value >= 200:
        return 0.35, "200 이상 1,000 미만"
    return 0.5, "200 미만"


def fiscal_independence_score(value: Optional[float]) -> Tuple[float, str]:
    if value is None:
        return 0.2, "자료 없음"
    if value >= 35:
        return 0.05, "35% 이상"
    if value >= 25:
        return 0.2, "25% 이상 35% 미만"
    if value >= 15:
        return 0.35, "15% 이상 25% 미만"
    return 0.5, "15% 미만"


def official_adjustment(total: float) -> int:
    if total >= 1.4:
        return 15
    if total >= 1.2:
        return 10
    if total >= 1.0:
        return 5
    if total >= 0.8:
        return 0
    if total >= 0.6:
        return -5
    if total >= 0.4:
        return -10
    return -15


def calculate_official_location_bonus(total: float) -> int:
    return official_adjustment(total)


def convert_policy_bonus_to_internal_score(adjustment: int | None) -> float:
    return {15: 10.0, 10: 9.5, 5: 8.0, 0: 6.0, -5: 2.0, -10: 0.5, -15: 0.0}.get(adjustment, 6.0)


def internal_site_suitability_score(adjustment: int | None) -> float:
    return convert_policy_bonus_to_internal_score(adjustment)


def internal_policy_score(adjustment: int | None) -> float:
    return convert_policy_bonus_to_internal_score(adjustment)


def official_power_self_score(rate: Optional[float]) -> float:
    if rate is None:
        return 4
    if rate >= 200:
        return 10
    if rate >= 150:
        return 8
    if rate >= 100:
        return 6
    if rate >= 50:
        return 4
    return 2


def internal_power_self_score(official_score: Optional[float]) -> float:
    if official_score is None:
        return 2
    if official_score >= 10:
        return 5
    if official_score >= 8:
        return 4
    if official_score >= 6:
        return 3
    if official_score >= 4:
        return 2
    return 1


def calculate_policy_judgement(adjustment: Optional[int]) -> str:
    return {
        15: "정책입지상 최상위 가점구간입니다. 지역낙후도·인구밀도·재정자립도 기준에서 매우 유리한 후보지로 평가됩니다.",
        10: "정책입지상 매우 강한 가점구간입니다. 다른 수도권 후보지 대비 정책점수 출발선이 크게 유리합니다.",
        5: "정책입지상 의미 있는 가점구간입니다. 후보지 경쟁력에 긍정적으로 반영됩니다.",
        0: "정책입지상 중립구간입니다. 가점 또는 감점에 따른 특별한 우위는 크지 않습니다.",
        -5: "정책입지상 주의구간입니다. 정책점수 측면에서 일부 불리하게 작용할 수 있습니다.",
        -10: "정책입지상 최악에 가까운 감점구간입니다. 후보지 경쟁력에 중대한 불리요소로 반영됩니다.",
        -15: "정책입지상 치명적 감점구간입니다. 대규모 전력수요 입지로서 정책점수 측면의 불리함이 매우 큽니다.",
    }.get(adjustment, "정책자료 미확인으로 공식 0점 구간에 해당하는 중립 임시점수를 적용했습니다.")


def site_judgement(adjustment: Optional[int]) -> str:
    return calculate_policy_judgement(adjustment)


def power_self_judgement(rate: Optional[float], official_score: Optional[float]) -> str:
    if rate is None:
        return "전력자립도 자동매칭 실패로 수동확인이 필요합니다. 내부 총점에는 임시 2점을 적용합니다."
    return f"전력자립도 {rate:.1f}%로 지침서 기준 {official_score:g}/10점 구간입니다. 내부 총점에는 5점 항목으로 약하게 반영합니다."


def land_use_ratios(text: str) -> Dict[str, str]:
    if _contains(text, ["계획관리"]):
        return {"building_coverage_ratio": "40% 이하(일반 기준, 지자체 확인 필요)", "floor_area_ratio": "100% 이하(일반 기준, 지자체 확인 필요)"}
    if _contains(text, ["생산관리", "보전관리"]):
        return {"building_coverage_ratio": "20% 이하(일반 기준, 지자체 확인 필요)", "floor_area_ratio": "80% 이하(일반 기준, 지자체 확인 필요)"}
    if _contains(text, ["공업", "준공업"]):
        return {"building_coverage_ratio": "70% 이하(일반 기준, 지자체 확인 필요)", "floor_area_ratio": "400% 이하(일반 기준, 지자체 확인 필요)"}
    if _contains(text, ["농림", "자연환경보전"]):
        return {"building_coverage_ratio": "20% 이하 가능성(수동확인 필요)", "floor_area_ratio": "80% 이하 가능성(수동확인 필요)"}
    return {"building_coverage_ratio": "수동확인 필요", "floor_area_ratio": "수동확인 필요"}


def restriction_summary(text: str, has_growth: bool) -> str:
    if _contains(text, ["개발제한"]):
        return "개발제한구역은 데이터센터 인허가 설명력이 매우 낮아 개별 법령 검토가 필요합니다."
    if _contains(text, ["농림"]):
        return "농림지역은 인허가 설명력이 낮으나 전력·도로·정책 조건이 우수하면 전략검토 후보로 남길 수 있습니다."
    if _contains(text, ["보전관리", "생산관리"]):
        base = "보전관리지역과 생산관리지역은 동일 점수대로 처리하며 방송통신시설 검토 가능성이 있는 구간으로 봅니다."
        return base + (" 성장관리계획구역 가능성으로 설명력이 보강됩니다." if has_growth else "")
    if _contains(text, ["계획관리", "공업", "준공업"]):
        return "데이터센터·방송통신시설 입지 설명력이 비교적 좋은 구간입니다."
    return "행위제한 요약은 공공 API 기반 1차 추정이며 토지이음에서 최종 확인이 필요합니다."


def combine_source_note(row: Dict[str, Any]) -> str:
    sources = [
        row.get("lagging_source"),
        row.get("population_source"),
        row.get("fiscal_source"),
    ]
    return " / ".join(str(item).strip() for item in sources if item not in (None, ""))


def clean_policy_source_year(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split("/") if part and part.strip() and part.strip() != "불명시"]
    return "/".join(parts)


def to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _contains(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _read_policy_rows(data_path: Path) -> Iterable[Dict[str, Any]]:
    if not data_path.exists():
        return []
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _flatten_site(site: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "lagging_index": site.get("lagging_index"),
        "lagging_rank": site.get("lagging_rank"),
        "lagging_score": site.get("lagging_score"),
        "regional_lagging_score": site.get("regional_lagging_score"),
        "lagging_band": site.get("lagging_band"),
        "population_density": site.get("population_density"),
        "population_density_score": site.get("population_density_score"),
        "population_density_band": site.get("population_density_band"),
        "fiscal_independence_rate": site.get("fiscal_independence_rate"),
        "fiscal_score": site.get("fiscal_score"),
        "fiscal_independence_score": site.get("fiscal_independence_score"),
        "fiscal_band": site.get("fiscal_band"),
        "regional_score_sum": site.get("regional_score_sum"),
        "official_adjustment": site.get("official_adjustment"),
        "site_internal_score": site.get("internal_score"),
        "site_updated_year": site.get("updated_year"),
        "site_source_note": site.get("source_note"),
        "site_judgement": site.get("judgement"),
        "policy_reference_match_status": site.get("match_status"),
        "policy_data_updated_year": site.get("updated_year"),
        "policy_source_note": site.get("source_note"),
        "policy_reflected_in_total": site.get("reflected_in_total", True),
        "policy_source_dataset": site.get("source"),
        "policy_table_region_name": site.get("policy_table_region_name"),
        "policy_table_judgement": site.get("policy_table_judgement"),
        "policy_table_match_method": site.get("policy_table_match_method"),
    }


def _flatten_power(power: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "power_self_sido": power.get("sido"),
        "power_self_sufficiency_rate": power.get("power_self_sufficiency_rate"),
        "official_power_self_score": power.get("official_power_self_score"),
        "power_self_internal_score": power.get("internal_score"),
        "power_self_updated_year": power.get("updated_year"),
        "power_self_source_note": power.get("source_note"),
        "power_self_judgement": power.get("judgement"),
        "power_self_sufficiency_not_in_total": False,
        "power_self_sufficiency_in_total": True,
    }
