from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Dict, Iterable, List

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional parser
    pd = None

try:
    import requests
except Exception:  # pragma: no cover - optional during offline fallback
    requests = None


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw_policy_sources"
OUTPUT = RAW_DIR / "lagging_index.csv"
FALLBACK = RAW_DIR / "kdi_lagging_index_manual.csv"
FIELDS = ["sido", "sigungu", "lagging_index", "year", "source_note"]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env")
    rows = fetch_kdi_rows()
    if not rows:
        rows = read_rows(FALLBACK)
    write_rows(OUTPUT, rows)
    print(f"lagging_index rows={len(rows)} -> {OUTPUT}")


def fetch_kdi_rows() -> List[Dict[str, str]]:
    url = os.getenv("KDI_LAGGING_INDEX_URL", "").strip()
    if not url or requests is None:
        return []
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception:
        return []
    target = RAW_DIR / "kdi_lagging_index_download"
    target.write_bytes(response.content)
    if pd is None:
        return []
    try:
        if url.lower().endswith((".xlsx", ".xls")):
            frame = pd.read_excel(target)
        elif url.lower().endswith(".csv"):
            frame = pd.read_csv(target)
        else:
            return []
    except Exception:
        return []
    rows: List[Dict[str, str]] = []
    for _, item in frame.iterrows():
        data = {str(key): item[key] for key in frame.columns}
        sido = first(data, "sido", "시도")
        sigungu = first(data, "sigungu", "시군구")
        lagging = first(data, "lagging_index", "지역낙후도", "지역낙후도지수")
        year = first(data, "year", "기준연도")
        if sido and sigungu and lagging:
            rows.append(
                {
                    "sido": sido,
                    "sigungu": sigungu,
                    "lagging_index": lagging,
                    "year": year or "",
                    "source_note": "KDI 지역낙후도 자료 자동파싱",
                }
            )
    return rows


def first(data: Dict[str, object], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, "") and str(value) != "nan":
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
