from http.server import BaseHTTPRequestHandler, HTTPServer
import os

PORT = int(os.environ.get("PORT", 7860))

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
server.serve_forever()
