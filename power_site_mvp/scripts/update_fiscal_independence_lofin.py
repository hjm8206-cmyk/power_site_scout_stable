from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Dict, Iterable, List

try:
    import requests
except Exception:  # pragma: no cover - optional during offline fallback
    requests = None


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw_policy_sources"
OUTPUT = RAW_DIR / "fiscal_independence.csv"
FALLBACK = RAW_DIR / "fiscal_independence_manual.csv"
FIELDS = ["sido", "sigungu", "fiscal_independence_rate", "year", "source_note"]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env")
    rows = fetch_lofin_rows()
    if not rows:
        rows = read_rows(FALLBACK)
    write_rows(OUTPUT, rows)
    print(f"fiscal_independence rows={len(rows)} -> {OUTPUT}")


def fetch_lofin_rows() -> List[Dict[str, str]]:
    service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    url = os.getenv("LOFIN_FISCAL_INDEPENDENCE_URL", "").strip()
    if not service_key or not url or requests is None:
        return []
    try:
        response = requests.get(url, params={"serviceKey": service_key, "type": "json"}, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    records = payload if isinstance(payload, list) else payload.get("data") or payload.get("items") or []
    rows: List[Dict[str, str]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        sido = first(item, "sido", "시도", "ctpvNm", "CTPRVN_NM")
        sigungu = first(item, "sigungu", "시군구", "sggNm", "SIGUNGU_NM")
        final_rate = first(item, "fiscal_independence_rate_final", "재정자립도최종", "finalRate")
        original_rate = first(item, "fiscal_independence_rate", "재정자립도당초", "originalRate", "value")
        rate = final_rate or original_rate
        year = first(item, "year", "기준연도", "fiscalYear")
        basis = "재정자립도(최종)" if final_rate else "재정자립도(당초)"
        if sido and sigungu and rate:
            rows.append(
                {
                    "sido": sido,
                    "sigungu": sigungu,
                    "fiscal_independence_rate": rate,
                    "year": year or "",
                    "source_note": f"지방재정365/API 자동수집, 기준={basis}",
                }
            )
    return rows


def first(data: Dict[str, object], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [{field: str(row.get(field, "")).strip() for field in FIELDS} for row in csv.DictReader(file)]


def write_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()
