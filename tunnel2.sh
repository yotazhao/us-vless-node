#!/bin/bash
# 备用公网入口：localhost.run（SSH 反向隧道，无需账号），失败则回落到 pinggy
set -u
echo "== trying localhost.run =="
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=20 \
    -R 80:localhost:8080 nokey@localhost.run 2>&1 | tee /tmp/lhr.log
