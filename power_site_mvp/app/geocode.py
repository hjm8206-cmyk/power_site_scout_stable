from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
VWORLD_GEOCODER_URL = "https://api.vworld.kr/req/address"

SENSITIVE_KEYWORDS = [
    "초등학교",
    "중학교",
    "고등학교",
    "유치원",
    "어린이집",
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

RESIDENTIAL_COMPLEX_KEYWORDS = [
    "아파트",
    "주공",
    "자이",
    "푸르지오",
    "래미안",
    "힐스테이트",
    "e편한세상",
    "더샵",
    "롯데캐슬",
    "마을",
    "단지",
    "빌라",
    "연립",
    "다세대",
]


RESIDENTIAL_COMPLEX_KEYWORDS = [
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
]


def geocode_address(address: str) -> Dict[str, Any]:
    warnings = []

    kakao_result = _geocode_with_kakao(address)
    if kakao_result.get("ok"):
        kakao_result["warnings"] = warnings
        return kakao_result
    if kakao_result.get("message"):
        warnings.append(kakao_result["message"])

    vworld_result = _geocode_with_vworld(address)
    if vworld_result.get("ok"):
        vworld_result["warnings"] = warnings
        return vworld_result
    if vworld_result.get("message"):
        warnings.append(vworld_result["message"])

    return {
        "ok": False,
        "source": None,
        "message": "주소 좌표 변환에 실패했습니다. API 키와 주소 형식을 확인하세요.",
        "warnings": warnings,
    }


def search_residential_risk_places(lat: float, lng: float, radius_m: int = 1000) -> Dict[str, Any]:
    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "sensitive_facilities": [],
            "residential_complexes": [],
            "message": "Kakao Local REST API 키가 없어 민감시설·주거단지 키워드 검색을 건너뜁니다.",
        }

    sensitive = _search_keyword_group(api_key, lat, lng, SENSITIVE_KEYWORDS, radius_m, "sensitive")
    complexes = _search_keyword_group(api_key, lat, lng, RESIDENTIAL_COMPLEX_KEYWORDS, radius_m, "complex")
    errors = [item.get("message") for item in [sensitive, complexes] if item.get("message")]
    return {
        "ok": bool(sensitive.get("items") or complexes.get("items")),
        "sensitive_facilities": sensitive.get("items") or [],
        "residential_complexes": complexes.get("items") or [],
        "message": " / ".join(errors) if errors else "Kakao Local 키워드로 민감시설·주거단지 후보를 조회했습니다.",
    }


def _search_keyword_group(
    api_key: str,
    lat: float,
    lng: float,
    keywords: list[str],
    radius_m: int,
    place_type: str,
) -> Dict[str, Any]:
    items: list[Dict[str, Any]] = []
    seen: set[str] = set()
    last_message = ""
    for keyword in keywords:
        try:
            response = requests.get(
                KAKAO_KEYWORD_URL,
                headers={"Authorization": f"KakaoAK {api_key}"},
                params={
                    "query": keyword,
                    "x": lng,
                    "y": lat,
                    "radius": min(max(radius_m, 1), 20000),
                    "sort": "distance",
                    "size": 15,
                },
                timeout=5,
            )
            response.raise_for_status()
            documents = response.json().get("documents") or []
            for doc in documents:
                name = str(doc.get("place_name") or "").strip()
                x = _float_or_none(doc.get("x"))
                y = _float_or_none(doc.get("y"))
                distance = _float_or_none(doc.get("distance"))
                if x is None or y is None:
                    continue
                key = str(doc.get("id") or f"{name}:{x:.6f}:{y:.6f}")
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "id": key,
                        "name": name or keyword,
                        "keyword": keyword,
                        "type": place_type,
                        "category": doc.get("category_name"),
                        "lat": y,
                        "lng": x,
                        "distance_m": round(distance if distance is not None else _rough_distance_m(lat, lng, y, x), 1),
                        "source": "kakao_keyword",
                    }
                )
        except requests.RequestException as exc:
            last_message = f"Kakao 키워드 검색 실패({keyword}): {exc}"
        except Exception:
            last_message = f"Kakao 키워드 검색 응답 파싱 실패({keyword})"
    items.sort(key=lambda item: item.get("distance_m") or 999999)
    return {"items": items, "message": last_message}


def _geocode_with_kakao(address: str) -> Dict[str, Any]:
    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "message": "Kakao Local REST API 키가 없어 Kakao 지오코딩을 건너뜁니다."}

    try:
        response = requests.get(
            KAKAO_LOCAL_URL,
            headers={"Authorization": f"KakaoAK {api_key}"},
            params={"query": address},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        documents = payload.get("documents") or []
        if not documents:
            return {"ok": False, "message": "Kakao Local API에서 주소 결과가 없습니다."}

        doc = documents[0]
        road_address = doc.get("road_address") or {}
        jibun_address = doc.get("address") or {}
        lng = _float_or_none(doc.get("x") or road_address.get("x") or jibun_address.get("x"))
        lat = _float_or_none(doc.get("y") or road_address.get("y") or jibun_address.get("y"))
        if lat is None or lng is None:
            return {"ok": False, "message": "Kakao Local API 응답에 좌표가 없습니다."}

        region = _region_from_parts(
            road_address or jibun_address,
            ["region_1depth_name", "region_2depth_name", "region_3depth_name"],
        )
        return {
            "ok": True,
            "source": "kakao",
            "lat": lat,
            "lng": lng,
            "road_address": road_address.get("address_name"),
            "jibun_address": jibun_address.get("address_name"),
            "region": region,
        }
    except requests.RequestException as exc:
        return {"ok": False, "message": f"Kakao Local API 호출 실패: {exc}"}
    except Exception:
        return {"ok": False, "message": "Kakao Local API 응답 파싱 실패"}


def _geocode_with_vworld(address: str) -> Dict[str, Any]:
    api_key = os.getenv("VWORLD_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "message": "VWorld API 키가 없어 VWorld 지오코딩 fallback을 건너뜁니다."}

    last_message: Optional[str] = None
    for address_type in ("road", "parcel"):
        try:
            response = requests.get(
                VWORLD_GEOCODER_URL,
                params={
                    "service": "address",
                    "request": "getcoord",
                    "version": "2.0",
                    "crs": "epsg:4326",
                    "address": address,
                    "format": "json",
                    "type": address_type,
                    "key": api_key,
                },
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            result = (payload.get("response") or {}).get("result") or {}
            point = result.get("point") or {}
            lng = _float_or_none(point.get("x"))
            lat = _float_or_none(point.get("y"))
            if lat is not None and lng is not None:
                return {
                    "ok": True,
                    "source": f"vworld_{address_type}",
                    "lat": lat,
                    "lng": lng,
                    "road_address": None,
                    "jibun_address": result.get("text"),
                    "region": _coarse_region(result.get("text") or address),
                }
            status = (payload.get("response") or {}).get("status")
            last_message = f"VWorld 지오코더 결과 없음(type={address_type}, status={status})."
        except requests.RequestException as exc:
            last_message = f"VWorld 지오코더 호출 실패(type={address_type}): {exc}"
        except Exception:
            last_message = f"VWorld 지오코더 응답 파싱 실패(type={address_type})."

    return {"ok": False, "message": last_message or "VWorld 지오코더 결과가 없습니다."}


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _region_from_parts(source: Dict[str, Any], keys: list[str]) -> str:
    parts = [str(source.get(key) or "").strip() for key in keys]
    return " ".join(part for part in parts if part)


def _coarse_region(text: str) -> str:
    parts = text.split()
    return " ".join(parts[:3])


def _rough_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
