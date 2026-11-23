"""Run: python test_opener.py   (no API key or internet needed; uses a local test site and a fake model)"""
import os, threading, http.server, socketserver, tempfile
os.environ["ALLOW_PRIVATE"] = "1"
os.environ["CACHE_FILE"] = tempfile.mktemp()
import opener
opener.CACHE_FILE = os.environ["CACHE_FILE"]

PAGE = """<html><head><title>Acme Billing</title><meta name="description" content="Invoicing for small agencies"></head>
<body><nav>menu</nav><h1>Get paid faster without chasing clients</h1>
<p>Acme sends automatic payment reminders to your clients so agencies with under ten people stop chasing invoices by hand.</p>
<p>Our customers are design studios and small marketing teams who bill monthly retainers.</p><script>x=1</script></body></html>"""
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode() if self.path in ("/", "/about") else b"x"
        self.send_response(200 if self.path in ("/", "/about") else 404)
        self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{port}/"

good = lambda t, f="": {"hook_quote": "automatic payment reminders to your clients",
    "lines": ["Saw that Acme sends automatic payment reminders to your clients.",
              "I'd guess small agencies still lose days to late retainers.", "Is chasing invoices still a weekly pain for them?"],
    "insufficient": False}
r = opener.make_opener(url, llm=good); assert r["status"] == "ok", r
r2 = opener.make_opener(url, llm=lambda t, f="": 1/0); assert r2.get("cached"), r2   # served from cache, model not called

os.remove(opener.CACHE_FILE)
calls = []
def bad_then_good(t, f=""):
    calls.append(f)
    return {"hook_quote": "we invented the moon", "lines": ["a", "b", "c"], "insufficient": False} if not f else good(t)
r3 = opener.make_opener(url, llm=bad_then_good); assert r3["status"] == "ok" and len(calls) == 2, (r3, calls)

os.remove(opener.CACHE_FILE)
always_bad = lambda t, f="": {"hook_quote": "made up phrase here", "lines": ["a b", "c d", "e f"], "insufficient": False}
assert opener.make_opener(url, llm=always_bad)["status"] == "needs_human"

os.environ["ALLOW_PRIVATE"] = "0"
assert opener.make_opener("http://127.0.0.1:%d/" % port)["status"] == "fetch_failed"      # SSRF blocked
assert opener.make_opener("http://169.254.169.254/latest/meta-data")["status"] == "fetch_failed"
print("all tests passed")
