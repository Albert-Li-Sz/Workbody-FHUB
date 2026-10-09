# Workbody-FHUB. Pin the official Python image; PYTHON_IMAGE can select another trusted source.
ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.11-alpine@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="Workbody-FHUB" \
      org.opencontainers.image.version="1.2.2" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.description="WorkBuddy, Cline, OpenCode and Command Code multi-account gateway" \
      org.opencontainers.image.source="https://github.com/Albert-Li-Sz/Workbody-FHUB"

# Set environment
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8788 TZ=Asia/Shanghai

WORKDIR /app

# Alpine timezone & certs
RUN apk add --no-cache tzdata ca-certificates &&     cp /usr/share/zoneinfo/${TZ} /etc/localtime &&     echo "${TZ}" > /etc/timezone

# Copy application files (Zero external pip dependencies needed)
COPY wb_*.py dashboard.html ./
COPY dashboard_static/ ./dashboard_static/
COPY README.md CHANGELOG.md CHANGELOG.upstream.md LICENSE LICENSE.upstream upstreams.json ./
COPY docs/ ./docs/

# Create data directories
RUN mkdir -p /app/accounts /app/usage

# Volume persistence for credentials and usage logs
VOLUME ["/app/accounts", "/app/usage"]

EXPOSE 8788

# Health probe for docker / orchestrators (M6 F3): /health always answers 200
# and only exposes account identity to an authorised caller. The URL follows
# PORT so a remapped container still reports healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8788'), timeout=3)" || exit 1

# Launch the proxy in the project's LAN mode: --lan listens on every interface
# and forces an api key (generated once, persisted in ./accounts/settings.json
# and printed in the startup log). Without it the container published port 8788
# to the network while key checking stayed off.
# No --port on purpose: the gateway already reads PORT from the environment
# (default 8788), and the exec form cannot expand a variable. Keeping the exec
# form leaves python as PID 1, so `docker stop` still delivers SIGTERM.
CMD ["python", "wb_proxy.py", "--host", "0.0.0.0", "--lan"]
