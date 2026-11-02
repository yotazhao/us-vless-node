#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-port VLESS + WebSocket + TLS edge node.

Why single port: every PaaS (Render / Fly / Netrun / HF Spaces / Koyama) gives you
exactly one public port and terminates TLS at its own edge. So this process owns
$PORT and does two jobs:

  1. /health /sub /vless /qr.png  -> self-describing subscription, host derived
                                    from the request's Host header, so the vless://
                                    URI is always correct for whatever domain the
                                    platform handed you (no hardcoded domain).
  2. <WS_PATH>                    -> raw WebSocket upgrade bytes are tunneled
                                    verbatim to a local Xray VLESS inbound.

Env:
  UUID        fixed client id (default: random per boot -> set it or it changes)
  WS_PATH     websocket path  (default /ws-<8hex>)
  PORT        public port (default 8080)
  INNER_PORT  local xray ws port (default 18080)
  NODE_NAME   tag shown in Shadowrocket
  PUBLIC_HOST force the host used in the URI (default: request Host header)
  SNI         override TLS SNI (default: same as host)
  EDGE_PORT   port used in the URI (default 443, e.g. 2053 behind Cloudflare)
  NO_TLS=1    emit security=none (local testing only)
  XRAY_BIN    path to xray binary (default ./xray)
"""
import asyncio
import base64
import json
import os
import secrets
import subprocess
import sys
import uuid as uuidlib
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))

UUID = (os.environ.get("UUID") or "").strip() or str(uuidlib.uuid4())
_ws = (os.environ.get("WS_PATH") or "").strip()
WS_PATH = "/" + (_ws.lstrip("/") if _ws else "ws-" + secrets.token_hex(4))
PORT = int(os.environ.get("PORT", "8080"))
INNER_PORT = int(os.environ.get("INNER_PORT", "18080"))
XRAY_BIN = os.environ.get("XRAY_BIN") or os.path.join(HERE, "xray")
NODE_NAME = os.environ.get("NODE_NAME", "US-VLESS")
PUBLIC_HOST = (os.environ.get("PUBLIC_HOST") or "").strip()
FORCE_SNI = (os.environ.get("SNI") or "").strip()
EDGE_PORT = os.environ.get("EDGE_PORT", "443").strip()
NO_TLS = os.environ.get("NO_TLS", "0") == "1"
CONFIG_PATH = os.environ.get("XRAY_CONFIG") or os.path.join(HERE, "config.json")

XRAY_CONFIG = {
    "log": {"loglevel": "warning", "access": "none"},
    "inbounds": [
        {
            "tag": "vless-ws",
            "listen": "127.0.0.1",
            "port": INNER_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "flow": ""}],
                "decryption": "none",
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": WS_PATH, "headers": {}},
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
                "routeOnly": False,
            },
        }
    ],
    "outbounds": [
        {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}},
        {"protocol": "blackhole", "tag": "block"},
    ],
    "routing": {
        "domainStrategy": "AsIs",
        "rules": [
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
        ],
    },
}


def build_uri(host, scheme="https"):
    if not host:
        host = "node.example.com"
    sni = FORCE_SNI or host
    if NO_TLS:
        q = "encryption=none&security=none&type=ws&host={h}&path={p}".format(
            h=quote(host, safe=""), p=quote(WS_PATH, safe="")
        )
        return "vless://{u}@{h}:{port}?{q}#{n}".format(
            u=UUID, h=host, port=PORT, q=q, n=quote(NODE_NAME, safe="")
        )
    q = (
        "encryption=none&security=tls&sni={sni}&fp=chrome&alpn=http%2F1.1"
        "&type=ws&host={h}&path={p}"
    ).format(sni=quote(sni, safe=""), h=quote(host, safe=""), p=quote(WS_PATH, safe=""))
    return "vless://{u}@{h}:{port}?{q}#{n}".format(
        u=UUID, h=host, port=EDGE_PORT, q=q, n=quote(NODE_NAME, safe="")
    )


def build_clash(host):
    sni = FORCE_SNI or host
    return {
        "name": NODE_NAME,
        "type": "vless",
        "server": host,
        "port": PORT if NO_TLS else int(EDGE_PORT),
        "uuid": UUID,
        "tls": not NO_TLS,
        "servername": "" if NO_TLS else sni,
        "network": "ws",
        "udp": True,
        "ws-opts": {"path": WS_PATH, "headers": {"Host": host}},
    }


def qr_png(text):
    try:
        import io

        import segno  # pure python, no deps

        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="png", scale=8, border=3)
        data = buf.getvalue()
        if data:
            return data
    except Exception:
        pass
    import shutil
    import tempfile

    if shutil.which("qrencode"):
        tmp = os.path.join(tempfile.gettempdir(), "qr-%s.png" % secrets.token_hex(4))
        try:
            subprocess.run(
                ["qrencode", "-o", tmp, "-s", "8", "-m", "3", "-l", "M", text],
                check=True,
                timeout=10,
            )
            with open(tmp, "rb") as fh:
                return fh.read()
        except Exception:
            return None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return None


LANDING = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><style>
:root{{color-scheme:dark}}body{{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:#0b0f14;color:#e6edf3;margin:0;padding:28px}}
.card{{max-width:760px;margin:0 auto;background:#111823;border:1px solid #1f2a37;border-radius:14px;padding:22px}}
h1{{font-size:19px;margin:0 0 4px}}.muted{{color:#8b98a5;font-size:13px}}
.qr{{display:block;margin:18px auto;width:260px;height:260px;background:#fff;padding:10px;border-radius:10px}}
code{{display:block;word-break:break-all;background:#0b0f14;border:1px solid #1f2a37;border-radius:8px;
padding:12px;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:#9be6a4;margin:10px 0}}
.row{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 4px}}
a.btn{{background:#1f6feb;color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-size:13px}}
a.ghost{{background:#1f2a37}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
td{{padding:6px 0;border-bottom:1px solid #1a2330}}td:first-child{{color:#8b98a5;width:130px}}
</style></head><body><div class="card">
<h1>{name}</h1><div class="muted">VLESS + WebSocket + TLS · 单端口自描述节点</div>
<img class="qr" src="/qr.png" alt="Shadowrocket QR">
<div class="row"><a class="btn" href="/sub">subscription</a>
<a class="btn ghost" href="/vless">vless://</a>
<a class="btn ghost" href="/clash.yaml">mihomo</a>
<a class="btn ghost" href="/qr.png">qr.png</a></div>
<code>{uri}</code>
<table>
<tr><td>host</td><td>{host}</td></tr>
<tr><td>port</td><td>{port}</td></tr>
<tr><td>uuid</td><td>{uuid}</td></tr>
<tr><td>ws path</td><td>{path}</td></tr>
<tr><td>tls</td><td>{tls}</td></tr>
</table>
<div class="muted" style="margin-top:14px">Shadowrocket: 右上 + → 扫描二维码 / 从剪贴板导入；或订阅填入 /sub 链接。</div>
</div></body></html>"""


def host_of(headers, default):
    h = PUBLIC_HOST or headers.get("x-forwarded-host") or headers.get("host") or default
    return h.split(",")[0].strip().split(":")[0] if h else default


async def pipe(reader, writer):
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
        try:
            writer.write_eof()
        except Exception:
            pass
    except Exception:
        pass


async def tunnel(head, client_r, client_w):
    try:
        up_r, up_w = await asyncio.open_connection("127.0.0.1", INNER_PORT)
    except Exception:
        try:
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 6\r\n\r\nxray?\n")
            await client_w.drain()
        except Exception:
            pass
        return
    up_w.write(head)
    await up_w.drain()
    await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))
    for w in (up_w, client_w):
        try:
            w.close()
        except Exception:
            pass


def respond(writer, status, body, ctype="text/plain; charset=utf-8", extra=""):
    if isinstance(body, str):
        body = body.encode()
    head = (
        "HTTP/1.1 {s}\r\nContent-Type: {ct}\r\nContent-Length: {n}\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\nServer: nginx\r\n{ex}\r\n"
    ).format(s=status, ct=ctype, n=len(body), ex=extra)
    writer.write(head.encode() + body)


async def handle(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        return
    try:
        lines = head.decode("latin-1").split("\r\n")
        method, target = lines[0].split(" ")[0], lines[0].split(" ")[1]
    except Exception:
        writer.close()
        return
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    path = target.split("?")[0]
    host = host_of(headers, "127.0.0.1")

    if path == WS_PATH or path.rstrip("/") == WS_PATH.rstrip("/"):
        return await tunnel(head, reader, writer)

    try:
        if path in ("/health", "/healthz", "/ping"):
            respond(
                writer,
                200,
                json.dumps(
                    {"ok": True, "uuid": UUID, "path": WS_PATH, "host": host},
                    ensure_ascii=False,
                ),
                "application/json",
            )
        elif path in ("/vless", "/uri", "/link"):
            respond(writer, 200, build_uri(host) + "\n")
        elif path in ("/sub", "/sub.txt", "/subscribe", "/s"):
            uri = build_uri(host)
            b64 = base64.b64encode((uri + "\n").encode()).decode()
            respond(writer, 200, b64)
        elif path in ("/clash", "/clash.yaml", "/meta"):
            y = (
                "mixed-port: 7890\nallow-lan: true\nmode: rule\nlog-level: info\n"
                "proxies:\n  - "
                + json.dumps(build_clash(host), ensure_ascii=False)
                + '\nproxy-groups:\n  - name: PROXY\n    type: select\n    proxies: ["'
                + NODE_NAME
                + '"]\nrules:\n  - MATCH,PROXY\n'
            )
            respond(writer, 200, y, "text/yaml; charset=utf-8")
        elif path in ("/qr.png", "/qr", "/qrcode"):
            png = qr_png(build_uri(host))
            if png:
                respond(writer, 200, png, "image/png")
            else:
                respond(writer, 500, "qr generator missing (need segno or qrencode)\n")
        elif path in ("/", "/index.html"):
            respond(
                writer,
                200,
                LANDING.format(
                    name=NODE_NAME,
                    uri=build_uri(host),
                    host=host,
                    port=EDGE_PORT if not NO_TLS else PORT,
                    uuid=UUID,
                    path=WS_PATH,
                    tls="off" if NO_TLS else "on (edge)",
                ),
                "text/html; charset=utf-8",
            )
        else:
            respond(writer, 404, "not found\n")
    except Exception as exc:  # keep the port alive no matter what
        try:
            respond(writer, 500, "err: %s\n" % exc)
        except Exception:
            pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def start_xray():
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(XRAY_CONFIG, fh, indent=1)
    log = open(os.path.join(HERE, "xray.log"), "ab", buffering=0)
    proc = subprocess.Popen(
        [XRAY_BIN, "run", "-c", CONFIG_PATH],
        stdout=log,
        stderr=log,
        cwd=HERE,
    )
    print("[node] xray pid=%s bin=%s" % (proc.pid, XRAY_BIN), flush=True)
    return proc


async def main():
    proc = start_xray()
    await asyncio.sleep(1.2)
    if proc.poll() is not None:
        print("[node] xray died, see xray.log", flush=True)
        sys.exit(1)
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, backlog=512, reuse_address=True)
    print(
        "[node] listening :%d  ws-path=%s  uuid=%s  edge=%s"
        % (PORT, WS_PATH, UUID, "none" if NO_TLS else "tls/%s" % EDGE_PORT),
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
