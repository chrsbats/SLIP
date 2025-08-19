import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import pytest
from slip import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected

@pytest.fixture(scope="module")
def http_server():
    store = {"data": ""}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence test logs
            return
        def do_GET(self):
            if self.path == "/ping":
                body = "pong"
            else:
                key = self.path.lstrip("/")
                body = store.get(key, "")
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_PUT(self):
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length).decode("utf-8") if length else ""
            key = self.path.lstrip("/")
            store[key] = data
            b = data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_DELETE(self):
            key = self.path.lstrip("/")
            store.pop(key, None)
            body = "deleted".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=2)

@pytest.fixture(scope="module")
def http_json_server():
    store = {"data": "{}"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return
        def do_GET(self):
            key = self.path.lstrip("/")
            body = store.get(key, "{}")
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_PUT(self):
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length).decode("utf-8") if length else "{}"
            key = self.path.lstrip("/")
            store[key] = data
            b = data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=2)

@pytest.fixture(scope="module")
def http_json_server_rw():
    store = {"data": "{}", "_last_headers": {}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return
        def _capture_headers(self):
            # Save request headers for assertions
            store["_last_headers"] = {k: v for k, v in self.headers.items()}
        def do_GET(self):
            key = self.path.lstrip("/")
            body = store.get(key, "{}")
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_PUT(self):
            self._capture_headers()
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length).decode("utf-8") if length else "{}"
            key = self.path.lstrip("/")
            store[key] = data
            b = data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_POST(self):
            self._capture_headers()
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length).decode("utf-8") if length else "{}"
            key = self.path.lstrip("/")
            # For demo, append or overwrite; we just echo back the posted body
            store[key] = data
            b = data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_DELETE(self):
            key = self.path.lstrip("/")
            store.pop(key, None)
            b = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield (f"http://{host}:{port}", store)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=2)

@pytest.mark.asyncio
async def test_http_get_returns_body(http_server):
    url = f"{http_server}/ping"
    src = f"{url}"
    res = await run_slip(src)
    assert_ok(res, "pong")

@pytest.mark.asyncio
async def test_http_put_then_get_roundtrip(http_server):
    url = f"{http_server}/data"
    src = f"""
    {url}: "hello"
    {url}
    """
    res = await run_slip(src)
    assert_ok(res, "hello")

@pytest.mark.asyncio
async def test_http_delete_then_get_empty(http_server):
    url = f"{http_server}/data"
    src = f"""
    {url}: "temp"
    ~{url}
    {url}
    """
    res = await run_slip(src)
    assert_ok(res, "")  # server returns empty after delete

@pytest.mark.asyncio
async def test_multi_set_destructuring_binds_http_urls(http_server):
    u1 = f"{http_server}/a"
    u2 = f"{http_server}/b"
    src = f"""
    [{u1}, {u2}]: #['X', 'Y']
    #[ {u1}, {u2} ]
    """
    res = await run_slip(src)
    assert_ok(res, ["X", "Y"])

@pytest.mark.asyncio
async def test_http_put_json_then_get_and_access_field(http_json_server):
    url = f"{http_json_server}/data"
    src = f"""
    {url}: '{{"field": 123, "msg": "hi"}}'
    x: {url}
    x.field
    """
    res = await run_slip(src)
    assert_ok(res, 123)

@pytest.mark.asyncio
async def test_resource_put_and_get_with_content_type_json(http_json_server_rw):
    base, store = http_json_server_rw
    url = f"{base}/data"
    src = f"""
    admin-api: resource `{url}#(content-type: "application/json")`
    put admin-api #{{ a: 1, b: "x" }}
    x: get admin-api
    x.a
    """
    res = await run_slip(src)
    assert_ok(res, 1)
    # Server stored JSON; verify by parsing stored body
    import json
    assert json.loads(store["data"]) == {"a": 1, "b": "x"}
    # Header was promoted from meta
    assert store["_last_headers"].get("Content-Type", "").startswith("application/json")

@pytest.mark.asyncio
async def test_post_path_literal_with_content_type_json(http_json_server_rw):
    base, store = http_json_server_rw
    url = f"{base}/data"
    src = f"""
    {url}#(content-type: "application/json")<- #{{ name: "three" }}
    """
    res = await run_slip(src)
    assert_ok(res, {"name": "three"})
    assert store["_last_headers"].get("Content-Type", "").startswith("application/json")

@pytest.mark.asyncio
async def test_post_prefix_and_piped_with_resource(http_json_server_rw):
    base, store = http_json_server_rw
    url = f"{base}/data"
    src = f"""
    admin-api: resource `{url}#(content-type: "application/json")`
    r1: post admin-api #{{ name: "one" }}
    r2: admin-api |post #{{ name: "two" }}
    #[ r1.name, r2.name ]
    """
    res = await run_slip(src)
    assert_ok(res, ["one", "two"])
    # Ensure correct header applied for POST as well
    assert store["_last_headers"].get("Content-Type", "").startswith("application/json")

@pytest.mark.asyncio
async def test_del_resource_then_get_returns_empty_json(http_json_server_rw):
    base, store = http_json_server_rw
    url = f"{base}/data"
    src = f"""
    admin-api: resource `{url}#(content-type: "application/json")`
    put admin-api #{{ a: 1 }}
    del admin-api
    get admin-api
    """
    res = await run_slip(src)
    assert_ok(res, {})  # server’s DELETE returns empty JSON
    # Last headers captured were from the DELETE (JSON content-type)
    assert store["_last_headers"].get("Content-Type", "").startswith("application/json")
