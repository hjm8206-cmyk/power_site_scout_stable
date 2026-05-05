from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_ZIP_URL = (
    "https://dat-ringtones-heath-shipments.trycloudflare.com/"
    "static/power_site_scout_stable_vercel_ready.zip?v=202605060401"
)

REQUIRED_ROOT_FILES = [
    "api/index.py",
    "power_site_mvp/app/main.py",
    "power_site_mvp/templates/index.html",
    "power_site_mvp/templates/login.html",
    "power_site_mvp/static/app.js",
    "power_site_mvp/static/style.css",
    "requirements.txt",
    "vercel.json",
]

REQUIRED_NESTED_FILES = [
    "api/index.py",
    "app/main.py",
    "templates/index.html",
    "templates/login.html",
    "static/app.js",
    "static/style.css",
    "requirements.txt",
    "vercel.json",
]


def safe_member_name(raw_name: str) -> Path | None:
    name = raw_name.replace("\\", "/").lstrip("/")
    if not name or name.endswith("/"):
        return None
    parts = [part for part in name.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return None
    return Path(*parts)


def download_zip(url: str, destination: Path) -> None:
    print(f"Downloading stable PowerSite package from {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "powersite-vercel-bootstrap"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    if destination.stat().st_size == 0:
        raise RuntimeError("Downloaded stable package is empty")


def extract_zip_normalized(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            relative_path = safe_member_name(member.filename)
            if relative_path is None:
                continue
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def copy_tree_contents(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def clean_generated_files(root: Path) -> None:
    for path in list(root.rglob("__pycache__")):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for pattern in ("*.pyc", "*.pyo", "*.log", "*.pid"):
        for path in root.rglob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)
    for relative in (
        "power_site_mvp/static/power_site_scout_stable_vercel_ready.zip",
        "static/power_site_scout_stable_vercel_ready.zip",
    ):
        (root / relative).unlink(missing_ok=True)


def validate_required_files(root: Path, nested: bool) -> None:
    required = REQUIRED_NESTED_FILES if nested else REQUIRED_ROOT_FILES
    missing = [path for path in required if not (root / path).exists()]
    if missing:
        raise RuntimeError("Stable package is missing required files: " + ", ".join(missing))


def main() -> None:
    cwd = Path.cwd().resolve()
    zip_url = os.environ.get("POWERSITE_STABLE_ZIP_URL", DEFAULT_ZIP_URL)

    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        zip_path = temp_dir / "powersite-stable.zip"
        extracted_dir = temp_dir / "stable"
        extracted_dir.mkdir(parents=True, exist_ok=True)

        download_zip(zip_url, zip_path)
        extract_zip_normalized(zip_path, extracted_dir)

        source_root = extracted_dir / "power_site_mvp"
        if not source_root.exists():
            raise RuntimeError("Stable package does not contain power_site_mvp/")

        if cwd.name == "power_site_mvp":
            copy_tree_contents(source_root, cwd)
            clean_generated_files(cwd)
            validate_required_files(cwd, nested=True)
        else:
            copy_tree_contents(extracted_dir, cwd)
            clean_generated_files(cwd)
            validate_required_files(cwd, nested=False)

    print("Stable PowerSite package prepared for Vercel build")


if __name__ == "__main__":
    main()
