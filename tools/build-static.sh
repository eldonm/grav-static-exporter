#!/usr/bin/env bash
# Build the static site for Cloudflare Pages:
#   Grav (Docker) -> controlled export -> Pagefind index -> Pagefind injection.
# Requires: docker, python3, node/npx. Output in ./output.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8092}"
OUT="${OUT:-output}"
IMG="em-static-build"

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
