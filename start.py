from http.server import HTTPServer, BaseHTTPRequestHandler
import os

PORT = int(os.environ.get("PORT", 7860))

print("PORT ENV =", os.environ.get("PORT"), flush=True)
print("USING PORT =", PORT, flush=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

server = HTTPServer(("0.0.0.0", PORT), Handler)

print("SERVER STARTED", flush=True)

server.serve_forever()
