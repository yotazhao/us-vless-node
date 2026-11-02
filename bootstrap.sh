#!/usr/bin/env bash
# 在 codespace 里把节点拉起来：bash bootstrap.sh <UUID> <WS_PATH>
set -euo pipefail
UUID="${1:?uuid}"
WSPATH="${2:?ws path}"
NODE_NAME="${3:-US-WestUs2}"

cd /workspaces/us-vless-node 2>/dev/null || cd "$HOME"
echo "workdir: $(pwd)"

if [ ! -x ./xray ]; then
  echo "fetching xray-core…"
  curl -fsSL --retry 3 -o /tmp/x.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
  unzip -oq /tmp/x.zip -d .
  chmod +x ./xray
fi
./xray version | head -2

export PORT=8080 INNER_PORT=18080 NO_TLS=0 EDGE_PORT=443
export UUID="$UUID" WS_PATH="$WSPATH" NODE_NAME="$NODE_NAME"
export XRAY_BIN="$(pwd)/xray"

pkill -f "python3 .*app.py" 2>/dev/null || true
sleep 1
nohup python3 app.py >/tmp/node.log 2>&1 &
for i in $(seq 1 20); do
  sleep 1
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then break; fi
done
echo "--- health ---"
curl -fsS http://127.0.0.1:8080/health || true
echo
echo "--- vless ---"
curl -fsS http://127.0.0.1:8080/vless || true
echo
echo "--- ws probe (want 400) ---"
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8080${WSPATH}" || true
echo "--- egress from this machine ---"
curl -fsS https://ipinfo.io/json || true
