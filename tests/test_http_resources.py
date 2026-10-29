import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import toml
import xmltodict
from safer_yaml import loads

from slip import ScriptRunner
from slip.slip_core import Path as SlipPath, PathLiteral


def test_http_get_queries_are_live_and_do_not_request_during_binding():
    calls = []
    players = [{"hp": 10, "name": "A"}, {"hp": 90, "name": "B"}]

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=players)

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            loaded = runner.handle_script("""
                names: fn {limit} [https://api/players[.hp < limit].name]
            """)
            assert loaded.status == "ok", loaded.error_message
            assert calls == []
            result = runner.handle_script("names 50")
            assert result.status == "ok", result.error_message
            assert result.value == ["A"] and len(calls) == 1
            players[0] = {"hp": 80, "name": "C"}
            result = runner.handle_script("names 100")
            assert result.status == "ok", result.error_message
            assert result.value == ["C", "B"] and len(calls) == 2
        assert not client.is_closed


def test_http_verbs_handles_and_direct_forms():
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"method": request.method})

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                mime: 'application/json'
                api: resource `https://api/items#(content-type: mime)`
                a: put api #{name: 'one'}
                b: api |post #{name: 'two'}
                c: https://api/direct<- 'three'
                d: https://api/direct: 'four'
                e: del api
                f: ~https://api/direct
                #[a.method, b.method, c.method, d, e.method, f.method]
            """)
            assert result.status == "ok", result.error_message
            assert result.value == [
                "PUT", "POST", "POST", "four", "DELETE", "DELETE",
            ]
            assert [method for method, _, _ in calls] == [
                "PUT", "POST", "POST", "PUT", "DELETE", "DELETE",
            ]
            assert json.loads(calls[0][2]) == {"name": "one"}
            assert json.loads(calls[1][2]) == {"name": "two"}
            assert calls[2][2] == b"three" and calls[3][2] == b"four"


@pytest.mark.parametrize("mode", [None, "`full`", "'FULL'"])
def test_http_status_failure_and_explicit_full_envelope(mode):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(404, json={"message": "missing"},
                              headers={"X-Test": "one"})

    options = "" if mode is None else f"#(response-mode: {mode})"
    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(
                f"https://api/missing{options}",
            )
            if mode is None:
                assert result.status == "err"
                assert result.error["kind"] == PathLiteral(
                    SlipPath(["protocol"]),
                )
                assert result.error["protocol-status"] == 404
                assert result.error["data"] == {"message": "missing"}
                assert result.error["meta"]["headers"]["x-test"] == "one"
                assert "HTTP 404" in result.error_message
            else:
                assert result.status == "ok", result.error_message
                assert result.value["status"] == 404
                assert result.value["value"] == {"message": "missing"}
                assert result.value["meta"]["headers"]["x-test"] == "one"
            assert len(calls) == 1


def test_http_protocol_failure_is_captured_by_do_with_effects():
    def respond(request):
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                out: do [emit 'audit' 'before'; https://api/down]
                #[out.status = err, out.error.code = `http-error`,
                  out.error.protocol = `http`, out.error.protocol-status,
                  out.error.data, out.effects]
            """)
            assert result.status == "ok", result.error_message
            assert result.value == [True, True, True, 503, "unavailable", [
                {"topics": ["audit"], "message": "before"},
            ]]


def test_failure_kinds_use_the_references_language_tokens():
    def respond(request):
        return httpx.Response(404, text="missing")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                protocol-result: do [https://api/missing]
                domain-result: do [fail 'invalid']
                runtime-result: do [missing-name]
                #[protocol-result.error.kind = `protocol`,
                  domain-result.error.kind = `domain`,
                  runtime-result.error.kind = `runtime`]
            """)
            assert result.status == "ok", result.error_message
            assert result.value == [True, True, True]


@pytest.mark.parametrize("options", [
    "response-mode: `lite`", "response-mode: 'none'",
    "response-mode: 'unknown'", "full: true", "lite: false",
])
def test_invalid_response_modes_fail_before_http_request(options):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="unexpected")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(
                f"https://api/items#({options})",
            )
            assert result.status == "err"
            assert "full" in result.error_message
            assert calls == []


@pytest.mark.parametrize(("content_type", "body", "expected"), [
    ("application/json", b'{"ok": true}', {"ok": True}),
    ("application/yaml", b"name: on\nenabled: false\n",
     {"name": "on", "enabled": False}),
    ("application/toml", b'name = "on"\nenabled = false\n',
     {"name": "on", "enabled": False}),
    ("application/xml", b"<root><name>Karl</name></root>",
     {"root": {"name": "Karl"}}),
    ("text/html", b"<html><head><title>t</title></head>"
     b"<body><p>Hello</p></body></html>",
     {"html": {"head": {"title": "t"}, "body": {"p": "Hello"}}}),
    ("application/x-yaml; charset=utf-8", b"a: 1\n", {"a": 1}),
    ("text/plain; charset=iso-8859-1", b"caf\xe9", "café"),
    ("text/plain", b'{"sniffed": 7}', {"sniffed": 7}),
    ("text/plain", b"<xml/>", {"xml": None}),
    ("application/json", b"{name: on}", {"name": "on"}),
    ("application/json", b"{", "{"),
    ("application/toml", b"[", "["),
])
def test_http_reference_decoding_policy(content_type, body, expected):
    def respond(request):
        return httpx.Response(200, content=body,
                              headers={"Content-Type": content_type})

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("https://api/data")
            assert result.status == "ok", result.error_message
            assert result.value == expected


@pytest.mark.parametrize(("content_type", "decode"), [
    ("application/json", json.loads), ("application/yaml", loads),
    ("application/toml", toml.loads), ("application/xml", xmltodict.parse),
])
def test_http_payload_headers_params_and_timeout(content_type, decode):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, text="accepted")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(f"""
                data: #{{root: #{{name: "Karl"}}}}
                https://api/items#(content-type: '{content_type}';
                    headers: #{{'X-Test': 'one'}};
                    params: #{{page: 2}}; timeout: 1.5)<- data
            """)
            assert result.status == "ok", result.error_message
            request, = captured
            assert request.headers["content-type"] == content_type
            assert request.headers["x-test"] == "one"
            assert request.url.params["page"] == "2"
            assert request.extensions["timeout"]["read"] == 1.5
            assert decode(request.content.decode()) == {
                "root": {"name": "Karl"},
            }


def test_http_xml_list_wrapping_and_default_text_content_type():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="accepted")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                mime: 'application/xml'
                https://api/list#(content-type: mime)<- #['A', 'B']
                https://api/text: 'hello'
            """)
            assert result.status == "ok", result.error_message
    xml, text = requests
    assert xml.method == "POST"
    assert xmltodict.parse(xml.content) == {"root": {"item": ["A", "B"]}}
    assert text.content == b"hello"
    assert text.headers["content-type"].startswith("text/plain")


def test_http_retries_keep_metadata_and_payload_evaluation_once():
    attempts, evaluated = [], []

    def respond(request):
        attempts.append(request.content)
        if len(attempts) == 1:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, text="accepted")

    def payload():
        evaluated.append("payload")
        return "body"

    def timeout():
        evaluated.append("metadata")
        return 1

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            runner.root_scope["payload"] = payload
            runner.root_scope["timeout"] = timeout
            result = runner.handle_script("""
                https://api/items#(retries: 1; backoff: 0;
                    timeout: (timeout))<- (payload)
            """)
            assert result.status == "ok", result.error_message
            assert result.value == "accepted"
            assert evaluated == ["metadata", "payload"]
            assert attempts == [b"body", b"body"]


@pytest.mark.parametrize("payload", [b"\x00\xff", bytearray(b"\x00\xff")])
def test_http_binary_payloads_are_sent_verbatim(payload):
    captured = []

    def respond(request):
        captured.append(request.content)
        return httpx.Response(200, text="accepted")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            runner.root_scope["payload"] = payload
            result = runner.handle_script("""
                https://api/bytes#(retries: 0)<- payload
            """)
            assert result.status == "ok", result.error_message
            assert captured == [b"\x00\xff"]


@pytest.mark.parametrize("background_io", [True, False])
def test_http_borrowed_client_retains_session_and_timeout_defaults(
    background_io,
):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, text="accepted")

    transport = httpx.MockTransport(respond)
    with httpx.Client(
        transport=transport, timeout=7, headers={"X-Session": "one"},
        cookies={"session": "token"},
    ) as client:
        with ScriptRunner(http_client=client,
                          background_io=background_io) as runner:
            result = runner.handle_script("https://api/data")
            assert result.status == "ok", result.error_message
        assert not client.is_closed
        request, = captured
        assert request.headers["x-session"] == "one"
        assert request.headers["cookie"] == "session=token"
        assert request.extensions["timeout"]["read"] == 7


def test_http_payload_reference_text_fallback_is_explicit():
    class Opaque:
        def __str__(self):
            return "opaque"

    captured = []

    def respond(request):
        captured.append(request.content)
        return httpx.Response(200, text="accepted")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            runner.root_scope["payload"] = Opaque()
            result = runner.handle_script("""
                mime: 'application/json'
                api: resource `https://api/items#(content-type: mime)`
                post api payload
            """)
            assert result.status == "ok", result.error_message
            assert captured == [b"opaque"]


def test_http_default_retry_count_is_finite():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, text="accepted")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(
                "https://api/data#(backoff: 0)",
            )
            assert result.status == "ok", result.error_message
            assert len(calls) == 3


def test_http_exhausted_transport_error_is_protocol_failure():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("too slow", request=request)

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                https://api/down#(retries: 1; backoff: 0;
                    response-mode: `full`)
            """)
            assert result.status == "err" and len(calls) == 2
            assert result.error["kind"] == PathLiteral(SlipPath(["protocol"]))
            assert result.error["protocol-status"] is None
            assert result.error["meta"]["method"] == "GET"
            assert "too slow" in result.error_message


def test_async_http_client_is_rejected_before_any_request():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="must not request")

    transport = httpx.MockTransport(respond)
    client = httpx.AsyncClient(transport=transport)
    with pytest.raises(TypeError, match="requires an httpx.Client"):
        ScriptRunner(http_client=client)
    assert calls == [] and not client.is_closed


def test_http_modules_cache_source_and_return_isolated_shadows():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/world.slip":
            return httpx.Response(200, text="""
                math: import `https://api/math.slip`
                value: math.add 2 3
                read: fn {} [https://api/data]
            """)
        if request.url.path == "/math.slip":
            return httpx.Response(200, text="add: fn {a, b} [a + b]")
        return httpx.Response(200, json={"answer": 42})

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("""
                first: import `https://api/world.slip`
                second: import 'https://api/world.slip'
                first.value: 100
                #[first.value, second.value, first = second, second.read]
            """)
            assert result.status == "ok", result.error_message
            assert result.value == [100, 5, False, {"answer": 42}]
            assert calls == ["https://api/world.slip", "https://api/math.slip",
                             "https://api/data"]


def test_http_module_request_metadata_is_evaluated_once():
    evaluated, requests = [], []

    def headers():
        evaluated.append("metadata")
        return {"X-Load": "one"}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="value: 7")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        with ScriptRunner(http_client=client) as runner:
            runner.root_scope["headers"] = headers
            result = runner.handle_script("""
                module: import `https://api/module.slip#(headers: (headers))`
                module.value
            """)
            assert result.status == "ok", result.error_message
            assert result.value == 7
            assert evaluated == ["metadata"]
            request, = requests
            assert request.headers["x-load"] == "one"


@pytest.mark.parametrize("background_io", [True, False])
def test_default_http_client_is_reused_and_runner_owned(background_io):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/ping")
                body = b""
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                body = b"pong"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True,
    )
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        runner = ScriptRunner(background_io=background_io)
        with runner:
            if background_io:
                assert isinstance(runner.resources.http_client,
                                  httpx.AsyncClient)
                assert runner.resources.worker.thread.is_alive()
            else:
                assert isinstance(runner.resources.http_client, httpx.Client)
                assert runner.resources.worker is None
            result = runner.handle_script(f"{url}/redirect")
            assert result.status == "ok", result.error_message
            assert result.value == "pong"
            client = runner.resources.http_client
            following = runner.handle_script(f"{url}/ping")
            assert following.status == "ok" and following.value == "pong"
            assert runner.resources.http_client is client
        assert client.is_closed
        if background_io:
            assert not runner.resources.worker.thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
