"""
Dummy HTTP server — exists only so Render (or any host that expects a
Web Service to bind a port) sees an open port. The actual bot doesn't
need this; it's pure infra glue.
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", 10000))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running.")

    def log_message(self, format, *args):
        pass  # keep Render logs clean, no per-request spam


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[keepalive] Listening on port {PORT}")
    server.serve_forever()
