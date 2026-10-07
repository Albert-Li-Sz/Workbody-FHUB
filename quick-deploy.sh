#!/usr/bin/env bash
# Workbody-FHUB: deploy the published image, preserving accounts/ and usage/.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null
docker compose pull workbody-fhub
docker compose up -d workbody-fhub
printf '%s\n' 'Workbody-FHUB: listening on 0.0.0.0:8788' \
  'Dashboard: http://<server-ip>:8788/' \
  'First startup: docker compose logs workbody-fhub (bootstrap password and API key)' \
  'To update: set WORKBODY_IMAGE to the desired release, then rerun ./quick-deploy.sh'
