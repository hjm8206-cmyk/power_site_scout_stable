from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ZIP_URL = os.getenv(
    "POWERSITE_STABLE_ZIP_URL",
    "https://dat-ringtones-heath-shipments.trycloudflare.com/static/power_site_scout_stable_vercel_ready.zip",
)

EXCLUDE_DIRS = {".git", ".github", "__pycache__", "node_modules", ".vercel", "reports", "private_data", "backups"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".pid"}
EXCLUDE_NAMES = {".env"}


def should_skip_parts(parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDE_DIRS or part in EXCLUDE_NAMES for part in parts) or any(part.endswith(tuple(EXCLUDE_SUFFIXES)) for part in parts)


def safe_zip_path(name: str) -> PurePosixPath | None:
    normalized = name.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if should_skip_parts(path.parts):
        return None
    return path


def extract_zip_normalized(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            rel = safe_zip_path(info.filename)
            if rel is None:
                continue
            target = dest.joinpath(*rel.parts)
            if info.is_dir() or info.filename.endswith(("/", "\\")):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if item.name in EXCLUDE_NAMES or item.name in EXCLUDE_DIRS or item.suffix in EXCLUDE_SUFFIXES:
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
        extract_zip_normalized(zip_path, extract_dir)

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
