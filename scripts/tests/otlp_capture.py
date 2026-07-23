import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


output_path = sys.argv[1]
expected_requests = int(sys.argv[2]) if len(sys.argv) > 2 else 1
received = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        received.append(json.loads(self.rfile.read(length)))
        with open(output_path, "w", encoding="utf-8") as stream:
            json.dump(received, stream, ensure_ascii=False)
        self.send_response(200)
        self.end_headers()
        if len(received) >= expected_requests:
            self.server.done = True

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 14318), Handler)
server.timeout = 0.2
server.done = False
while not server.done:
    server.handle_request()
