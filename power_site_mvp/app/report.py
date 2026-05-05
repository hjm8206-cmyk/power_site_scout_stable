from __future__ import annotations

import csv
import io
from typing import Any, Dict, List


DISCLAIMER = (
    "본 앱은 전력공급 가능 여부, 인허가 가능 여부, 공식 평가점수를 확정하는 도구가 아니라, "
    "전력진입 가능성이 있는 후보지를 1차로 선별하기 위한 내부 스카우트 도구입니다. "
    "기본점수는 전력·도로·인허가·민가·정책입지·경사도·전력자립도 기준으로 산정하며, "
    "별도 감점은 실무 리스크 보정을 위한 내부 기준입니다. 정책입지 가·감점과 전력자립도는 "
    "전력계통영향평가 지침서 기준을 참고한 내부 예상값이며, 최종 전력공급 가능 여부와 평가점수는 "
    "한전 기술검토, 기후에너지환경부 검토 및 전력계통영향평가 심의 절차에서 확정됩니다. "
    "도로폭·민가밀집·경사도·용도지역·인허가 가능성은 공공데이터와 위성지도 기반 1차 추정이며, "
    "현장확인 및 지자체 확인이 필요합니다."
)


def markdown_report(analysis: Dict[str, Any], manual: Any, towers: List[Any], privacy: bool = False) -> str:
    del manual, towers
    score = analysis.get("score") or {}
    metrics = score.get("metrics") or {}
    policy = analysis.get("policy") or metrics.get("policy") or {}
    buildings = analysis.get("buildings") or {}
    roads = analysis.get("roads") or {}
    permit = analysis.get("datacenter_permit") or {}
    parcel_group = analysis.get("parcel_group") or {}
    main = parcel_group.get("main") or analysis.get("parcel") or {}
    summary = analysis.get("selected_parcel_summary") or parcel_group.get("summary") or metrics.get("selected_summary") or {}
    transmission = metrics.get("transmission") or {}
    fatal_rows = _fatal_rows(score)
    anchor = parcel_group.get("anchor_point") or metrics.get("anchor_point") or analysis.get("center") or {}
    nearby_rows = _nearby_parcel_rows(parcel_group)
    scenario_rows = _scenario_rows(parcel_group, summary, metrics, score)
    area_summary = _report_area_summary(main, summary)
    area_blocked = bool(score.get("evaluation_blocked"))
    area_block_lines = [f"- {message}" for message in (score.get("blocking_messages") or [])]

    address = analysis.get("masked_address") if privacy else analysis.get("address")
    address = address or analysis.get("masked_address") or "주소 비공개"

    lines = [
        "# PowerSite MVP 후보지 리포트",
        "",
        "## 후보지 요약",
        f"- 후보지 표시 주소: {address}",
        f"- 기준 주소 면적: {_area_pair(area_summary['main_m2'], area_summary['main_pyeong'])}",
        f"- 추가 취합 면적: {_area_pair(area_summary['additional_m2'], area_summary['additional_pyeong'], zero_fallback=True)}",
        f"- 최종 합산 면적: {_area_pair(area_summary['total_m2'], area_summary['total_pyeong'])}",
        *area_block_lines,
        f"- 필지 수: {summary.get('parcel_count', '-')}",
        f"- 최종점수: {'미산정' if area_blocked else score.get('final_score', score.get('total', '-'))} / 100",
        f"- 최종등급: {'검토 불가' if area_blocked else score.get('final_grade', score.get('grade', '-'))}",
        f"- 판정: {'대용량 수전형 데이터센터 검토 불가' if area_blocked else score.get('decision_label', _grade_decision(score.get('final_grade', score.get('grade'))))}",
        f"- 상세 등급 설명: {score.get('grade_label', '-')}",
        "",
        "## 주소 필지 연결 후보 분석",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| 기준점 좌표 | {_fmt(anchor.get('lat'))}, {_fmt(anchor.get('lng'))} |",
        f"| 자동조회 필지 수 | {metrics.get('nearby_parcel_count', len(parcel_group.get('nearby_parcels') or []))} |",
        f"| 표시 필지 수 | {metrics.get('displayed_parcel_count', len(parcel_group.get('displayed_parcels') or []))} |",
        f"| 개발 후보 필지 수 | {metrics.get('development_candidate_count', parcel_group.get('development_candidate_count', '-'))} |",
        f"| 접도/진입 후보 필지 수 | {metrics.get('access_candidate_count', parcel_group.get('access_candidate_count', '-'))} |",
        f"| 제약/경계 필지 수 | {metrics.get('constraint_parcel_count', parcel_group.get('constraint_parcel_count', '-'))} |",
        f"| 구거/도로/하천 포함 여부 | {_yes_no(metrics.get('has_guggeo_or_stream', parcel_group.get('has_guggeo_or_stream')))} |",
        f"| 필지군 난이도 | {metrics.get('parcel_group_difficulty', parcel_group.get('parcel_group_difficulty', '-'))} |",
        "",
        "### 연결 필지 목록",
        "| 순번 | 지목 | 역할 | 면적(평) | 용도지역 | 건물 | 도로접함 | 선택상태 |",
        "|---:|---|---|---:|---|---|---|---|",
        *nearby_rows,
        "",
        parcel_group.get("parcel_group_judgement") or metrics.get("parcel_group_judgement") or "-",
        "",
        "주의문구: 주소 필지 연결 후보 분석은 주소가 찍힌 필지와 서로 붙어 이어지는 토지를 기준으로 초기 부지구조 난이도를 파악하기 위한 내부 스카우트 지표입니다. 구거·도로·하천·제방 등은 개발면적에 자동 합산하지 않으며, 실제 개발부지 편입 여부는 지적도, 권리관계, 지자체 협의 및 현장확인을 통해 검토해야 합니다.",
        "",
        "### 시나리오 비교",
        "| 항목 | 연결 필지 구조 | 메인 필지만 | 편입 후보 포함 |",
        "|---|---:|---:|---:|",
        *scenario_rows,
        "",
        "## 전력축 수동마킹 분석",
        f"- 송전탑 후보 수: {transmission.get('tower_count', 0)}",
        f"- 송전선 후보축 수: {transmission.get('line_axis_count', 0)}",
        f"- 전력축 관계: {transmission.get('power_axis_relation_label') or transmission.get('power_axis_relation', '-')}",
        f"- 기준점 기준 거리: {_fmt(transmission.get('power_axis_distance_from_anchor_m'))} m",
        f"- 부지경계 기준 최단거리: {_fmt(transmission.get('power_axis_distance_from_site_boundary_m'))} m",
        f"- 전력축 점수 적용 거리: {_fmt(transmission.get('power_axis_applied_distance_m'))} m",
        f"- 메인 필지만 기준 송전축 거리: {_fmt(transmission.get('power_axis_main_only_distance_m'))} m",
        f"- 편입 후보 포함 송전축 거리: {_fmt(transmission.get('power_axis_selected_site_distance_m'))} m",
        f"- 추가필지 송전축 연접 반영: {'반영됨' if transmission.get('power_axis_improved_by_added_parcel') else '미반영/해당 없음'}",
        f"- 송전축 점수 기준 부지 polygon 수: {transmission.get('power_axis_site_polygon_count', '-')}",
        f"- 거리 기준: {transmission.get('power_axis_distance_basis', '-')}",
        f"- 송전탑 후보 거리: {_fmt(transmission.get('nearest_tower_distance_from_parcel_m'))} m",
        f"- 송전선 후보축 거리: {_fmt(transmission.get('line_distance_from_parcel_m'))} m",
        f"- 선택 전압: {_voltage_label(transmission.get('voltage'))}",
        f"- 전력축 위치점수: {transmission.get('distance_score', '-')} / 20",
        f"- 전압점수: {transmission.get('voltage_score', '-')} / 10",
        f"- 전력축 최종점수: {_category_value(score, 'power_axis')} / 30",
        f"- 선하지·안전거리·한전협의 필요 여부: {'필요' if transmission.get('power_axis_needs_safety_review') else '일반 확인'}",
        _power_axis_report_notice(transmission),
        "",
        "## 도로·접도 분석",
        f"- 자동판정 도로유형: {roads.get('nearest_road_type', '-')}",
        f"- 자동판정 도로폭: {roads.get('width_class', '-')}",
        f"- 수동보정 도로폭: {roads.get('manual_override_width_class') or metrics.get('manual_override_width_class') or '없음'}",
        f"- 최종 적용 도로폭: {roads.get('final_width_class') or metrics.get('final_width_class') or '-'}",
        f"- 접도 방식: {(metrics.get('effective_access_path') or {}).get('method', '-')}",
        f"- 도로 점수: {_category_value(score, 'road_access')} / 20",
        "",
        "## 수동마킹 도로 분석",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| 수동마킹 도로 여부 | {_yes_no(metrics.get('manual_road_exists'))} |",
        f"| 수동마킹 도로폭 | {metrics.get('manual_road_width_class') or '-'} |",
        f"| 수동도로 길이 | {_fmt(metrics.get('manual_road_length_m'))} m |",
        f"| 접도된 필지 수 | {metrics.get('manual_road_touching_parcel_count', 0)} |",
        f"| 접도된 필지 목록 | {', '.join(str(item) for item in (metrics.get('manual_road_touching_parcel_ids') or [])) or '-'} |",
        f"| 접도방식 | {metrics.get('road_connection_type') or (metrics.get('effective_access_path') or {}).get('method', '-')} |",
        f"| 도로폭 기본점수 | {metrics.get('road_width_base_score', '-')} |",
        f"| 접도방식 감점 | -{metrics.get('road_connection_penalty', 0)} |",
        f"| 최종 도로점수 | {_category_value(score, 'road_access')} / 20 |",
        "",
        f"판정: {(metrics.get('manual_visual_road') or {}).get('message') or '수동마킹 도로가 없거나 자동도로 결과를 사용했습니다.'}",
        "",
        "주의문구: 수동마킹 도로는 사용자가 지도에서 지정한 도로 후보입니다. 실제 도로폭, 법정도로 여부, 공사차량 진입 가능성, 회전반경, 사용승낙 및 지자체 도로대장 확인이 필요합니다.",
        "",
        "## 정책입지 가·감점 분석",
        "### 적용 기준",
        "전력수요 입지 적정성은 지역낙후도, 인구밀도, 재정자립도 각각의 배점을 합산하여 산정하며, 합산값에 따라 -15점부터 +15점까지 가점 또는 감점이 적용됩니다.",
        "",
        "### 행정구역",
        f"- 시도: {policy.get('sido', '-')}",
        f"- 시군구: {policy.get('sigungu', '-')}",
        f"- 기준연도: {policy.get('policy_data_updated_year') or policy.get('site_updated_year') or '-'}",
        f"- 자료 출처: {policy.get('policy_source_note') or policy.get('site_source_note') or '-'}",
        f"- 매칭 상태: {policy.get('policy_reference_match_status') or metrics.get('policy_match_status') or '-'}",
        "",
        "### 세부 배점 계산표",
        "| 항목 | 원자료 값 | 지침서 기준 구간 | 배점 |",
        "|---|---:|---|---:|",
        f"| 지역낙후도 | {_fmt(policy.get('lagging_index'))} | {policy.get('lagging_band', '-')} | {_fmt(policy.get('regional_lagging_score') or policy.get('lagging_score'))} |",
        f"| 지역낙후도 순위 | {_fmt(policy.get('lagging_rank'))} | 참고값 | - |",
        f"| 인구밀도 | {_fmt(policy.get('population_density'))} | {policy.get('population_density_band', '-')} | {_fmt(policy.get('population_density_score'))} |",
        f"| 재정자립도 | {_fmt(policy.get('fiscal_independence_rate'))}% | {policy.get('fiscal_band', '-')} | {_fmt(policy.get('fiscal_independence_score') or policy.get('fiscal_score'))} |",
        "",
        "### 합산 결과",
        f"- 지역낙후도 배점: {_fmt(policy.get('regional_lagging_score') or policy.get('lagging_score'))}",
        f"- 인구밀도 배점: {_fmt(policy.get('population_density_score'))}",
        f"- 재정자립도 배점: {_fmt(policy.get('fiscal_independence_score') or policy.get('fiscal_score'))}",
        f"- 합산값: {_fmt(policy.get('regional_score_sum'))}",
        "",
        "### 지침서 기준 예상 가·감점",
        f"- 전평 공식 가·감점: {policy.get('official_adjustment', metrics.get('official_location_bonus', '-'))}점",
        "",
        "### 내부 스카우트 반영",
        f"- 정책입지 점수: {_category_value(score, 'policy_location')} / 10점",
        "- 별도 추가감점: 미적용",
        "- 총점 상한제: 미적용",
        "",
        "### 판정",
        metrics.get("policy_judgement") or policy.get("site_judgement", "-"),
        "",
        "### 주의사항",
        "정책입지 가·감점은 전력계통영향평가 지침서의 전력수요 입지 적정성 기준을 참고한 내부 예상값입니다. 최종 가·감점은 기후에너지환경부 검토 및 전력계통영향평가 심의 절차에서 확정됩니다.",
        "",
        "## 전력자립도 분석",
        f"- 시도: {policy.get('power_self_sido', '-')}",
        f"- 전력자립도: {_fmt(policy.get('power_self_sufficiency_rate'))}%",
        f"- 지침서 기준 예상점수: {policy.get('official_power_self_score', '-')} / 10",
        f"- 내부 반영점수: {_category_value(score, 'power_self')} / 5",
        f"- 판정문구: {policy.get('power_self_judgement', metrics.get('power_self_judgement', '-'))}",
        f"- 기준연도/출처: {policy.get('power_self_updated_year', '-')} / {policy.get('power_self_source_note', '-')}",
        "",
        "## 토지이음·용도지역·행위제한 분석",
        f"- 용도지역: {analysis.get('zoning', {}).get('main_zoning') or metrics.get('main_zoning', '-')}",
        f"- 용도지구·구역: {', '.join(permit.get('land_use_districts') or metrics.get('land_use_districts') or []) or '-'}",
        f"- 성장관리계획구역 여부: {metrics.get('growth_management_status')}" if metrics.get("growth_management_ok") else None,
        f"- 건폐율: {permit.get('building_coverage_ratio', '-')}",
        f"- 용적률: {permit.get('floor_area_ratio', '-')}",
        f"- 행위제한 요약: {permit.get('land_use_restriction_summary', '-')}",
        f"- 방송통신시설 가능성: {permit.get('telecom_facility_possible', '-')}",
        f"- 인허가 자동등급: {permit.get('grade', '-')}",
        f"- 인허가 설명력 점수: {_category_value(score, 'permitting')} / 20",
        f"- 추가필지 용도지역 평가: {_zoning_score_items_text(metrics)}",
        f"- 통합 용도지역 점수: {metrics.get('integrated_zoning_score', _category_value(score, 'permitting'))} / 20",
        f"- 농림지역 면적비율: {(_fmt(metrics.get('agricultural_area_ratio')) + '%') if metrics.get('agricultural_area_ratio') is not None else '미해당/비율 미산정'}",
        f"- 농림지역 혼입 판정: {metrics.get('agricultural_mixed_judgement') or metrics.get('agricultural_dominant_judgement') or '미해당'}",
        f"- 농림지역 혼입 리스크 감점: -{metrics.get('agricultural_mixed_penalty', 0)}",
        f"- 개발제한구역 감점: -{metrics.get('greenbelt_penalty', 0)}",
        f"- 농림지역 감점: {'혼입 리스크로 별도 반영' if metrics.get('agricultural_mixed_risk') else '-' + str(metrics.get('agricultural_penalty', 0))}",
        f"- 토지이음 확인 링크: {permit.get('land_use_link', 'https://www.eum.go.kr/')}",
        "",
        "## 중첩 규제구역 분석",
        f"- 기본 입지점수: {score.get('base_score', '-')}점",
        f"- 중첩규제구역 감점: -{metrics.get('overlay_regulation_penalty_total', 0)}점",
        f"- 최종점수: {score.get('final_score', score.get('total', '-'))}점",
        f"- 최종판정: {score.get('decision_label') or score.get('grade_label') or '-'}",
        "",
        "| 항목 | 상태 | 중첩비율 | 감점 | 판정 | 출처 |",
        "|---|---|---:|---:|---|---|",
        *_overlay_regulation_rows(analysis, metrics),
        "",
        "- 중첩규제구역은 가점형 평가항목이 아니며, 해당 없음 또는 미확인은 0점에서 시작합니다.",
        "- 확인된 중첩 규제구역은 용도지역 점수와 별도로 규제 리스크 감점 및 최종판정 하향에 반영합니다.",
        "- 개발제한구역·공익용산지·상수원보호구역·하천구역은 점수와 별도로 원칙적 보류로 표시합니다.",
        "",
        "## 민가밀집·민감시설 리스크 분석",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| 150m 이내 건물 수 | {buildings.get('building_count_150m', (metrics.get('building_counts') or {}).get('150m', '-'))} |",
        f"| 250m 이내 건물 수 | {buildings.get('building_count_250m', (metrics.get('building_counts') or {}).get('250m', '-'))} |",
        f"| 350m 이내 건물 수 | {buildings.get('building_count_350m', (metrics.get('building_counts') or {}).get('350m', '-'))} |",
        f"| 500m 이내 건물 수 | {buildings.get('building_count_500m', (metrics.get('building_counts') or {}).get('500m', '-'))} |",
        f"| 1km 이내 건물 수 참고값 | {buildings.get('building_count_1km', '-')} |",
        f"| 3km 이내 건물 수 참고값 | {buildings.get('building_count_3km', '-')} |",
        "| 1km 정보 감점 여부 | 참고값만 표시 / 자동감점 없음 |",
        f"| 주거노출지수 | {_fmt(_coalesce(metrics.get('residential_exposure_index'), metrics.get('residential_exposure_500m'), buildings.get('residential_exposure_500m')))} |",
        f"| 대규모 주거단지 판정 여부 | {_yes_no(metrics.get('residential_large_complex_detected'))} |",
        f"| 대규모 주거단지 판정 근거 | {metrics.get('residential_large_complex_reason') or '-'} |",
        f"| 대규모 주거단지 신뢰도 | {metrics.get('residential_large_complex_confidence') or '-'} |",
        f"| 민감시설 수 | {metrics.get('sensitive_facility_count', 0)} |",
        f"| 민감시설 자동탐지 상태 | {metrics.get('sensitive_detection_status') or '-'} |",
        f"| 중대 민감시설 수 | {metrics.get('major_sensitive_facility_count', 0)} |",
        f"| 주민수용성 참고시설 수 | {metrics.get('reference_facility_count', 0)} |",
        f"| 민감시설 종류 | {metrics.get('nearest_sensitive_facility_type') or '-'} |",
        f"| 가장 가까운 민감시설 | {metrics.get('nearest_sensitive_facility_name') or '-'} |",
        f"| 가장 가까운 참고시설 | {metrics.get('nearest_reference_facility_name') or '-'} |",
        f"| 참고시설 거리 | {_fmt(metrics.get('nearest_reference_facility_distance_m'))} |",
        f"| 민감시설 기준점 기준 거리 | {_fmt(metrics.get('sensitive_distance_from_anchor_m'))} |",
        f"| 민감시설 부지경계 기준 거리 | {_fmt(metrics.get('sensitive_distance_from_site_boundary_m'))} |",
        f"| 민감시설 감점 적용 거리 | {_fmt(metrics.get('sensitive_applied_distance_m'))} |",
        f"| 가장 가까운 민감시설 거리 | {_fmt(metrics.get('nearest_sensitive_facility_distance_m'))} |",
        f"| 민감시설 탐지 소스 | {metrics.get('sensitive_facility_source') or '-'} |",
        f"| 민감시설 신뢰도 | {metrics.get('sensitive_facility_confidence') or '-'} |",
        f"| 아파트/공동주택단지 수 | {metrics.get('residential_complex_count', 0)} |",
        f"| 주거단지 자동탐지 상태 | {metrics.get('residential_complex_detection_status') or '-'} |",
        f"| 가장 가까운 주거단지 | {metrics.get('nearest_residential_complex_name') or '-'} |",
        f"| 가장 가까운 주거단지 거리 | {_fmt(metrics.get('nearest_residential_complex_distance_m'))} |",
        f"| 주거단지 탐지 소스 | {metrics.get('residential_complex_source') or '-'} |",
        f"| 주거단지 신뢰도 | {metrics.get('residential_complex_confidence') or '-'} |",
        f"| 주거추정 신뢰도 | {metrics.get('residential_confidence') or buildings.get('residential_confidence') or '낮음'} |",
        f"| 민가밀집 기본점수 | {_category_value(score, 'residential_density')} / 10 |",
        f"| 150m 감점 후보 | -{metrics.get('residential_penalty_150m', 0)} |",
        f"| 250m 감점 후보 | -{metrics.get('residential_penalty_250m', 0)} |",
        f"| 350m 감점 후보 | -{metrics.get('residential_penalty_350m', 0)} |",
        f"| 500m 감점 후보 | -{metrics.get('residential_penalty_500m', 0)} |",
        f"| 최종 적용 근거리 민가감점 | -{metrics.get('residential_proximity_penalty_applied', 0)} |",
        f"| 중대 민감시설 감점 | -{metrics.get('major_sensitive_facility_penalty', 0)} |",
        f"| 참고시설 약한 감점 | -{metrics.get('reference_facility_penalty', 0)} |",
        f"| 민감시설 감점 | -{metrics.get('sensitive_facility_penalty', metrics.get('residential_sensitive_facility_penalty', 0))} |",
        f"| 아파트/주거단지 감점 | -{metrics.get('residential_complex_penalty', 0)} |",
        f"| 최종 민가 관련 총 감점 | -{metrics.get('residential_penalty_total', metrics.get('residential_penalty_applied', 0))} |",
        f"| 민가 관련 상한 | {_cap_text(metrics.get('residential_fatal_cap'))} |",
        f"| 감점 미적용 사유 | {metrics.get('residential_penalty_not_applied_reason') or '-'} |",
        "",
        "1km 이내 주거·시설 정보는 참고값으로만 표시하며, 자동감점은 원칙적으로 500m 이내의 명확한 주거밀집, 민감시설, 아파트단지에 한해 적용합니다.",
        "마을회관, 농가, 창고, 축사, 공장, 주유소, 공동묘지, 소규모 마을명은 대규모 주거단지로 보지 않습니다.",
        "요양시설·마을회관·소규모 종교시설은 직접적인 개발 제한 요소라기보다 주민수용성 및 공사동선 확인이 필요한 참고시설입니다.",
        metrics.get("residential_judgement", "-"),
        "",
        "주의문구: 본 민가밀집 분석은 건물 수, 건물 용도, 지도상 시설명, 공공데이터를 기반으로 한 1차 리스크 분석입니다. 실제 주거 여부, 주민수용성, 민원 가능성은 현장확인과 지자체 협의를 통해 확인해야 합니다.",
        "",
        "## 등고선·경사도 분석",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| DEM/등고선 자동조회 상태 | {metrics.get('slope_auto_status', '-')} |",
        f"| 자동 평균경사도 | {_fmt(metrics.get('slope_degree_average'))} |",
        f"| 자동 최대경사도 | {_fmt(metrics.get('slope_degree_max'))} |",
        f"| 수동 입력 경사도 | {metrics.get('slope_manual_value') or '-'} |",
        f"| 최종 적용 경사도 | {_fmt(metrics.get('slope_final_degree'))} |",
        f"| 경사도 등급 | {metrics.get('slope_grade', '수동확인')} |",
        f"| 경사도 기본점수 | {_category_value(score, 'slope') if _category_value(score, 'slope') is not None else '미반영'} / 5 |",
        f"| 경사도 감점 | -{metrics.get('slope_penalty', 0)} |",
        f"| 경사도 상한 적용 | {_cap_text(metrics.get('slope_fatal_cap'))} |",
        f"| 점수 처리 | {metrics.get('slope_score_apply_method', '미확인 / 점수 미반영')} |",
        f"| 확인 필요사항 | {'현장측량 또는 등고선 자료 확인' if metrics.get('slope_status') == 'unknown' else '-'} |",
        f"| 데이터 출처 | {metrics.get('slope_source', '-')} |",
        f"| 신뢰도 | {metrics.get('slope_confidence', '-')} |",
        "",
        metrics.get("slope_judgement", "-"),
        "",
        "## 인접필지·편입후보 분석",
        f"- 자동 표시 인접필지 수: {metrics.get('display_adjacent_count', len(parcel_group.get('display_adjacent') or []))}",
        f"- 수동 추가 후보 수: {metrics.get('manual_added_parcel_count', 0)}",
        f"- 선택된 편입 후보 수: {metrics.get('selected_parcel_count', 0)}",
        f"- 도로 접도 필지 수: {summary.get('road_contact_parcel_count', '-')}",
        f"- 권리관계 정리 난이도: {metrics.get('fragmentation_judgement', '-')}",
        "",
        "필지 수는 권리관계 정리 난이도 참고값이며, 실제 매입 가능성은 소유자 수, 협의 가능성, 지분관계 확인이 필요합니다. 대면적 후보지 기준에서 1~7필지는 양호한 범위로 봅니다.",
        "",
        "## 별도 감점 분석",
        "| 감점 사유 | 감점 |",
        "|---|---:|",
        "| 정책입지 별도 감점 | 미적용 |",
        f"| 민가 관련 총 감점 | -{metrics.get('residential_penalty_total', metrics.get('residential_penalty_applied', 0))} |",
        f"| 경사도 감점 | -{metrics.get('slope_penalty', 0)} |",
        f"| 개발제한구역 감점 | -{metrics.get('greenbelt_penalty', 0)} |",
        f"| 농림지역 감점 | -{metrics.get('agricultural_penalty', 0)} |",
        f"| 필지 분산도 감점 | -{metrics.get('fragmentation_penalty', 0)} |",
        f"| 도로 불량 감점 | -{metrics.get('road_penalty', 0)} |",
        f"| 송전탑 수동마킹 없음 감점 | -{metrics.get('power_marking_penalty', 0)} |",
        "",
        "## 치명조건 상한",
        "| 상한 사유 | 상한점수 |",
        "|---|---:|",
        *_fatal_table_lines(fatal_rows),
        "",
        "## 종합 점수표",
        "| 항목 | 점수 |",
        "|---|---:|",
        f"| 전력축 인접성 | {_category_value(score, 'power_axis')} / 30 |",
        f"| 도로·접도·공사차량 진입 | {_category_value(score, 'road_access')} / 20 |",
        f"| 용도지역·토지이음 인허가 설명력 | {_category_value(score, 'permitting')} / 20 |",
        f"| 민가밀집도 | {_category_value(score, 'residential_density')} / 10 |",
        f"| 정책입지 가·감점 | {_category_value(score, 'policy_location')} / 10 |",
        f"| 등고선·경사도 | {_category_value(score, 'slope')} / 5 |",
        f"| 전력자립도 | {_category_value(score, 'power_self')} / 5 |",
        f"| 기본점수 | {score.get('base_score', '-')} / 100 |",
        f"| 별도 감점 | -{score.get('penalty_score', 0)} |",
        f"| 치명조건 상한 | {_cap_text(score.get('fatal_cap'))} |",
        f"| 최종점수 | {'미산정' if area_blocked else score.get('final_score', score.get('total', '-'))} / 100 |",
        f"| 최종등급 | {'검토 불가' if area_blocked else score.get('final_grade', score.get('grade', '-'))} |",
        f"| 판정 | {'대용량 수전형 데이터센터 검토 불가' if area_blocked else score.get('decision_label', _grade_decision(score.get('final_grade', score.get('grade'))))} |",
        "",
        "## 현장확인 필요사항",
        *[f"- {item}" for item in score.get("next_checks", [])],
        "",
        "## 주의문구",
        DISCLAIMER,
        "",
    ]
    return "\n".join(str(line) for line in lines if line is not None)


def markdown_report(analysis: Dict[str, Any], manual: Any, towers: List[Any], privacy: bool = False) -> str:
    del manual, towers
    score = analysis.get("score") or {}
    metrics = score.get("metrics") or {}
    policy = analysis.get("policy") or metrics.get("policy") or {}
    buildings = analysis.get("buildings") or {}
    roads = analysis.get("roads") or {}
    permit = analysis.get("datacenter_permit") or {}
    parcel_group = analysis.get("parcel_group") or {}
    main = parcel_group.get("main") or analysis.get("parcel") or {}
    summary = analysis.get("selected_parcel_summary") or parcel_group.get("summary") or metrics.get("selected_summary") or {}
    transmission = metrics.get("transmission") or {}
    access = metrics.get("effective_access_path") or roads.get("access_path") or {}
    anchor = parcel_group.get("anchor_point") or metrics.get("anchor_point") or analysis.get("center") or {}
    fatal_rows = _fatal_rows(score)
    area_summary = _report_area_summary(main, summary)
    area_blocked = bool(score.get("evaluation_blocked"))

    def num(value: Any, suffix: str = "") -> str:
        formatted = _fmt(value)
        return "-" if formatted == "-" else f"{formatted}{suffix}"

    def value(value: Any, fallback: str = "-") -> str:
        return fallback if value in (None, "") else str(value)

    def yn(value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return "미확인"
        return "예" if bool(value) else "아니오"

    def cap(value: Any) -> str:
        return "미적용" if value in (None, "") else f"{value}점"

    def voltage(value_: Any) -> str:
        return {"345kv": "345kV", "154kv": "154kV", "unknown": "미확인"}.get(str(value_ or "unknown"), "미확인")

    def table(rows: List[tuple[Any, Any]]) -> List[str]:
        result = ["| 항목 | 값 |", "|---|---:|"]
        result.extend(f"| {label} | {value(item)} |" for label, item in rows)
        return result

    address = analysis.get("masked_address") if privacy else analysis.get("address")
    address = address or analysis.get("masked_address") or "주소 비공개"
    score_rows = [
        ("전력축 인접성", f"{value(_category_value(score, 'power_axis'))} / 30"),
        ("도로·접도·공사차량 진입", f"{value(_category_value(score, 'road_access'))} / 20"),
        ("용도지역·인허가 설명력", f"{value(_category_value(score, 'permitting'))} / 20"),
        ("민가밀집도", f"{value(_category_value(score, 'residential_density'))} / 10"),
        ("정책입지", f"{value(_category_value(score, 'policy_location'))} / 10"),
        ("등고선·경사도", f"{value(_category_value(score, 'slope'))} / 5"),
        ("전력자립도", f"{value(_category_value(score, 'power_self'))} / 5"),
        ("기본점수", f"{value(score.get('base_score'))} / 100"),
        ("별도 감점", f"-{value(score.get('penalty_score'), '0')}"),
        ("치명조건 상한", cap(score.get("fatal_cap"))),
        ("최종점수", "미산정 / 100" if area_blocked else f"{value(score.get('final_score', score.get('total')))} / 100"),
        ("최종등급", "검토 불가" if area_blocked else value(score.get("final_grade", score.get("grade")))),
        ("판정", "대용량 수전형 데이터센터 검토 불가" if area_blocked else score.get("decision_label", _grade_decision(score.get("final_grade", score.get("grade"))))),
        ("상세 등급 설명", value(score.get("grade_label"))),
    ]

    lines = [
        "# PowerSite MVP 후보지 리포트",
        "",
        "## 1. 후보지 요약",
        *table(
            [
                ("후보지 표시 주소", address),
                ("기준점 좌표", f"{num(anchor.get('lat'))}, {num(anchor.get('lng'))}"),
                ("기준 주소 면적", _area_pair(area_summary["main_m2"], area_summary["main_pyeong"])),
                ("추가 취합 면적", _area_pair(area_summary["additional_m2"], area_summary["additional_pyeong"], zero_fallback=True)),
                ("최종 합산 면적", _area_pair(area_summary["total_m2"], area_summary["total_pyeong"])),
                ("최소 사업구역 기준", "10,000평 이상"),
                ("종합점수 산정 여부", "미산정 / 10,000평 미만" if area_blocked else "산정 가능"),
                ("필지 수", summary.get("parcel_count", "-")),
                ("주소·지번 비공개", "예" if privacy else "아니오"),
            ]
        ),
        "",
        "## 2. 종합 점수표",
        "| 항목 | 점수 |",
        "|---|---:|",
        *[f"| {label} | {item} |" for label, item in score_rows],
        "",
        "## 3. 핵심 판정",
        f"- 판정: {'대용량 수전형 데이터센터 검토 불가' if area_blocked else score.get('decision_label', _grade_decision(score.get('final_grade', score.get('grade'))))}",
        f"- 상세 등급 설명: {'선택한 필지 총합 면적이 10,000평 미만입니다.' if area_blocked else value(score.get('grade_label'))}",
        "",
        "### 강점",
        *[f"- {item}" for item in (score.get("strengths") or ["확인된 강점 없음"])],
        "",
        "### 약점",
        *[f"- {item}" for item in (score.get("weaknesses") or ["확인된 약점 없음"])],
        "",
        "### 다음 확인사항",
        *[f"- {item}" for item in (score.get("next_checks") or ["현장확인 및 관계기관 검토 필요"])],
        "",
        "## 4. 전력축 수동마킹 분석",
        *table(
            [
                ("송전탑 후보 수", transmission.get("tower_count", 0)),
                ("송전선 후보축 수", transmission.get("line_axis_count", 0)),
                ("전력축 관계", transmission.get("power_axis_relation_label") or transmission.get("power_axis_relation")),
                ("기준점 기준 거리", num(transmission.get("power_axis_distance_from_anchor_m"), " m")),
                ("부지경계 기준 최단거리", num(transmission.get("power_axis_distance_from_site_boundary_m"), " m")),
                ("메인 필지만 기준 거리", num(transmission.get("power_axis_main_only_distance_m"), " m")),
                ("편입 후보 포함 거리", num(transmission.get("power_axis_selected_site_distance_m"), " m")),
                ("추가필지 송전축 연접 반영", "반영됨" if transmission.get("power_axis_improved_by_added_parcel") else "미반영/해당 없음"),
                ("선택 전압", voltage(transmission.get("voltage"))),
                ("전력축 위치점수", f"{value(transmission.get('distance_score'))} / 20"),
                ("전압점수", f"{value(transmission.get('voltage_score'))} / 10"),
                ("전력축 최종점수", f"{value(_category_value(score, 'power_axis'))} / 30"),
                ("선하지·안전거리 검토", "필요" if transmission.get("power_axis_needs_safety_review") else "일반 확인"),
            ]
        ),
        "",
        _power_axis_report_notice(transmission),
        "",
        "## 5. 도로·접도 분석",
        *table(
            [
                ("자동판정 도로유형", roads.get("nearest_road_type")),
                ("자동판정 도로폭", roads.get("width_class")),
                ("수동보정 도로폭", roads.get("manual_override_width_class") or metrics.get("manual_override_width_class") or "없음"),
                ("최종 적용 도로폭", roads.get("final_width_class") or metrics.get("final_width_class")),
                ("접도 방식", access.get("method") or metrics.get("road_connection_type")),
                ("수동마킹 도로", "있음" if metrics.get("manual_road_exists") else "없음"),
                ("수동마킹 도로폭", metrics.get("manual_road_width_class")),
                ("수동도로 길이", num(metrics.get("manual_road_length_m"), " m")),
                ("접도된 필지 수", metrics.get("manual_road_touching_parcel_count", 0)),
                ("도로점수", f"{value(_category_value(score, 'road_access'))} / 20"),
            ]
        ),
        "",
        "수동마킹 도로는 지도에서 지정한 도로 후보입니다. 실제 도로폭, 법정도로 여부, 공사차량 진입 가능성, 회전반경, 사용승낙 및 지자체 도로대장 확인이 필요합니다.",
        "",
        "## 6. 용도지역·인허가 설명력",
        *table(
            [
                ("용도지역", analysis.get("zoning", {}).get("main_zoning") or metrics.get("main_zoning")),
                ("자동 분류 그룹", metrics.get("zoning_group")),
                ("용도지구·구역", ", ".join(permit.get("land_use_districts") or metrics.get("land_use_districts") or []) or "-"),
                ("건폐율", permit.get("building_coverage_ratio")),
                ("용적률", permit.get("floor_area_ratio")),
                ("행위제한 요약", permit.get("land_use_restriction_summary")),
                ("방송통신시설 가능성", permit.get("telecom_facility_possible")),
                ("인허가 자동등급", permit.get("grade")),
                ("인허가 설명력 점수", f"{value(_category_value(score, 'permitting'))} / 20"),
                ("추가필지 용도지역 평가", _zoning_score_items_text(metrics)),
                ("통합 용도지역 점수", f"{value(metrics.get('integrated_zoning_score'), value(_category_value(score, 'permitting')))} / 20"),
                ("농림지역 면적비율", f"{value(metrics.get('agricultural_area_ratio'))}%" if metrics.get("agricultural_area_ratio") is not None else "미해당/비율 미산정"),
                ("농림지역 혼입 판정", metrics.get("agricultural_mixed_judgement") or metrics.get("agricultural_dominant_judgement") or "미해당"),
                ("농림지역 혼입 리스크 감점", f"-{value(metrics.get('agricultural_mixed_penalty'), '0')}"),
                ("개발제한구역 감점", f"-{value(metrics.get('greenbelt_penalty'), '0')}"),
                ("농림지역 감점", "혼입 리스크로 별도 반영" if metrics.get("agricultural_mixed_risk") else f"-{value(metrics.get('agricultural_penalty'), '0')}"),
                ("토지이음 확인 링크", permit.get("land_use_link") or "https://www.eum.go.kr/"),
            ]
        ),
        "",
        "본 인허가 등급은 용도지역·지구·구역 및 방송통신시설 허용 가능성 기반의 1차 자동등급입니다. 최종 인허가는 지자체 해석 및 개별 법령 검토가 필요합니다.",
        "",
        "## 7. 민가밀집·민감시설 리스크",
        *table(
            [
                ("150m 건물 수", buildings.get("building_count_150m", (metrics.get("building_counts") or {}).get("150m"))),
                ("250m 건물 수", buildings.get("building_count_250m", (metrics.get("building_counts") or {}).get("250m"))),
                ("350m 건물 수", buildings.get("building_count_350m", (metrics.get("building_counts") or {}).get("350m"))),
                ("500m 건물 수", buildings.get("building_count_500m", (metrics.get("building_counts") or {}).get("500m"))),
                ("1km 건물 수", f"{value(buildings.get('building_count_1km'))} (참고값)"),
                ("3km 건물 수", f"{value(buildings.get('building_count_3km'))} (참고값)"),
                ("주거노출지수", num(_coalesce(metrics.get("residential_exposure_index"), metrics.get("residential_exposure_500m"), buildings.get("residential_exposure_500m")))),
                ("주거추정 신뢰도", metrics.get("residential_confidence") or buildings.get("residential_confidence")),
                ("민감시설 자동탐지 상태", metrics.get("sensitive_detection_status")),
                ("민감시설 수", metrics.get("sensitive_facility_count", 0)),
                ("중대 민감시설 수", metrics.get("major_sensitive_facility_count", 0)),
                ("주민수용성 참고시설 수", metrics.get("reference_facility_count", 0)),
                ("가장 가까운 민감시설", metrics.get("nearest_sensitive_facility_name")),
                ("가장 가까운 참고시설", metrics.get("nearest_reference_facility_name")),
                ("참고시설 거리", num(metrics.get("nearest_reference_facility_distance_m"), " m")),
                ("민감시설 적용 거리", num(metrics.get("sensitive_applied_distance_m"), " m")),
                ("주거단지 자동탐지 상태", metrics.get("residential_complex_detection_status")),
                ("주거단지 수", metrics.get("residential_complex_count", 0)),
                ("가장 가까운 주거단지", metrics.get("nearest_residential_complex_name")),
                ("민가밀집 기본점수", f"{value(_category_value(score, 'residential_density'))} / 10"),
                ("근거리 민가감점", f"-{value(metrics.get('residential_proximity_penalty_applied'), '0')}"),
                ("중대 민감시설 감점", f"-{value(metrics.get('major_sensitive_facility_penalty'), '0')}"),
                ("참고시설 약한 감점", f"-{value(metrics.get('reference_facility_penalty'), '0')}"),
                ("민감시설 감점", f"-{value(metrics.get('sensitive_facility_penalty'), '0')}"),
                ("주거단지 감점", f"-{value(metrics.get('residential_complex_penalty'), '0')}"),
                ("최종 민가 관련 감점", f"-{value(metrics.get('residential_penalty_total'), '0')}"),
                ("민가 관련 상한", cap(metrics.get("residential_fatal_cap"))),
            ]
        ),
        "",
        value(metrics.get("residential_judgement"), "건물 수 및 지도 데이터 기반 1차 지표입니다. 실제 주거 여부와 민원 가능성은 현장확인이 필요합니다."),
        "",
        "요양시설·마을회관·소규모 종교시설은 직접적인 개발 제한 요소라기보다 주민수용성 및 공사동선 확인이 필요한 참고시설입니다.",
        "",
        "1km 이내 주거·시설 정보는 참고값으로만 표시하며, 자동감점은 원칙적으로 500m 이내의 명확한 주거밀집, 민감시설, 아파트단지에 한해 적용합니다.",
        "",
        "## 8. 정책입지 가·감점",
        *table(
            [
                ("정책자료 매칭 상태", policy.get("policy_reference_match_status") or metrics.get("policy_match_status")),
                ("정책자료 표", policy.get("policy_source_dataset")),
                ("병합표 매칭지역", policy.get("policy_table_region_name")),
                ("병합표 매칭방식", policy.get("policy_table_match_method")),
                ("시도", policy.get("sido")),
                ("시군구", policy.get("sigungu")),
                ("지역낙후도 원값", policy.get("lagging_index")),
                ("지역낙후도 순위", policy.get("lagging_rank")),
                ("지역낙후도 배점", policy.get("regional_lagging_score") or policy.get("lagging_score")),
                ("인구밀도 원값", policy.get("population_density")),
                ("인구밀도 배점", policy.get("population_density_score")),
                ("재정자립도 원값", policy.get("fiscal_independence_rate")),
                ("재정자립도 배점", policy.get("fiscal_independence_score") or policy.get("fiscal_score")),
                ("합산값", policy.get("regional_score_sum")),
                ("지침서 기준 예상 가·감점", policy.get("official_adjustment", metrics.get("official_location_bonus"))),
                ("병합표 판정", policy.get("policy_table_judgement")),
                ("정책입지 점수", f"{value(_category_value(score, 'policy_location'))} / 10"),
                ("정책입지 별도 감점", "미적용"),
                ("정책입지 상한", "미적용"),
                ("기준연도", policy.get("policy_data_updated_year") or policy.get("site_updated_year")),
                ("출처", policy.get("policy_source_note") or policy.get("site_source_note")),
            ]
        ),
        "",
        value(metrics.get("policy_judgement") or policy.get("site_judgement"), "정책입지 자료 확인이 필요합니다."),
        "",
        "## 9. 전력자립도",
        *table(
            [
                ("시도", policy.get("power_self_sido")),
                ("전력자립도", num(policy.get("power_self_sufficiency_rate"), "%")),
                ("지침서 기준 예상점수", f"{value(policy.get('official_power_self_score'))} / 10"),
                ("내부 반영점수", f"{value(_category_value(score, 'power_self'))} / 5"),
                ("기준연도", policy.get("power_self_updated_year")),
                ("출처", policy.get("power_self_source_note")),
                ("판정", policy.get("power_self_judgement", metrics.get("power_self_judgement"))),
            ]
        ),
        "",
        "## 10. 등고선·경사도",
        *table(
            [
                ("자동조회 상태", metrics.get("slope_auto_status")),
                ("자동 평균경사도", num(metrics.get("slope_degree_average"), "도")),
                ("자동 최대경사도", num(metrics.get("slope_degree_max"), "도")),
                ("수동 입력값", metrics.get("slope_manual_value")),
                ("최종 적용 경사도", num(metrics.get("slope_final_degree"), "도")),
                ("경사도 등급", metrics.get("slope_grade")),
                ("경사도 점수", f"{value(_category_value(score, 'slope'))} / 5"),
                ("경사도 감점", f"-{value(metrics.get('slope_penalty'), '0')}"),
                ("경사도 상한", cap(metrics.get("slope_fatal_cap"))),
                ("점수 처리", metrics.get("slope_score_apply_method")),
                ("자료 출처", metrics.get("slope_source")),
                ("신뢰도", metrics.get("slope_confidence")),
            ]
        ),
        "",
        value(metrics.get("slope_judgement"), "경사도는 현장측량 또는 수동확인이 필요합니다."),
        "",
        "## 11. 필지·편입 후보",
        *table(
            [
                ("표시 필지 수", metrics.get("displayed_parcel_count")),
                ("개발 후보 필지 수", metrics.get("development_candidate_count")),
                ("접도·진입 후보 필지 수", metrics.get("access_candidate_count")),
                ("제약·경계 필지 수", metrics.get("constraint_parcel_count")),
                ("필지군 난이도", metrics.get("parcel_group_difficulty")),
                ("선택된 편입 후보 수", metrics.get("selected_parcel_count")),
                ("도로 접함 필지 수", summary.get("road_contact_parcel_count")),
                ("필지군 판단", metrics.get("parcel_group_judgement")),
            ]
        ),
        "",
        "주변 필지 분석은 주소 기준점 주변의 초기 부지구조 난이도를 파악하기 위한 내부 스카우트 지표입니다. 구거·도로·하천·제방 등은 개발면적에 자동 합산하지 않습니다.",
        "",
        "## 12. 별도 감점 및 상한",
        "| 감점/상한 | 값 |",
        "|---|---:|",
        "| 정책입지 별도 감점 | 미적용 |",
        f"| 민가 관련 감점 | -{value(metrics.get('residential_penalty_total'), '0')} |",
        f"| 경사도 감점 | -{value(metrics.get('slope_penalty'), '0')} |",
        f"| 개발제한구역 감점 | -{value(metrics.get('greenbelt_penalty'), '0')} |",
        f"| 농림지역 감점 | -{value(metrics.get('agricultural_penalty'), '0')} |",
        f"| 도로 불량 감점 | -{value(metrics.get('road_penalty'), '0')} |",
        f"| 송전탑 수동마킹 없음 감점 | -{value(metrics.get('power_marking_penalty'), '0')} |",
        f"| 최종 적용 상한 | {cap(score.get('fatal_cap'))} |",
        "",
        "### 상한 적용 사유",
        *([f"- {row.get('reason')}: {row.get('cap')}점" for row in fatal_rows] if fatal_rows else ["- 적용 없음"]),
        "",
        "## 13. 주의문구",
        DISCLAIMER,
        "",
    ]
    return "\n".join(str(line) for line in lines if line is not None)


def score_csv(analysis: Dict[str, Any]) -> str:
    score = analysis.get("score") or {}
    metrics = score.get("metrics") or {}
    summary = metrics.get("selected_summary") or {}
    policy = metrics.get("policy") or analysis.get("policy") or {}
    transmission = metrics.get("transmission") or {}
    roads = analysis.get("roads") or {}
    permit = analysis.get("datacenter_permit") or {}
    buildings = analysis.get("buildings") or {}
    parcel_group = analysis.get("parcel_group") or {}
    access = metrics.get("effective_access_path") or roads.get("access_path") or {}

    row = {
        "candidate_code": analysis.get("masked_address") or analysis.get("address") or "candidate",
        "total_score": score.get("final_score", score.get("total")),
        "final_score": score.get("final_score", score.get("total")),
        "final_grade": score.get("final_grade", score.get("grade")),
        "base_score": score.get("base_score"),
        "penalty_score": score.get("penalty_score"),
        "evaluation_blocked": score.get("evaluation_blocked"),
        "score_status": score.get("score_status"),
        "minimum_business_area_pyeong": metrics.get("minimum_business_area_pyeong"),
        "business_area_total_pyeong": metrics.get("business_area_total_pyeong"),
        "business_area_total_m2": metrics.get("business_area_total_m2"),
        "business_area_eligible": metrics.get("business_area_eligible"),
        "business_area_requirement_message": metrics.get("business_area_requirement_message"),
        "fatal_cap": score.get("fatal_cap"),
        "fatal_cap_reason": "; ".join(score.get("fatal_cap_reasons") or []),
        "penalty_reasons": "; ".join(item.get("label", "") for item in score.get("penalty_items") or []),
        "anchor_lat": metrics.get("anchor_lat"),
        "anchor_lng": metrics.get("anchor_lng"),
        "nearby_parcel_count": metrics.get("nearby_parcel_count"),
        "displayed_parcel_count": metrics.get("displayed_parcel_count"),
        "development_candidate_count": metrics.get("development_candidate_count"),
        "access_candidate_count": metrics.get("access_candidate_count"),
        "constraint_parcel_count": metrics.get("constraint_parcel_count"),
        "has_constraint_parcels": metrics.get("has_constraint_parcels"),
        "has_guggeo_or_stream": metrics.get("has_guggeo_or_stream"),
        "parcel_group_difficulty": metrics.get("parcel_group_difficulty"),
        "parcel_group_judgement": metrics.get("parcel_group_judgement"),
        "main_parcel_role": metrics.get("main_parcel_role"),
        "main_parcel_is_development_candidate": metrics.get("main_parcel_is_development_candidate"),
        "selected_development_parcel_count": metrics.get("selected_development_parcel_count"),
        "selected_access_parcel_count": metrics.get("selected_access_parcel_count"),
        "selected_constraint_parcel_count": metrics.get("selected_constraint_parcel_count"),
        "fragmentation_penalty": metrics.get("fragmentation_penalty"),
        "fragmentation_judgement": metrics.get("fragmentation_judgement"),
        "parcel_compactness_score_cap_by_group_difficulty": metrics.get("parcel_compactness_score_cap_by_group_difficulty"),
        "scenario_0_group_difficulty": metrics.get("scenario_0_group_difficulty"),
        "scenario_a_main_only_score": metrics.get("scenario_a_main_only_score"),
        "scenario_b_selected_site_score": metrics.get("scenario_b_selected_site_score"),
        "power_axis_score_30": _category_value(score, "power_axis"),
        "power_axis_relation": transmission.get("power_axis_relation"),
        "power_axis_distance_from_site_boundary_m": transmission.get("power_axis_distance_from_site_boundary_m"),
        "power_axis_distance_from_anchor_m": transmission.get("power_axis_distance_from_anchor_m"),
        "power_axis_main_only_distance_m": transmission.get("power_axis_main_only_distance_m"),
        "power_axis_selected_site_distance_m": transmission.get("power_axis_selected_site_distance_m"),
        "power_axis_improved_by_added_parcel": transmission.get("power_axis_improved_by_added_parcel"),
        "power_axis_site_polygon_count": transmission.get("power_axis_site_polygon_count"),
        "power_axis_selected_parcel_count": transmission.get("power_axis_selected_parcel_count"),
        "power_axis_location_score_20": transmission.get("power_axis_location_score_20"),
        "power_voltage_type": _voltage_label(transmission.get("voltage")),
        "power_distance_score": transmission.get("distance_score"),
        "power_voltage_score": transmission.get("voltage_score"),
        "power_voltage_score_10": transmission.get("power_voltage_score_10"),
        "tower_distance_m": transmission.get("nearest_tower_distance_from_parcel_m"),
        "line_axis_distance_m": transmission.get("line_distance_from_parcel_m"),
        "transmission_line_crosses_site": transmission.get("transmission_line_crosses_site"),
        "transmission_tower_inside_site": transmission.get("transmission_tower_inside_site"),
        "transmission_axis_boundary_touch": transmission.get("transmission_axis_boundary_touch"),
        "power_axis_needs_safety_review": transmission.get("power_axis_needs_safety_review"),
        "road_score_20": _category_value(score, "road_access"),
        "road_manual_override": roads.get("manual_override_width_class") or metrics.get("manual_override_width_class"),
        "construction_access_difficult_manual": metrics.get("construction_access_difficult_manual"),
        "road_final_width_class": roads.get("final_width_class") or metrics.get("final_width_class"),
        "road_connection_type": access.get("method"),
        "road_connection_parcel_count": len(access.get("via_parcels") or []),
        "road_score_before_selection": roads.get("road_score_before_selection"),
        "road_score_after_selection": _category_value(score, "road_access"),
        "road_improved_by_added_parcel": bool(access.get("selected_access_improvement")),
        "manual_road_exists": metrics.get("manual_road_exists"),
        "manual_road_width_class": metrics.get("manual_road_width_class"),
        "manual_road_length_m": metrics.get("manual_road_length_m"),
        "manual_road_touching_main_parcel": metrics.get("manual_road_touching_main_parcel"),
        "manual_road_touching_selected_parcel": metrics.get("manual_road_touching_selected_parcel"),
        "manual_road_touching_access_parcel": metrics.get("manual_road_touching_access_parcel"),
        "manual_road_touching_parcel_count": metrics.get("manual_road_touching_parcel_count"),
        "manual_road_touching_parcel_ids": "; ".join(str(item) for item in (metrics.get("manual_road_touching_parcel_ids") or [])),
        "road_touch_distance_m": metrics.get("road_touch_distance_m"),
        "road_width_base_score": metrics.get("road_width_base_score"),
        "road_connection_penalty": metrics.get("road_connection_penalty"),
        "road_score_source": metrics.get("road_score_source"),
        "manual_road_applied_to_score": metrics.get("manual_road_applied_to_score"),
        "permit_score_20": _category_value(score, "permitting"),
        "zoning_main": metrics.get("main_zoning"),
        "zoning_group": metrics.get("zoning_group"),
        "zoning_score_items": _zoning_score_items_text(metrics),
        "integrated_zoning_score": metrics.get("integrated_zoning_score"),
        "integrated_zoning_source": metrics.get("integrated_zoning_source"),
        "integrated_zoning_parcel_id": metrics.get("integrated_zoning_parcel_id"),
        "land_use_districts": "; ".join(permit.get("land_use_districts") or metrics.get("land_use_districts") or []),
        "growth_management_zone": metrics.get("growth_management_status"),
        "building_coverage_ratio": permit.get("building_coverage_ratio"),
        "floor_area_ratio": permit.get("floor_area_ratio"),
        "land_use_restriction_summary": permit.get("land_use_restriction_summary"),
        "telecom_facility_possible": permit.get("telecom_facility_possible"),
        "permit_grade": permit.get("grade"),
        "permit_confidence": permit.get("permit_confidence"),
        "overlay_regulation_detected_labels": "; ".join(metrics.get("overlay_regulation_detected_labels") or []),
        "overlay_regulation_unknown_labels": "; ".join(metrics.get("overlay_regulation_unknown_labels") or []),
        "overlay_regulation_penalty_total": metrics.get("overlay_regulation_penalty_total"),
        "overlay_regulation_hold_decision": metrics.get("overlay_regulation_hold_decision"),
        "overlay_regulation_hold_reasons": "; ".join(metrics.get("overlay_regulation_hold_reasons") or []),
        "overlay_regulation_manual_check_items": "; ".join(metrics.get("overlay_regulation_manual_check_items") or []),
        "greenbelt_status": metrics.get("greenbelt_status"),
        "greenbelt_detected": metrics.get("greenbelt_detected"),
        "greenbelt_overlap_ratio": metrics.get("greenbelt_overlap_ratio"),
        "greenbelt_penalty": metrics.get("greenbelt_penalty"),
        "agricultural_penalty": metrics.get("agricultural_penalty"),
        "agricultural_area_m2": metrics.get("agricultural_area_m2"),
        "agricultural_area_ratio": metrics.get("agricultural_area_ratio"),
        "agricultural_mixed_risk": metrics.get("agricultural_mixed_risk"),
        "agricultural_mixed_penalty": metrics.get("agricultural_mixed_penalty"),
        "agricultural_mixed_judgement": metrics.get("agricultural_mixed_judgement"),
        "agricultural_dominant": metrics.get("agricultural_dominant"),
        "agricultural_dominant_judgement": metrics.get("agricultural_dominant_judgement"),
        "building_count_150m": buildings.get("building_count_150m", (metrics.get("building_counts") or {}).get("150m")),
        "building_count_250m": buildings.get("building_count_250m", (metrics.get("building_counts") or {}).get("250m")),
        "building_count_350m": buildings.get("building_count_350m", (metrics.get("building_counts") or {}).get("350m")),
        "building_count_500m": buildings.get("building_count_500m", (metrics.get("building_counts") or {}).get("500m")),
        "building_count_1km_reference": buildings.get("building_count_1km", (metrics.get("building_counts") or {}).get("1km")),
        "building_count_3km_reference": buildings.get("building_count_3km", (metrics.get("building_counts") or {}).get("3km")),
        "residential_exposure_150m": _coalesce(metrics.get("residential_exposure_150m"), buildings.get("residential_exposure_150m")),
        "residential_exposure_250m": _coalesce(metrics.get("residential_exposure_250m"), buildings.get("residential_exposure_250m")),
        "residential_exposure_350m": _coalesce(metrics.get("residential_exposure_350m"), buildings.get("residential_exposure_350m")),
        "residential_exposure_500m": _coalesce(metrics.get("residential_exposure_500m"), buildings.get("residential_exposure_500m")),
        "residential_exposure_index": _coalesce(metrics.get("residential_exposure_index"), metrics.get("residential_exposure_500m"), buildings.get("residential_exposure_500m")),
        "residential_confidence": metrics.get("residential_confidence") or buildings.get("residential_confidence"),
        "residential_large_complex_detected": metrics.get("residential_large_complex_detected"),
        "residential_large_complex_reason": metrics.get("residential_large_complex_reason"),
        "residential_large_complex_confidence": metrics.get("residential_large_complex_confidence"),
        "residential_score_10": _category_value(score, "residential_density"),
        "residential_penalty_150m": metrics.get("residential_penalty_150m"),
        "residential_penalty_250m": metrics.get("residential_penalty_250m"),
        "residential_penalty_350m": metrics.get("residential_penalty_350m"),
        "residential_penalty_500m": metrics.get("residential_penalty_500m"),
        "residential_proximity_penalty": metrics.get("residential_proximity_penalty_applied"),
        "residential_proximity_penalty_applied": metrics.get("residential_proximity_penalty_applied"),
        "sensitive_facility_count": metrics.get("sensitive_facility_count"),
        "major_sensitive_facility_count": metrics.get("major_sensitive_facility_count"),
        "reference_facility_count": metrics.get("reference_facility_count"),
        "sensitive_detection_status": metrics.get("sensitive_detection_status"),
        "sensitive_facility_detected": metrics.get("sensitive_facility_detected"),
        "nearest_sensitive_facility_type": metrics.get("nearest_sensitive_facility_type"),
        "nearest_sensitive_facility_name": metrics.get("nearest_sensitive_facility_name"),
        "nearest_sensitive_facility_distance_m": metrics.get("nearest_sensitive_facility_distance_m"),
        "nearest_major_sensitive_facility_name": metrics.get("nearest_major_sensitive_facility_name"),
        "nearest_major_sensitive_facility_type": metrics.get("nearest_major_sensitive_facility_type"),
        "nearest_major_sensitive_facility_distance_m": metrics.get("nearest_major_sensitive_facility_distance_m"),
        "nearest_reference_facility_name": metrics.get("nearest_reference_facility_name"),
        "nearest_reference_facility_type": metrics.get("nearest_reference_facility_type"),
        "nearest_reference_facility_distance_m": metrics.get("nearest_reference_facility_distance_m"),
        "sensitive_distance_from_anchor_m": metrics.get("sensitive_distance_from_anchor_m"),
        "sensitive_distance_from_site_boundary_m": metrics.get("sensitive_distance_from_site_boundary_m"),
        "sensitive_applied_distance_m": metrics.get("sensitive_applied_distance_m"),
        "sensitive_facility_penalty_applied": metrics.get("sensitive_facility_penalty_applied"),
        "major_sensitive_facility_penalty": metrics.get("major_sensitive_facility_penalty"),
        "reference_facility_penalty": metrics.get("reference_facility_penalty"),
        "reference_facility_manual_check": metrics.get("reference_facility_manual_check"),
        "reference_facility_judgement": metrics.get("reference_facility_judgement"),
        "sensitive_facility_penalty": metrics.get("sensitive_facility_penalty"),
        "sensitive_facility_fatal_cap": metrics.get("sensitive_facility_fatal_cap"),
        "sensitive_facility_source": metrics.get("sensitive_facility_source"),
        "sensitive_facility_confidence": metrics.get("sensitive_facility_confidence"),
        "residential_complex_detection_status": metrics.get("residential_complex_detection_status"),
        "residential_complex_count": metrics.get("residential_complex_count"),
        "nearest_residential_complex_name": metrics.get("nearest_residential_complex_name"),
        "nearest_residential_complex_distance_m": metrics.get("nearest_residential_complex_distance_m"),
        "residential_complex_penalty": metrics.get("residential_complex_penalty"),
        "residential_complex_fatal_cap": metrics.get("residential_complex_fatal_cap"),
        "residential_complex_source": metrics.get("residential_complex_source"),
        "residential_complex_confidence": metrics.get("residential_complex_confidence"),
        "residential_cluster_sensitive_penalty": metrics.get("residential_cluster_sensitive_penalty"),
        "residential_penalty_total": metrics.get("residential_penalty_total"),
        "residential_penalty_applied": metrics.get("residential_penalty_applied"),
        "residential_reference_only_1km": metrics.get("residential_reference_only_1km"),
        "residential_penalty_not_applied_reason": metrics.get("residential_penalty_not_applied_reason"),
        "residential_fatal_cap": metrics.get("residential_fatal_cap"),
        "residential_judgement": metrics.get("residential_judgement"),
        "residential_penalty_applied_to_final_score": metrics.get("residential_penalty_applied_to_final_score"),
        "official_location_bonus": policy.get("official_adjustment", metrics.get("official_location_bonus")),
        "policy_location_score_10": _category_value(score, "policy_location"),
        "policy_penalty_modifier": 0,
        "policy_fatal_cap": None,
        "policy_judgement": metrics.get("policy_judgement"),
        "regional_score_sum": policy.get("regional_score_sum"),
        "lagging_index": policy.get("lagging_index"),
        "lagging_rank": policy.get("lagging_rank"),
        "lagging_score": policy.get("regional_lagging_score") or policy.get("lagging_score"),
        "population_density": policy.get("population_density"),
        "population_density_score": policy.get("population_density_score"),
        "fiscal_independence_rate": policy.get("fiscal_independence_rate"),
        "fiscal_score": policy.get("fiscal_independence_score") or policy.get("fiscal_score"),
        "policy_reference_match_status": policy.get("policy_reference_match_status") or metrics.get("policy_match_status"),
        "policy_data_updated_year": policy.get("policy_data_updated_year") or policy.get("site_updated_year"),
        "policy_source_note": policy.get("policy_source_note") or policy.get("site_source_note"),
        "policy_score_applied_to_total": metrics.get("policy_score_applied_to_total", True),
        "policy_saved_from_user_input": False,
        "slope_degree": metrics.get("slope_degree"),
        "slope_auto_status": metrics.get("slope_auto_status"),
        "slope_degree_average": metrics.get("slope_degree_average"),
        "slope_degree_max": metrics.get("slope_degree_max"),
        "slope_manual_value": metrics.get("slope_manual_value"),
        "slope_final_degree": metrics.get("slope_final_degree"),
        "slope_confidence": metrics.get("slope_confidence"),
        "slope_grade": metrics.get("slope_grade"),
        "slope_score_5": _category_value(score, "slope"),
        "slope_penalty": metrics.get("slope_penalty"),
        "slope_fatal_cap": metrics.get("slope_fatal_cap"),
        "slope_judgement": metrics.get("slope_judgement"),
        "slope_source": metrics.get("slope_source"),
        "power_self_sufficiency_rate": policy.get("power_self_sufficiency_rate"),
        "official_power_self_score": policy.get("official_power_self_score"),
        "internal_power_self_score_5": _category_value(score, "power_self"),
        "power_self_sufficiency_year": policy.get("power_self_updated_year"),
        "power_self_sufficiency_source_note": policy.get("power_self_source_note"),
        "power_self_sufficiency_match_status": metrics.get("power_self_match_status"),
        "adjacent_parcels_auto_count": len(parcel_group.get("display_adjacent") or []),
        "adjacent_parcels_manual_added_count": metrics.get("manual_added_parcel_count", 0),
        "selected_parcels_count": metrics.get("selected_parcel_count", 0),
        "total_area_after_selection_m2": summary.get("total_area_m2"),
        "total_area_after_selection_pyeong": summary.get("total_area_pyeong"),
    }
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(row.keys()))
    writer.writeheader()
    writer.writerow(row)
    return buffer.getvalue()


def _category_value(score: Dict[str, Any], key: str) -> Any:
    for item in score.get("categories") or []:
        if item.get("key") == key:
            return item.get("score")
    return None


def _zoning_score_items_text(metrics: Dict[str, Any]) -> str:
    items = metrics.get("zoning_score_items") or []
    added = [item for item in items if item.get("scope") != "기준 필지"]
    if not added:
        return "추가필지 없음"
    parts = []
    for item in added:
        penalty = item.get("penalty") or 0
        penalty_text = f", 감점 -{penalty}" if penalty else ""
        parts.append(
            f"{item.get('scope')}: {item.get('zoning') or '미확인'}, {item.get('score', 0)} / 20{penalty_text}"
        )
    return "; ".join(parts)


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.1f}"
    except (TypeError, ValueError):
        return str(value)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _numeric_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pyeong_from_m2(value: Any) -> float | None:
    number = _numeric_or_none(value)
    return None if number is None else number / 3.305785


def _report_area_summary(main: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, float | None]:
    main_m2 = _numeric_or_none(_coalesce(main.get("area_m2"), summary.get("main_area_m2")))
    main_pyeong = _numeric_or_none(_coalesce(main.get("area_pyeong"), summary.get("main_area_pyeong"), _pyeong_from_m2(main_m2)))
    additional_m2 = _numeric_or_none(_coalesce(summary.get("incorporation_area_m2"), 0)) or 0.0
    additional_pyeong = _numeric_or_none(_coalesce(summary.get("incorporation_area_pyeong"), _pyeong_from_m2(additional_m2), 0)) or 0.0
    if main_m2 is None:
        total_m2 = _numeric_or_none(summary.get("total_area_m2"))
    else:
        total_m2 = main_m2 + additional_m2
    if main_pyeong is None:
        total_pyeong = _numeric_or_none(_coalesce(summary.get("total_area_pyeong"), _pyeong_from_m2(total_m2)))
    else:
        total_pyeong = main_pyeong + additional_pyeong
    return {
        "main_m2": main_m2,
        "main_pyeong": main_pyeong,
        "additional_m2": additional_m2,
        "additional_pyeong": additional_pyeong,
        "total_m2": total_m2,
        "total_pyeong": total_pyeong,
    }


def _area_pair(area_m2: Any, area_pyeong: Any, zero_fallback: bool = False) -> str:
    m2 = _numeric_or_none(area_m2)
    pyeong = _numeric_or_none(_coalesce(area_pyeong, _pyeong_from_m2(m2)))
    if m2 is None and pyeong is None:
        if not zero_fallback:
            return "-"
        m2 = 0.0
        pyeong = 0.0
    return f"{_fmt(m2 or 0)} m2 / {_fmt(pyeong or 0)} 평"


def _cap_text(value: Any) -> str:
    return "미적용" if value in (None, "") else f"{value}점"


def _voltage_label(value: Any) -> str:
    return {"345kv": "345kV", "154kv": "154kV", "unknown": "미확인"}.get(str(value or "unknown"), "미확인")


def _grade_decision(value: Any) -> str:
    return {"A": "우선검토", "B": "검토가능", "C": "추가확인", "D": "낮은 우선순위"}.get(
        str(value or "").upper(),
        "미확인",
    )


def _overlay_regulation_rows(analysis: Dict[str, Any], metrics: Dict[str, Any]) -> List[str]:
    regulations = analysis.get("overlay_regulations") or metrics.get("overlay_regulations") or {}
    items = regulations.get("items") or metrics.get("overlay_regulation_items") or []
    visible_items = [
        item
        for item in items
        if item.get("detected")
        or item.get("suspected")
        or "의심" in str(item.get("status") or "")
        or _fmt(item.get("overlay_penalty")) not in {"-", "0", "0.0"}
    ]
    if not visible_items:
        return ["| 중첩규제구역 | 특이사항 없음 | - | 0 | - | 자동감점 없음 |"]
    rows = []
    for item in visible_items:
        ratio = _fmt(item.get("overlap_ratio")) if item.get("overlap_ratio") is not None else "-"
        penalty = f"-{_fmt(item.get('overlay_penalty'))}" if item.get("overlay_penalty") else "-"
        decision = item.get("overlay_decision") or ("수동확인 필요" if item.get("suspected") else "-")
        rows.append(
            f"| {item.get('label', item.get('key', '-'))} | {item.get('status', '미확인')} | {ratio} | {penalty} | {decision} | {item.get('source') or item.get('message') or '-'} |"
        )
    return rows


def _power_axis_report_notice(transmission: Dict[str, Any]) -> str:
    relation = str(transmission.get("power_axis_relation") or "")
    distance = transmission.get("power_axis_applied_distance_m")
    if relation in {"line_crosses_site", "tower_inside_site", "line_touches_boundary", "tower_on_boundary"}:
        return (
            "송전탑 또는 송전선 후보축이 부지 내부 또는 부지 경계부에 있어 전력축 인접성은 매우 우수하게 평가됩니다. "
            "다만 실제 개발 시에는 선하지, 안전거리, 점용, 이설 가능성, 보호구역, 전자파 민원, 한전 협의 및 계통연계 검토가 필요합니다."
        )
    try:
        distance_value = float(distance)
    except (TypeError, ValueError):
        return "송전탑·송전선 후보는 위성지도 수동마킹 기반이며, 실제 전압·소유·계통연계 여부는 한전 및 현장확인이 필요합니다."
    if 150 < distance_value <= 500:
        return "송전탑·송전선 후보가 150m 초과 500m 이내에 있어 참고 가능한 전력축 인접성은 있으나, 부지 내부 또는 경계부 인접 수준의 강한 점수로 보지는 않았습니다."
    if distance_value > 500:
        return "송전탑·송전선 후보가 500m를 초과하여 강한 전력축 인접성으로 보지 않았습니다."
    return "송전탑·송전선 후보는 위성지도 수동마킹 기반이며, 실제 전압·소유·계통연계 여부는 한전 및 현장확인이 필요합니다."


def _nearby_parcel_rows(parcel_group: Dict[str, Any]) -> List[str]:
    rows = parcel_group.get("nearby_parcel_table") or parcel_group.get("displayed_parcels") or []
    if not rows:
        return ["| - | - | - | - | - | - | - | - |"]
    result = []
    for index, item in enumerate(rows[:10], start=1):
        result.append(
            "| "
            f"{item.get('index') or index} | "
            f"{item.get('land_category', '-')} | "
            f"{_parcel_role_label(item.get('parcel_role'))} | "
            f"{_fmt(item.get('area_pyeong'))} | "
            f"{item.get('zoning') or '-'} | "
            f"{_yes_no(item.get('has_building'))} | "
            f"{_yes_no(item.get('has_road_contact'))} | "
            f"{item.get('selection_status') or '-'} |"
        )
    return result


def _scenario_rows(
    parcel_group: Dict[str, Any],
    selected_summary: Dict[str, Any],
    metrics: Dict[str, Any],
    score: Dict[str, Any],
) -> List[str]:
    scenarios = parcel_group.get("site_scenarios") or metrics.get("site_scenarios") or {}
    s0 = scenarios.get("scenario_0") or {}
    sa = scenarios.get("scenario_a") or {}
    sb = scenarios.get("scenario_b") or {}
    rows = [
        ("총면적", _fmt(s0.get("total_area_m2")), _fmt(sa.get("total_area_m2")), _fmt(selected_summary.get("total_area_m2") or sb.get("total_area_m2"))),
        (
            "개발 후보 필지 수",
            s0.get("development_candidate_count", "-"),
            sa.get("development_candidate_count", "-"),
            selected_summary.get("selected_development_parcel_count", sb.get("development_candidate_count", "-")),
        ),
        (
            "제약 필지 수",
            s0.get("constraint_parcel_count", "-"),
            sa.get("constraint_parcel_count", "-"),
            selected_summary.get("selected_constraint_parcel_count", sb.get("constraint_parcel_count", "-")),
        ),
        ("도로 접도", _yes_no(s0.get("road_contact")), _yes_no(sa.get("road_contact")), _yes_no(sb.get("road_contact"))),
        ("도로 점수", "-", "-", _category_value(score, "road_access")),
        (
            "부지규모·집적성 점수",
            f"{metrics.get('parcel_compactness_score_cap_by_group_difficulty', '-')}점 상한",
            f"{metrics.get('parcel_compactness_score_cap_by_group_difficulty', '-')}점 상한",
            f"{metrics.get('parcel_compactness_score_cap_by_group_difficulty', '-')}점 상한",
        ),
        (
            "필지군 난이도",
            s0.get("parcel_group_difficulty") or parcel_group.get("parcel_group_difficulty") or "-",
            sa.get("parcel_group_difficulty") or parcel_group.get("parcel_group_difficulty") or "-",
            sb.get("parcel_group_difficulty") or parcel_group.get("parcel_group_difficulty") or "-",
        ),
        ("최종점수", "-", "-", "미산정" if score.get("evaluation_blocked") else score.get("final_score", score.get("total", "-"))),
    ]
    return [f"| {label} | {a} | {b} | {c} |" for label, a, b, c in rows]


def _parcel_role_label(value: Any) -> str:
    return {
        "development_candidate": "개발 후보",
        "access_candidate": "접도·진입",
        "constraint_parcel": "제약·경계",
        "unknown": "수동확인",
    }.get(str(value or "unknown"), "수동확인")


def _yes_no(value: Any) -> str:
    if isinstance(value, str):
        if value in {"예", "아니오", "미확인", "수동확인 필요"}:
            return value
        return "예" if value.lower() in {"true", "yes", "y"} else ("아니오" if value.lower() in {"false", "no", "n"} else value)
    if value is None:
        return "미확인"
    return "예" if bool(value) else "아니오"


def _fatal_rows(score: Dict[str, Any]) -> List[Dict[str, Any]]:
    cap = score.get("fatal_cap")
    reasons = score.get("fatal_cap_reasons") or []
    if cap in (None, ""):
        return []
    return [{"reason": reason, "cap": cap} for reason in reasons] or [{"reason": "치명조건 상한", "cap": cap}]


def _fatal_table_lines(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return ["| 적용 없음 | - |"]
    return [f"| {row.get('reason')} | {row.get('cap')} |" for row in rows]
