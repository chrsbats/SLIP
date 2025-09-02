import pytest
from slip import ScriptRunner
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected, f"expected {expected!r}, got {res.value!r}"


def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


@pytest.fixture(scope="module")
def http_server_rw():
    store = {"data": {"initial": True}, "log": [], "_last_headers": {}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return
        def _capture_headers(self):
            store["_last_headers"] = {k.lower(): v for k, v in self.headers.items()}
        def _read_body(self):
            cl = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(cl) if cl > 0 else b""
        def do_GET(self):
            self._capture_headers()
            store["log"].append("GET")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(store["data"]).encode("utf-8"))
        def do_PUT(self):
            self._capture_headers()
            body = self._read_body()
            store["log"].append(("PUT", body.decode('utf-8')))
            try:
                store["data"] = json.loads(body)
            except Exception:
                store["data"] = body.decode('utf-8')
            self.send_response(200)
            self.end_headers()
        def do_POST(self):
            self._capture_headers()
            body = self._read_body()
            store["log"].append(("POST", body.decode('utf-8')))
            try:
                parsed_body = json.loads(body)
                store["data"].update(parsed_body)
            except Exception:
                pass
            self.send_response(200)
            self.end_headers()
        def do_DELETE(self):
            self._capture_headers()
            store["log"].append("DELETE")
            store["data"] = {}
            self.send_response(204)
            self.end_headers()

    server = HTTPServer(('localhost', 8999), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield "http://localhost:8999", store
    server.shutdown()
    thread.join(timeout=1)


@pytest.mark.asyncio
async def test_string_and_path_utilities_join_split_replace_indent():
    runner = ScriptRunner()
    src = """
xs: #['x', 'y', 'z']
joined: join xs ', '
parts: split 'a,b,c' ','
repl: replace 'foo bar foo' 'foo' 'baz'
ind: indent 'a\nb' '>> '
#[ joined, parts, repl, ind ]
"""
    res = await runner.handle_script(src)
    assert_ok(res, ["x, y, z", ["a", "b", "c"], "baz bar baz", ">> a\n>> b"])


@pytest.mark.asyncio
async def test_type_of_primitives_and_paths_and_functions():
    runner = ScriptRunner()
    src = """
s: scope #{}
f: fn {x} [ x ]
#[
  eq (type-of 3) `int`,
  eq (type-of -2.5) `float`,
  eq (type-of 'r') `string`,
  eq (type-of "i") `i-string`,
  eq (type-of #[]) `list`,
  eq (type-of #{}) `dict`,
  eq (type-of s) `scope`,
  eq (type-of f) `function`,
  eq (type-of `a.b`) `path`,
  eq (type-of none) `none`
]
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    assert all(res.value), f"type-of checks failed: {res.value!r}"


@pytest.mark.asyncio
async def test_call_invokes_function_with_list_args():
    runner = ScriptRunner()
    res = await runner.handle_script("call add #[1, 2]")
    assert_ok(res, 3)


@pytest.mark.asyncio
async def test_collection_utilities_len_range_keys_values_copy_clone():
    runner = ScriptRunner()
    src = """
d: #{ a: 1, b: 2 }
s: scope #{ x: 10, y: 20 }
r1: len #[1, 2, 3]
r2: range 3
r3: range 1 4
r4: range 1 5 2
k-d: sort (keys d)
v-d: sort (values d)
k-s: sort (keys s)
v-s: sort (values s)
orig: #{ nested: #[1, #{ z: 9 }] }
shallow: copy orig
deep: clone orig
orig.nested[1].z: 99
#[ r1, r2, r3, r4, k-d, v-d, k-s, v-s, shallow.nested[1].z, deep.nested[1].z ]
"""
    res = await runner.handle_script(src)
    assert_ok(
        res,
        [
            3,
            [0, 1, 2],
            [1, 2, 3],
            [1, 3],
            ["a", "b"],
            [1, 2],
            ["x", "y"],
            [10, 20],
            99,
            9,
        ],
    )


@pytest.mark.asyncio
async def test_math_pow_and_not_operators():
    runner = ScriptRunner()
    src = """
#[ 2 ** 3, not true, not false ]
"""
    res = await runner.handle_script(src)
    assert_ok(res, [8, False, True])


@pytest.mark.asyncio
async def test_import_and_channels_and_current_scope_missing_errors_cleanly():
    runner = ScriptRunner()

    # import missing
    res = await runner.handle_script("import `a.b`")
    assert_error(res, "PathNotFound: import")

    # channels present and functional
    res = await runner.handle_script("""
    ch: make-channel
    task [ send ch 42 ]
    receive ch
    """)
    assert_ok(res, 42)

    # current-scope present: returns a scope
    res = await runner.handle_script("is-scope? current-scope")
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_join_path_variant_concatenates_paths_now():
    runner = ScriptRunner()
    res = await runner.handle_script("eq (join `a` `b`) `a.b`")
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_resource_fluent_api(http_server_rw):
    url, store = http_server_rw
    runner = ScriptRunner()

    src = f"""
    -- Create a configured resource handle for a JSON API
    api: resource `{url}/items#(content-type: "application/json", timeout: 1)`

    -- GET initial data
    initial: get api

    -- PUT new data
    put api #{{ name: "new-item", value: 42 }}

    -- POST to update/merge
    post api #{{ extra: true }}

    -- GET again to see combined result
    final_get: get api

    -- DELETE data
    del api

    -- Return all results for inspection
    #{{
        initial: initial,
        final_get: final_get
    }}
    """

    res = await runner.handle_script(src)
    assert_ok(res)

    assert res.value['initial'] == {'initial': True}
    assert res.value['final_get'] == {'name': 'new-item', 'value': 42, 'extra': True}

    assert store['log'] == [
        'GET',
        ('PUT', '{\n  "name": "new-item",\n  "value": 42\n}'),
        ('POST', '{\n  "extra": true\n}'),
        'GET',
        'DELETE'
    ]
