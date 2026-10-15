"""AIM preview only: serve this repo's page with the fake supabase client (mock.js) so the page shows sample data
without signing in. python preview.py [port]"""
import http.server, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)   # the repo root holds the page


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=SITE, **k)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/index.html"):
            with open(os.path.join(SITE, "index.html"), encoding="utf-8") as f:
                s = f.read()
            i = s.index('<script src="https://cdn.jsdelivr.net/npm/@supabase')
            j = s.index("</script>", i) + 9
            body = (s[:i] + '<script src="/_mock.js"></script>' + s[j:])
            body = body.replace('<script src="config.js"></script>', '<script>window.AIM_CONFIG = { supabaseUrl: "https://preview.local", supabaseKey: "sb_publishable_preview" };</script>').encode("utf-8")
        elif p == "/_mock.js":
            body = open(os.path.join(HERE, "mock.js"), "rb").read()
        elif p == "/sw.js":
            self.send_error(404); return
        else:
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if p != "/_mock.js" else "text/javascript")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
