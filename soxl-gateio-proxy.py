#!/usr/bin/env python3
"""Local CORS proxy for soxl-usdt-dashboard.html.

Gate.io's REST API does not send CORS headers, so a browser page
cannot call it directly. This script runs on your own machine,
forwards GET requests to Gate.io server-to-server (not subject to
CORS), and adds the CORS header back before returning the response
to the browser. Only binds to 127.0.0.1, so nothing outside your
machine can reach it.

Run:
    python soxl-gateio-proxy.py
Then open soxl-usdt-dashboard.html and click "시작" - it talks to
http://127.0.0.1:8787/gateio/... by default.
"""
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://api.gateio.ws"
PREFIX = "/gateio"
HOST = "127.0.0.1"
PORT = 8787


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self.path.startswith(PREFIX + "/"):
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"use /gateio/<gate.io api path>"}')
            return

        upstream_url = UPSTREAM + self.path[len(PREFIX):]
        try:
            req = urllib.request.Request(upstream_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self._cors()
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:  # network errors, timeouts, etc.
            self.send_response(502)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def log_message(self, fmt, *args):
        print("[proxy]", fmt % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Gate.io CORS proxy running at http://{HOST}:{PORT}{PREFIX}/... (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
