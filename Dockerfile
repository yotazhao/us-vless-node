# Single-port VLESS + WebSocket node for any PaaS (edge TLS terminates upstream)
FROM python:3.12-alpine

# qrencode = PNG QR fallback (segno, pure python, is the primary path)
RUN apk add --no-cache ca-certificates curl unzip qrencode tzdata \
    && pip install --no-cache-dir segno

ARG TARGETARCH=amd64
ARG XRAY_VERSION=latest

WORKDIR /app
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) pkg="Xray-linux-64.zip" ;; \
      arm64) pkg="Xray-linux-arm64-v8a.zip" ;; \
      *) echo "unsupported arch ${TARGETARCH}" && exit 1 ;; \
    esac; \
    if [ "${XRAY_VERSION}" = "latest" ]; then \
      url="https://github.com/XTLS/Xray-core/releases/latest/download/${pkg}"; \
    else \
      url="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/${pkg}"; \
    fi; \
    echo "fetching ${url}"; \
    curl -fsSL --retry 5 --retry-delay 2 -o /tmp/xray.zip "${url}"; \
    unzip -q /tmp/xray.zip -d /app; \
    rm -f /tmp/xray.zip; \
    chmod +x /app/xray; \
    /app/xray version

COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PORT=8080 \
    INNER_PORT=18080 \
    NODE_NAME=US-VLESS \
    UUID="" \
    WS_PATH=""

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8080'),timeout=4)" || exit 1

CMD ["/app/entrypoint.sh"]
