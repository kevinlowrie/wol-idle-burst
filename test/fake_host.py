#!/usr/bin/env python3
"""Fake sleeping host for the end-to-end test.

Listens for a Wake-on-LAN magic packet on UDP. When a *valid* packet for --mac arrives it waits
--boot-delay seconds and then starts answering GET /health with 200 (the host "has booted").
With --already-up it serves /health immediately. Every event is appended to --events as JSON lines.
"""
import argparse
import http.server
import json
import socket
import threading
import time

p = argparse.ArgumentParser()
p.add_argument("--mac", required=True)
p.add_argument("--udp-port", type=int, default=40009)
p.add_argument("--health-port", type=int, default=48088)
p.add_argument("--boot-delay", type=float, default=3.0)
p.add_argument("--already-up", action="store_true")
p.add_argument("--no-boot", action="store_true", help="receive packets but never come up (timeout scenario)")
p.add_argument("--events", required=True)
p.add_argument("--lifetime", type=float, default=60.0)
a = p.parse_args()

mac = bytes.fromhex(a.mac.replace(":", "").replace("-", ""))
expected = b"\xff" * 6 + mac * 16
lock = threading.Lock()


def log(event, **kw):
    with lock, open(a.events, "a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "event": event, **kw}) + "\n")


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
        log("health-hit", path=self.path)

    def log_message(self, *_):
        pass


def serve_health():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.health_port), Health)
    log("host-up", port=a.health_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp.bind(("0.0.0.0", a.udp_port))
udp.settimeout(0.5)
log("listening", udp_port=a.udp_port)

if a.already_up:
    serve_health()

booted = a.already_up
deadline = time.time() + a.lifetime
while time.time() < deadline:
    try:
        data, src = udp.recvfrom(2048)
    except socket.timeout:
        continue
    ok = data == expected
    log("magic-packet" if ok else "bad-packet", valid=ok, length=len(data), src=src[0])
    if ok and not booted and not a.no_boot:
        booted = True
        threading.Timer(a.boot_delay, serve_health).start()
time.sleep(0.2)
