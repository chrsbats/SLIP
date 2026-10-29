"""Runner-owned native I/O jobs, polled by an ordinary synchronous host."""

import asyncio
import json
import threading
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue

import httpx
import pytest

from slip import ScriptRunner, slip_api_method
from slip.slip_core import Failure
from slip.slip_jobs import job_result


@contextmanager
def endpoint(respond):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            result = respond(self, body)
            if result is None:
                self.close_connection = True
                return
            status, headers, response = result
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        do_GET = do_PUT = do_POST = do_DELETE = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_http_jobs_overlap_while_host_runs_mechanics_and_polls():
    entered, release = Queue(), threading.Event()

    def respond(request, body):
        entered.put(request.path)
        assert release.wait(5), "host did not release concurrent requests"
        return 200, {"Content-Type": "application/json"}, json.dumps(
            {"path": request.path},
        ).encode()

    with endpoint(respond) as url, ScriptRunner() as runner:
        try:
            first = runner.submit(url + "/first")
            launched = runner.handle_script(f"""
                job: submit `{url}/second`
                job
            """)
            assert launched.status == "ok", launched.error_message
            second = launched.value
            assert isinstance(first, Future) and isinstance(second, Future)
            assert {entered.get(timeout=3), entered.get(timeout=3)} == {
                "/first", "/second",
            }
            assert not first.done() and not second.done()
            with pytest.raises(TimeoutError, match="not complete"):
                job_result(first)
            pending = runner.handle_script("job-done job")
            assert pending.status == "ok" and pending.value is False
            pending = runner.handle_script("job-result job")
            assert pending.status == "err"
            assert "not complete" in pending.error_message
            mechanics = runner.handle_script("hp: 100; hp: - 7; hp")
            assert mechanics.status == "ok" and mechanics.value == 93
        finally:
            release.set()
        assert first.result(timeout=3) == {"path": "/first"}
        assert second.result(timeout=3) == {"path": "/second"}
        collected = runner.handle_script("#[job-done job, job-result job]")
        assert collected.status == "ok", collected.error_message
        assert collected.value == [True, {"path": "/second"}]


def test_native_async_operations_use_worker_and_original_host_methods():
    entered, gates, threads = Queue(), {}, []

    class Host:
        @slip_api_method
        async def fetch(self, key):
            threads.append(threading.get_ident())
            gate = gates[key] = asyncio.Event()
            entered.put(key)
            await gate.wait()
            return {"key": key}

    async def release():
        for gate in gates.values():
            gate.set()

    with ScriptRunner(host_object=Host()) as runner:
        assert runner.root_scope["fetch"].__func__ is Host.fetch
        first = runner.submit(runner.root_scope["fetch"], ["first"])
        launched = runner.handle_script("""
            start: fn {key} [submit `fetch` #[key]]
            start 'second'
        """)
        assert launched.status == "ok", launched.error_message
        assert {entered.get(timeout=3), entered.get(timeout=3)} == {
            "first", "second",
        }
        assert not first.done() and not launched.value.done()
        runner.submit(release).result(timeout=3)
        assert first.result(timeout=3) == {"key": "first"}
        assert launched.value.result(timeout=3) == {"key": "second"}
        assert threads == [runner.resources.worker.thread.ident] * 2
        assert threads[0] != threading.get_ident()


@pytest.mark.parametrize("form", ["function", "partial", "callable-object"])
def test_async_operation_forms_and_exception_results(form):
    async def operation(value):
        await asyncio.sleep(0)
        return value

    class AsyncOperation:
        async def __call__(self, value):
            return await operation(value)

    async def fail():
        raise ValueError("external failure")

    function = {"function": operation, "partial": partial(operation),
                "callable-object": AsyncOperation()}[form]
    with ScriptRunner() as runner:
        assert runner.submit(function, [7]).result(timeout=3) == 7
        failed = runner.submit(fail)
        with pytest.raises(ValueError, match="external failure"):
            failed.result(timeout=3)
        runner.scope["failed"] = failed
        captured = runner.handle_script("do [job-result failed]")
        assert captured.status == "ok", captured.error_message
        assert captured.value["error"]["message"] == "external failure"


def test_http_job_verbs_metadata_payload_and_protocol_errors():
    requests, evaluated = [], []

    def respond(request, body):
        requests.append((
            request.command, request.path, dict(request.headers), body,
        ))
        if request.path == "/missing":
            return 404, {"X-Test": "one"}, b"missing"
        return 200, {"Content-Type": "application/json"}, b'{"ok":true}'

    with endpoint(respond) as url, ScriptRunner() as runner:
        def headers():
            evaluated.append("metadata")
            return {"X-Test": "one"}

        def payload():
            evaluated.append("payload")
            return {"value": 7}

        runner.root_scope["headers"] = headers
        runner.root_scope["payload"] = payload
        launched = runner.handle_script(f"""
            start: fn {{timeout}} [
                submit "{url}/items#(content-type: 'application/json';
                    timeout: timeout; headers: (headers))<-" #[(payload)]
            ]
            start 2
        """)
        assert launched.status == "ok", launched.error_message
        assert launched.value.result(timeout=3) == {"ok": True}
        assert evaluated == ["payload", "metadata"]
        method, path, sent_headers, body = requests[0]
        assert (method, path) == ("POST", "/items")
        assert sent_headers["X-Test"] == "one"
        assert json.loads(body) == {"value": 7}
        cases = (
            (":", ["body"], "PUT"), ("", [], "GET"), ("", [], "DELETE"),
        )
        for suffix, args, expected in cases:
            prefix = "~" if expected == "DELETE" else ""
            target = prefix + url + "/items" + suffix
            value = runner.submit(target, args).result(timeout=3)
            assert value == {"ok": True}
            assert requests[-1][0] == expected
        failed = runner.submit(url + "/missing")
        with pytest.raises(Failure, match="HTTP 404") as error:
            failed.result(timeout=3)
        assert error.value.error["protocol-status"] == 404
        assert error.value.error["data"] == "missing"
        full = runner.submit(url + "/missing#(response-mode: `full`)")
        result = full.result(timeout=3)
        assert result["status"] == 404 and result["value"] == "missing"
        assert result["meta"]["headers"]["x-test"] == "one"


def test_foreground_and_background_http_share_owned_session_and_connections():
    connections = []

    def respond(request, body):
        connections.append(request.client_address)
        if request.path == "/login":
            return 200, {"Set-Cookie": "session=one"}, b"logged in"
        return 200, {}, request.headers.get("Cookie", "missing").encode()

    with endpoint(respond) as url, ScriptRunner() as runner:
        foreground = runner.handle_script(url + "/login")
        assert foreground.status == "ok", foreground.error_message
        job = runner.submit(url + "/session")
        assert job.result(timeout=3) == "session=one"
        assert connections[0] == connections[1]


def test_borrowed_sync_client_is_not_ignored_by_background_http():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="foreground")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            with pytest.raises(TypeError, match="Runner-owned async client"):
                runner.submit("https://api/items")
            result = runner.handle_script("https://api/items")
            assert result.status == "ok" and result.value == "foreground"
            assert len(requests) == 1
        assert not client.is_closed


def test_shutdown_cancels_jobs_waits_for_cleanup_and_closes_owned_resources():
    entered, cleaned = Queue(), Queue()

    async def pending():
        entered.put(True)
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.put(True)

    runner = ScriptRunner()
    worker, client = runner.resources.worker, runner.resources.http_client
    job = runner.submit(pending)
    assert entered.get(timeout=3)
    runner.close()
    assert cleaned.get(timeout=3)
    assert job.cancelled() and client.is_closed
    assert worker.loop.is_closed() and not worker.thread.is_alive()
    with pytest.raises(CancelledError):
        job_result(job)
    runner.close()
    with pytest.raises(RuntimeError, match="closed"):
        runner.submit(pending)


def test_worker_cannot_execute_slip_or_block_on_foreground_http():
    with ScriptRunner() as runner:
        async def enter_script():
            return runner.handle_script("value: 7")

        async def enter_http():
            return runner.resources.request("GET", "https://api/data", {})

        async def close_from_worker():
            runner.close()

        for operation in (enter_script, enter_http, close_from_worker):
            job = runner.submit(operation)
            with pytest.raises(RuntimeError, match="host thread"):
                job.result(timeout=3)
        assert "value" not in runner.scope and not runner.closed


def test_submission_rejects_slip_code_and_sync_calls_without_running_them():
    calls = []

    def sync_operation():
        calls.append("must not run")

    with ScriptRunner() as runner:
        with pytest.raises(TypeError, match="native async function"):
            runner.submit(sync_operation)
        for source in ("submit [print 'must not run']",
                       "submit (fn {} [print 'must not run'])"):
            result = runner.handle_script(source)
            assert result.status == "err"
            assert "tasks are deferred" in result.error_message
            assert result.side_effects == [
                {"topics": ["stderr"], "message": result.error_message},
            ]
        assert calls == []


def test_job_concurrency_is_bounded_and_queued_cancellation_does_not_run():
    entered, gates = Queue(), []

    async def hold(value):
        gate = asyncio.Event()
        gates.append(gate)
        entered.put(value)
        await gate.wait()
        return value

    with ScriptRunner() as runner:
        jobs = [runner.submit(hold, [value]) for value in range(33)]
        started = {entered.get(timeout=3) for _ in range(32)}
        assert started == set(range(32))
        worker = runner.resources.worker
        # A barrier on the actual loop establishes that the queue drained.
        checked = threading.Event()
        worker.loop.call_soon_threadsafe(checked.set)
        assert checked.wait(3)
        assert entered.empty() and not jobs[-1].done()
        assert jobs[-1].cancel()

        def release():
            for gate in gates:
                gate.set()

        worker.loop.call_soon_threadsafe(release)
        assert [job.result(timeout=3) for job in jobs[:-1]] == list(range(32))
        assert jobs[-1].cancelled() and entered.empty()


def test_async_http_retries_keep_payload_and_pending_backoff_off_host_thread():
    requests, entered = [], Queue()

    def respond(request, body):
        requests.append((request.path, body))
        if request.path == "/retry" and len(requests) < 3:
            return None
        if request.path == "/backoff":
            entered.put(True)
            return None
        return 200, {}, b"done"

    with endpoint(respond) as url, ScriptRunner() as runner:
        job = runner.submit(url + "/retry#(backoff: 0)<-", ["body"])
        assert job.result(timeout=3) == "done"
        assert requests == [("/retry", b"body")] * 3
        pending = runner.submit(url + "/backoff#(retries: 1; backoff: 60)")
        assert entered.get(timeout=3)
        quick = runner.submit(url + "/quick")
        assert quick.result(timeout=3) == "done"
        assert not pending.done()
        pending.cancel()


@pytest.mark.parametrize(("mime", "body", "expected"), [
    ("application/yaml", b"flag: on\nenabled: false",
     {"flag": "on", "enabled": False}),
    ("application/toml", b"value = 7", {"value": 7}),
    ("application/xml", b"<root>7</root>", {"root": "7"}),
    ("application/json", b"{value: on}", {"value": "on"}),
    ("text/plain; charset=iso-8859-1", b"caf\xe9", "café"),
])
def test_background_http_uses_existing_wire_decoding(mime, body, expected):
    def respond(request, payload):
        return 200, {"Content-Type": mime}, body

    with endpoint(respond) as url, ScriptRunner() as runner:
        assert runner.submit(url + "/data").result(timeout=3) == expected


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:1/data[0]", "file://data.json", "slip://future/action",
    "http://127.0.0.1:1/data#(response-mode: `lite`)",
])
def test_invalid_or_deferred_resource_jobs_fail_before_io(target):
    with ScriptRunner() as runner:
        with pytest.raises((TypeError, ValueError),
                           match="query|HTTP|Unsupported|full"):
            runner.submit(target)


@pytest.mark.parametrize("phase", ["loop", "client"])
def test_worker_startup_failure_propagates_and_joins_thread(
    monkeypatch, phase,
):
    from slip import slip_jobs

    before = set(threading.enumerate())

    def fail(*args, **kwargs):
        raise RuntimeError("startup failed")

    if phase == "loop":
        monkeypatch.setattr(slip_jobs.asyncio, "new_event_loop", fail)
    else:
        monkeypatch.setattr(slip_jobs.httpx, "AsyncClient", fail)
    with pytest.raises(RuntimeError, match="startup failed"):
        ScriptRunner()
    assert set(threading.enumerate()) == before


def test_marked_host_operations_still_shadow_builtin_resource_names():
    class Host:
        @slip_api_method
        def get(self, target, options):
            return "host override"

    with ScriptRunner(host_object=Host()) as runner:
        assert runner.root_scope["get"].__func__ is Host.get
        result = runner.handle_script("https://must-not-request/data")
        assert result.status == "ok" and result.value == "host override"


@pytest.mark.parametrize("path", ["operations[0]", "operations(index)"])
def test_submission_binds_indexed_and_computed_native_operation_paths(path):
    async def fetch(value):
        return value

    with ScriptRunner() as runner:
        runner.scope["operations"] = [fetch]
        runner.scope["index"] = 0
        assert runner.submit(path, [7]).result(timeout=3) == 7
        result = runner.handle_script(f"submit `{path}` #[8]")
        assert result.status == "ok", result.error_message
        assert result.value.result(timeout=3) == 8
        local = runner.handle_script("""
            launch: fn {position} [submit `operations[position]` #[9]]
            launch 0
        """)
        assert local.status == "ok", local.error_message
        assert local.value.result(timeout=3) == 9


@pytest.mark.parametrize("entry", [
    "submit", "resource", "code-import", "file-import",
])
def test_worker_reentry_cannot_evaluate_metadata_or_modules(tmp_path, entry):
    from slip.slip_syntax import parse, to_path

    mutations = []
    module = tmp_path / "module.slip"
    module.write_text("mark; value: 7")
    with ScriptRunner() as runner:
        runner.root_scope["mark"] = lambda: mutations.append("must not run")
        target = "http://127.0.0.1:1/data#(headers: (mark); retries: 0)"

        async def reenter():
            if entry == "submit":
                return runner.submit(target)
            if entry == "resource":
                return runner.resources.resource(
                    to_path(target), scope=runner.scope,
                )
            source = parse("mark; value: 7") if entry == "code-import" \
                else "file://" + str(module)
            return runner.resources.import_module(source, scope=runner.scope)

        with pytest.raises(RuntimeError, match="host thread"):
            runner.submit(reenter).result(timeout=3)
        assert mutations == [] and runner.resources.modules == {}
        assert "value" not in runner.scope


def test_worker_reentry_does_not_call_borrowed_sync_http_transport():
    requests = []

    def respond(request):
        requests.append(threading.get_ident())
        return httpx.Response(200, text="must not request")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            async def reenter():
                return runner.resources.request("GET", "https://api/data", {})

            with pytest.raises(RuntimeError, match="host thread"):
                runner.submit(reenter).result(timeout=3)
            assert requests == []


def test_mechanics_never_enter_the_io_worker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("ordinary mechanics submitted I/O")

    with ScriptRunner() as runner:
        monkeypatch.setattr(runner.resources.worker, "submit", forbidden)
        result = runner.handle_script("""
            player: #{hp: 100}
            damage: fn {target, amount} [target.hp: - amount; target.hp]
            for {i} 0 3 [damage player 2]
            players: #[player]
            #[player.hp, players[.hp < 100].hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [94, [94]]


def test_opt_out_runs_scripts_hosts_and_public_modules_without_worker(
    tmp_path, monkeypatch,
):
    from slip import slip_resources

    def forbidden():
        raise AssertionError("disabled background I/O created a worker")

    monkeypatch.setattr(slip_resources, "IOWorker", forbidden)
    threads = set(threading.enumerate())
    calls = []

    class Host:
        @slip_api_method
        def host_number(self):
            calls.append(threading.get_ident())
            return 40

    path = tmp_path / "api.slip"
    path.write_text("answer: fn {n: `int`} [host-number + n] |public")
    data = {"hp": 10}
    with ScriptRunner(host_object=Host(), host_data=lambda key: data,
                      background_io=False) as runner:
        assert runner.resources.worker is None
        client = runner.resources.http_client
        result = runner.handle_script("""
            person: host-object 'item'
            for {i} 0 3 [person.hp: - 1]
            person.hp
        """)
        assert result.status == "ok", result.error_message
        assert result.value == 7 and data == {"hp": 7}
        module = runner.import_public_module("file://" + str(path))
        result = module.run_json_command({
            "function": "answer", "arguments": {"n": 2},
        })
        assert result.status == "ok", result.error_message
        assert result.value == 42
        assert calls == [threading.get_ident()]
        assert set(threading.enumerate()) == threads
    assert client.is_closed and runner.closed
    runner.close()
    with pytest.raises(RuntimeError, match="closed"):
        runner.handle_script("1")
    assert set(threading.enumerate()) == threads


def test_disabled_submission_fails_before_target_resolution_or_metadata():
    calls = []

    async def fetch():
        calls.append("operation")

    with ScriptRunner(background_io=False) as runner:
        runner.root_scope["mark"] = lambda: calls.append("metadata")
        runner.root_scope["fetch"] = fetch
        target = "https://must-not-request/data#(headers: (mark))"
        for operation in (fetch, "missing-name", target):
            with pytest.raises(RuntimeError,
                               match="Background I/O is disabled"):
                runner.submit(operation)
        for source in ("submit `fetch`", "submit `" + target + "`"):
            result = runner.handle_script(source)
            assert result.status == "err"
            assert "Background I/O is disabled" in result.error_message
            assert result.side_effects == [
                {"topics": ["stderr"], "message": result.error_message},
            ]
        assert calls == [] and runner.resources.worker is None
    with pytest.raises(RuntimeError, match="closed"):
        runner.submit(fetch)


def test_disabled_background_client_closes_when_context_exits_on_error():
    runner = ScriptRunner(background_io=False)
    client = runner.resources.http_client
    with pytest.raises(ValueError, match="host failure"):
        with runner:
            raise ValueError("host failure")
    assert runner.closed and client.is_closed
