#!/usr/bin/env bash
set -euo pipefail

ZIP_URL="${POWERSITE_STABLE_ZIP_URL:-https://dat-ringtones-heath-shipments.trycloudflare.com/static/power_site_scout_stable_vercel_ready.zip}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v unzip >/dev/null 2>&1 || { echo "unzip is required" >&2; exit 1; }

echo "Downloading stable PowerSite package from ${ZIP_URL}"
curl -fL "${ZIP_URL}" -o "${TMP_DIR}/powersite-stable.zip"
test -s "${TMP_DIR}/powersite-stable.zip"

mkdir -p "${TMP_DIR}/stable"
unzip -q "${TMP_DIR}/powersite-stable.zip" -d "${TMP_DIR}/stable"

test -d "${TMP_DIR}/stable/power_site_mvp"

if [ "$(basename "$PWD")" = "power_site_mvp" ]; then
  cp -R "${TMP_DIR}/stable/power_site_mvp/." .
else
  cp -R "${TMP_DIR}/stable/." .
fi

find . -type d -name __pycache__ -prune -exec rm -rf {} + || true
find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name '*.pid' \) -delete || true
rm -f power_site_mvp/static/power_site_scout_stable_vercel_ready.zip static/power_site_scout_stable_vercel_ready.zip || true

echo "Stable PowerSite package prepared for Vercel build"
