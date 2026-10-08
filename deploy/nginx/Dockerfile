ARG NGINX_IMAGE=public.ecr.aws/docker/library/nginx:1.28-alpine
FROM ${NGINX_IMAGE}

LABEL org.opencontainers.image.title="Workbody-FHUB Nginx" \
      org.opencontainers.image.version="1.1.3" \
      org.opencontainers.image.source="https://github.com/Albert-Li-Sz/Workbody-FHUB" \
      org.opencontainers.image.description="Nginx frontend with automatic IP/domain ACME renewal"

RUN apk add --no-cache python3 py3-pip openssl ca-certificates \
    && python3 -m venv /opt/acme \
    && /opt/acme/bin/pip install --no-cache-dir certbot==5.8.0

COPY deploy/nginx/gateway.py /opt/workbody/gateway.py
ENV PATH="/opt/acme/bin:${PATH}" \
    WB_TLS_MODE=auto WB_ACME_CHECK_SECONDS=21600 \
    WB_ACME_RETRY_SECONDS=1800 WB_NGINX_UPSTREAM=workbody-fhub:8788

VOLUME ["/etc/letsencrypt", "/var/lib/letsencrypt"]
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/nginx-health',timeout=3)" || exit 1
ENTRYPOINT ["python3", "/opt/workbody/gateway.py"]
