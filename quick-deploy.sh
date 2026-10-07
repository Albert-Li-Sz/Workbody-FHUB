#!/usr/bin/env bash
# Workbody-FHUB: build this checkout, preserving accounts/ and usage/.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null
docker compose up -d --build workbody-fhub
printf '%s\n' 'Workbody-FHUB: http://127.0.0.1:8788/' \
  'First startup: docker compose logs workbody-fhub (bootstrap password and API key)' \
  'To update: update this checkout, then rerun ./quick-deploy.sh'
