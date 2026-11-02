#!/bin/bash
set -e
cd /tmp
if [ ! -x ./cloudflared ]; then
  curl -fsSL -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x cloudflared
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2
: >/tmp/cf2.log
nohup ./cloudflared tunnel --url http://127.0.0.1:8080 --no-autoupdate --protocol http2 --edge-ip-version 4 >/tmp/cf2.log 2>&1 &
for i in $(seq 1 30); do
  sleep 2
  grep -q 'Registered tunnel connection' /tmp/cf2.log && break
done
echo "registered: $(grep -c 'Registered tunnel connection' /tmp/cf2.log)"
echo "url: $(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf2.log | head -1)"
tail -4 /tmp/cf2.log
