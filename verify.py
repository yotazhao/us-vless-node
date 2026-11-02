#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Two-stage verification + client artifact generation (works locally and against a
real deployed node).

Stage 1  HTTP probe:  GET <scheme>://<host>:<port><ws-path>
         Xray answers a plain HTTP GET on the WS path with 400 Bad Request
         (it carries sec-websocket-version expectations). 400/426 = alive.

Stage 2  Real client test: start a temporary Xray client with a SOCKS5 inbound,
         curl https://ipinfo.io/json through it, print exit IP / city / country.

Stage 3  Emit: vless:// URI, base64 subscription, qr.png, clash.yaml

Examples
  python verify.py --host 127.0.0.1 --port 8080 --no-tls \
      --uuid 1111... --path /ws-abcd1234
  python verify.py --host us-vless.onrender.com --uuid ... --path /ws-abcd1234
"""
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))


def find_xray():
    for c in (
        os.environ.get("XRAY_BIN"),
        os.path.join(HERE, "bin", "xray", "xray.exe"),
        os.path.join(HERE, "bin", "xray", "xray"),
        shutil.which("xray"),
        "/usr/local/bin/xray",
        "/usr/bin/xray",
    ):
        if c and os.path.exists(c):
            return c
    sys.exit("xray binary not found — put it in bin/xray/ or set XRAY_BIN")


def probe(host, port, path, tls):
    import ssl

    try:
        raw = socket.create_connection((host, port), timeout=15)
    except Exception as exc:
        return "CONNECT-FAIL %s" % exc
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            raw = ctx.wrap_socket(raw, server_hostname=host)
        except Exception as exc:
            return "TLS-FAIL %s" % exc
    req = "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n" % (
        path,
        host,
    )
    raw.sendall(req.encode())
    buf = b""
    try:
        while len(buf) < 4096:
            chunk = raw.recv(4096)
            if not chunk:
                break
            buf += chunk
    except Exception:
        pass
    raw.close()
    head = buf.decode("latin-1", "replace").split("\r\n")[0]
    return head or "EMPTY"


def client_config(host, port, path, uuid, tls, sni, socks_port, insecure=False):
    return {
        "log": {"loglevel": "warning", "access": "none"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {"address": host, "port": port, "users": [{"id": uuid, "encryption": "none"}]}
                    ]
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "tls" if tls else "none",
                    "tlsSettings": {
                        "serverName": sni or host,
                        "allowInsecure": bool(insecure),
                        "alpn": ["http/1.1"],
                    },
                    "wsSettings": {"path": path, "headers": {"Host": sni or host}},
                },
            }
        ],
    }


def curl_socks(url, socks_port):
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        return "curl missing"
    try:
        out = subprocess.run(
            [exe, "-sS", "--max-time", "25", "--socks5-hostname", "127.0.0.1:%d" % socks_port, url],
            capture_output=True,
            text=True,
            timeout=40,
        )
        return (out.stdout or out.stderr).strip()[:1200]
    except Exception as exc:
        return "curl-fail %s" % exc


def wait_port(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--uuid", required=True)
    ap.add_argument("--path", required=True)
    ap.add_argument("--sni", default="")
    ap.add_argument("--no-tls", action="store_true")
    ap.add_argument("--name", default="US-VLESS")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--skip-client", action="store_true")
    ap.add_argument("--insecure", action="store_true")
    a = ap.parse_args()

    path = "/" + a.path.lstrip("/")
    os.makedirs(a.out, exist_ok=True)
    print("== stage 1: HTTP probe ==")
    print("GET %s://%s:%d%s -> %s" % ("http" if a.no_tls else "https", a.host, a.port, path,
          probe(a.host, a.port, path, not a.no_tls)))

    q = "encryption=none&security={sec}&type=ws&host={h}&path={p}".format(
        sec="none" if a.no_tls else "tls", h=a.host, p=quote(path, safe="")
    )
    if not a.no_tls:
        q += "&sni={s}&fp=chrome&alpn=http%2F1.1".format(s=a.sni or a.host)
    uri = "vless://{u}@{h}:{p}?{q}#{n}".format(
        u=a.uuid, h=a.host, p=a.port, q=q, n=quote(a.name, safe="")
    )

    if not a.skip_client:
        print("== stage 2: real client through node ==")
        cfg = client_config(a.host, a.port, path, a.uuid, not a.no_tls, a.sni, 10899, a.insecure)
        cfgp = os.path.join(a.out, "xray-client.json")
        with open(cfgp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=1)
        proc = subprocess.Popen(
            [find_xray(), "run", "-c", cfgp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            if not wait_port(10899):
                print("socks inbound did not come up")
            else:
                info = curl_socks("https://ipinfo.io/json", 10899)
                print("ipinfo.io/json through node:\n%s" % info)
                print("--- google 204 ---")
                print(curl_socks("https://www.google.com/generate_204", 10899) or "(empty 204 = ok)")
        finally:
            proc.terminate()

    print("== stage 3: client artifacts ==")
    with open(os.path.join(a.out, "vless.txt"), "w", encoding="utf-8") as fh:
        fh.write(uri + "\n")
    with open(os.path.join(a.out, "sub.txt"), "w", encoding="utf-8") as fh:
        fh.write(base64.b64encode((uri + "\n").encode()).decode())
    try:
        import segno

        segno.make(uri, error="m").save(os.path.join(a.out, "qr.png"), scale=8, border=3)
        print("qr.png written")
    except Exception as exc:
        print("qr skip: %s" % exc)
    print("\nURI:\n%s" % uri)


if __name__ == "__main__":
    main()
