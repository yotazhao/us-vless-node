#!/bin/sh
set -eu

# Deterministic-but-secret defaults: if UUID / WS_PATH are not supplied by the
# platform, derive them from a persisted state file so a restart does not silently
# invalidate a client that is already configured.
STATE=/app/.state
if [ -z "${UUID:-}" ] || [ -z "${WS_PATH:-}" ]; then
  if [ -f "$STATE" ]; then
    # shellcheck disable=SC1090
    . "$STATE"
  else
    UUID=$(python3 -c 'import uuid;print(uuid.uuid4())')
    WS_PATH="/ws-$(python3 -c 'import secrets;print(secrets.token_hex(4))')"
    printf 'UUID=%s\nWS_PATH=%s\n' "$UUID" "$WS_PATH" >"$STATE"
  fi
  export UUID WS_PATH
fi

echo "[entrypoint] port=${PORT:-8080} node=${NODE_NAME:-US-VLESS} uuid=${UUID} path=${WS_PATH}"
exec python3 /app/app.py
