from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ZIP_URL = os.getenv(
    "POWERSITE_STABLE_ZIP_URL",
    "https://dat-ringtones-heath-shipments.trycloudflare.com/static/power_site_scout_stable_vercel_ready.zip",
)

EXCLUDE_DIRS = {".git", ".github", "__pycache__", "node_modules", ".vercel", "reports", "private_data", "backups"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".pid"}
EXCLUDE_NAMES = {".env"}


def should_skip(path: Path) -> bool:
    return path.name in EXCLUDE_NAMES or path.name in EXCLUDE_DIRS or path.suffix in EXCLUDE_SUFFIXES


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if should_skip(item):
            continue
        target = dst / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> None:
    cwd = Path.cwd().resolve()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        zip_path = tmp / "powersite-stable.zip"
        print(f"Downloading stable PowerSite package from {ZIP_URL}")
        urllib.request.urlretrieve(ZIP_URL, zip_path)
        if zip_path.stat().st_size <= 0:
            raise RuntimeError("Downloaded stable package is empty")

        extract_dir = tmp / "stable"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        package_root = extract_dir / "power_site_mvp"
        if not package_root.exists():
            raise RuntimeError("Stable package does not contain power_site_mvp/")

        if cwd.name == "power_site_mvp":
            copy_tree(package_root, cwd)
        else:
            copy_tree(extract_dir, cwd)

    print("Stable PowerSite package prepared for Vercel build")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PowerSite stable bootstrap failed: {exc}", file=sys.stderr)
        raise
