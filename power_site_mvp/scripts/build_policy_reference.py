from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw_policy_sources"
OUTPUT = DATA_DIR / "policy_reference.csv"
META = DATA_DIR / "policy_source_meta.json"
FIELDS = [
    "sido",
    "sigungu",
    "lagging_index",
    "population_density",
    "fiscal_independence_rate",
    "updated_year",
    "lagging_source",
    "population_source",
    "fiscal_source",
    "match_key",
]


SIDO_ALIASES = {
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


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    population = read_source("population_density.csv", "population_density_manual.csv")
    fiscal = read_source("fiscal_independence.csv", "fiscal_independence_manual.csv")
    lagging = read_source("lagging_index.csv", "kdi_lagging_index_manual.csv")

    merged: Dict[str, Dict[str, str]] = {}
    for row in population:
        key = build_match_key(row.get("sido", ""), row.get("sigungu", ""))
        item = merged.setdefault(key, base_row(row))
        item["population_density"] = row.get("population_density", "")
        item["population_source"] = row.get("source_note", "")
        item["updated_year"] = newest_year(item.get("updated_year", ""), row.get("year", ""))
    for row in fiscal:
        key = build_match_key(row.get("sido", ""), row.get("sigungu", ""))
        item = merged.setdefault(key, base_row(row))
        item["fiscal_independence_rate"] = row.get("fiscal_independence_rate", "")
        item["fiscal_source"] = row.get("source_note", "")
        item["updated_year"] = newest_year(item.get("updated_year", ""), row.get("year", ""))
    for row in lagging:
        key = build_match_key(row.get("sido", ""), row.get("sigungu", ""))
        item = merged.setdefault(key, base_row(row))
        item["lagging_index"] = row.get("lagging_index", "")
        item["lagging_source"] = row.get("source_note", "")
        item["updated_year"] = newest_year(item.get("updated_year", ""), row.get("year", ""))

    rows = [row for row in merged.values() if row.get("sido") and row.get("sigungu")]
    rows.sort(key=lambda row: row["match_key"])
    write_rows(OUTPUT, rows)
    write_meta(population, fiscal, lagging)
    print(f"policy_reference rows={len(rows)} -> {OUTPUT}")


def read_source(primary_name: str, fallback_name: str) -> List[Dict[str, str]]:
    primary = RAW_DIR / primary_name
    fallback = RAW_DIR / fallback_name
    path = primary if primary.exists() else fallback
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def base_row(row: Dict[str, str]) -> Dict[str, str]:
    sido = normalize_sido(row.get("sido", ""))
    sigungu = normalize_sigungu(row.get("sigungu", ""))
    return {
        "sido": sido,
        "sigungu": sigungu,
        "lagging_index": "",
        "population_density": "",
        "fiscal_independence_rate": "",
        "updated_year": row.get("year", ""),
        "lagging_source": "",
        "population_source": "",
        "fiscal_source": "",
        "match_key": build_match_key(sido, sigungu),
    }


def write_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def write_meta(population: List[Dict[str, str]], fiscal: List[Dict[str, str]], lagging: List[Dict[str, str]]) -> None:
    meta = {
        "population_density_source": source_summary(population, "population_density_manual.csv fallback"),
        "fiscal_independence_source": source_summary(fiscal, "fiscal_independence_manual.csv fallback"),
        "lagging_index_source": source_summary(lagging, "kdi_lagging_index_manual.csv fallback"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "notes": "KOSIS, 지방재정365, KDI 자동수집 스크립트 실패 시 raw_policy_sources 수동 CSV를 병합합니다.",
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def source_summary(rows: List[Dict[str, str]], fallback: str) -> str:
    notes = sorted({row.get("source_note", "") for row in rows if row.get("source_note")})
    return "; ".join(notes[:5]) if notes else fallback


def normalize_sido(value: str) -> str:
    text = str(value or "").strip()
    return SIDO_ALIASES.get(text, text)


def normalize_sigungu(value: str) -> str:
    text = str(value or "").strip()
    for suffix in ["시", "군"]:
        if text.endswith(suffix) and len(text) > 2:
            return text[: -len(suffix)]
    return text


def build_match_key(sido: str, sigungu: str) -> str:
    return f"{normalize_sido(sido)}|{normalize_sigungu(sigungu)}"


def newest_year(*values: str) -> str:
    years = [str(value).strip() for value in values if str(value or "").strip()]
    if not years:
        return ""
    numeric = [int(value) for value in years if value.isdigit()]
    if numeric:
        return str(max(numeric))
    return years[-1]


if __name__ == "__main__":
    main()
