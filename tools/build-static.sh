#!/usr/bin/env bash
# Build the static site for Cloudflare Pages:
#   Grav (Docker) -> controlled export -> Pagefind index -> Pagefind injection.
# Requires: docker, python3, node/npx. Output in ./output.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8092}"
OUT="${OUT:-output}"

# Per-site Docker image name so building multiple Grav sites locally doesn't
# clobber a shared image. Derived from the config's Pages project name, falling
# back to the repo directory; sanitized to a valid image tag. Override with IMG=.
CONFIG="${STATIC_EXPORT_CONFIG:-static-export.config.json}"
PROJECT="$(python3 -c "import json; print(json.load(open('$CONFIG'))['deploy']['cloudflare_pages_project'])" 2>/dev/null || true)"
[ -n "${PROJECT:-}" ] || PROJECT="$(basename "$PWD")"
SLUG="$(printf '%s' "$PROJECT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-' '-' | sed 's/^-*//; s/-*$//')"
IMG="${IMG:-grav-static-export-${SLUG:-site}}"

echo "==> Building Grav image"
docker build -t "$IMG" .

echo "==> Starting Grav container on 127.0.0.1:$PORT"
docker rm -f "${IMG}-run" >/dev/null 2>&1 || true
docker run -d --name "${IMG}-run" -p "127.0.0.1:${PORT}:80" "$IMG" >/dev/null
trap 'docker rm -f "${IMG}-run" >/dev/null 2>&1 || true' EXIT
for i in $(seq 1 40); do curl -sf -o /dev/null "http://127.0.0.1:${PORT}/" && break; sleep 1; done

echo "==> Controlled static export"
rm -rf "$OUT"
python3 tools/static_export.py "http://127.0.0.1:${PORT}" "./$OUT"

echo "==> Copying root files (robots.txt)"
[ -f robots.txt ] && cp robots.txt "$OUT/" || true

echo "==> Inject Pagefind UI + index-scope markers (must run BEFORE indexing)"
python3 tools/inject_pagefind.py "./$OUT"

echo "==> Pagefind index (respects data-pagefind-body scoping)"
npx -y pagefind --site "$OUT"

echo "==> Done. Static site in ./$OUT ($(find "$OUT" -type f | wc -l | tr -d ' ') files)"
