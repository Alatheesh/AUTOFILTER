print("WEB SERVER STARTED")

from http.server import BaseHTTPRequestHandler, HTTPServer
import os
print("WEB SERVER STARTED")
PORT = int(os.environ.get("PORT", 7860))

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is Running and Healthy!")
    
    def log_message(self, format, *args):
        pass # Disables spammy logs

if __name__ == "__main__":
    print(f"Starting independent web server on port {PORT}...")
    HTTPServer(('0.0.0.0', PORT), HealthCheckHandler).serve_forever()
  
