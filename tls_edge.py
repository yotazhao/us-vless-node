#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal TLS edge emulator: terminates TLS (ALPN h1 only, like a WS-capable edge)
and pipes raw bytes to the node on 127.0.0.1:LOCAL_PORT. Used to prove the deploy
works when TLS is terminated upstream (Render / Fly / Caddy / Cloudflare)."""
import asyncio
import hashlib
import os
import ssl
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, "edge-cert.pem")
KEY = os.path.join(HERE, "edge-key.pem")
LISTEN = int(os.environ.get("EDGE_LISTEN", "8443"))
LOCAL_PORT = int(os.environ.get("EDGE_LOCAL", "18080"))


def gen_cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import datetime

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.DNSName("*.onrender.com"),
            x509.DNSName("*.fly.dev"),
            x509.DNSName("*.hf.space"),
            x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    with open(CERT, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEY, "wb") as fh:
        fh.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    der = cert.public_bytes(serialization.Encoding.DER)
    print("cert written; sha256 pin =", hashlib.sha256(der).hexdigest())
    return hashlib.sha256(der).hexdigest()


async def pipe(r, w):
    try:
        while True:
            b = await r.read(65536)
            if not b:
                break
            w.write(b)
            await w.drain()
        try:
            w.write_eof()
        except Exception:
            pass
    except Exception:
        pass


async def handle(cr, cw):
    try:
        ur, uw = await asyncio.open_connection("127.0.0.1", LOCAL_PORT)
    except Exception:
        cw.close()
        return
    await asyncio.gather(pipe(cr, uw), pipe(ur, cw))
    for w in (uw, cw):
        try:
            w.close()
        except Exception:
            pass


async def main():
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        gen_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    ctx.set_alpn_protocols(["http/1.1"])  # WS needs HTTP/1.1
    srv = await asyncio.start_server(handle, "0.0.0.0", LISTEN, ssl=ctx)
    print("TLS edge on :%d -> 127.0.0.1:%d (alpn h1)" % (LISTEN, LOCAL_PORT), flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
