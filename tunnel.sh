#!/bin/bash
set -e
cd /tmp
if [ ! -x ./cloudflared ]; then
  curl -fsSL -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x cloudflared
fi
pkill -f "cloudflared tunnel" || true
sleep 1
nohup ./cloudflared tunnel --url http://127.0.0.1:8080 --no-autoupdate >/tmp/cf.log 2>&1 &
sleep 16
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log | head -1
tail -2 /tmp/cf.log
