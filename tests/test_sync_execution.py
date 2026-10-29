"""Synchronous calls, explicit deferrals, and host-owned execution."""

import ast
import inspect
import threading
from functools import partial
from pathlib import Path

import httpx
import pytest

DIRECTORY = Path(__file__).resolve().parents[1]
from slip import ScriptRunner, slip_api_method  # noqa: E402
from slip.slip_core import Scope, execute, invoke, language_scope  # noqa: E402
from slip.slip_syntax import parse  # noqa: E402


@pytest.mark.parametrize("form", ["function", "partial", "callable-object"])
def test_async_function_forms_fail_without_starting(form):
    entered = []

    async def native(value):
        entered.append(value)
        return value

    class AsyncCallable:
        async def __call__(self, value):
            entered.append(value)
            return value

    function = {"function": native, "partial": partial(native),
                "callable-object": AsyncCallable()}[form]
    with pytest.raises(TypeError, match="Async functions.*unsupported"):
        invoke(function, [7], language_scope())
    assert entered == []


def test_synchronous_call_results_remain_data_without_running_or_closing():
    entered, produced = [], []

    async def deferred():
        entered.append("ran")
        return 7

    def native():
        result = deferred()
        produced.append(result)
        return result

    try:
        with ScriptRunner() as runner:
            runner.root_scope["native"] = native
            result = runner.handle_script("value: native; value")
            assert result.status == "ok", result.error_message
            assert len(produced) == 1 and entered == []
            assert result.value is produced[0]
            state = inspect.getcoroutinestate(result.value)
            assert state == inspect.CORO_CREATED
    finally:
        for value in produced:
            value.close()


def test_custom_awaitable_is_data_in_storage_and_synchronous_call_results():
    class Deferred:
        def __await__(self):
            raise AssertionError("SLIP attempted to await host data")

    data = Deferred()
    with ScriptRunner() as runner:
        runner.root_scope["stored"] = data
        runner.root_scope["native"] = lambda: data
        result = runner.handle_script("stored")
        assert result.status == "ok" and result.value is data
        called = runner.handle_script("native")
        assert called.status == "ok" and called.value is data
        preserved = runner.handle_script("stored")
        assert preserved.status == "ok" and preserved.value is data


@pytest.mark.parametrize("kind", ["custom", "coroutine"])
@pytest.mark.parametrize("source", [
    "alias: stored", "~stored", "if [true] [stored]", "run [stored]",
    "identity: fn {value} [value]; identity stored",
    "true and stored", "false or stored",
])
def test_assignment_and_deletion_preserve_opaque_awaitable_data(kind, source):
    class Deferred:
        def __await__(self):
            raise AssertionError("SLIP attempted to await stored data")

    async def deferred():
        raise AssertionError("SLIP executed stored coroutine data")

    value = deferred() if kind == "coroutine" else Deferred()
    try:
        with ScriptRunner() as runner:
            runner.scope["stored"] = value
            runner.root_scope["stored"] = value
            result = runner.handle_script(source)
            if source == "alias: stored":
                assert runner.scope["alias"] is value
            elif source == "~stored":
                assert "stored" not in runner.scope.bindings
            if kind == "coroutine":
                assert inspect.getcoroutinestate(value) == inspect.CORO_CREATED
            assert result.status == "ok", result.error_message
            assert result.value is value
    finally:
        if kind == "coroutine":
            value.close()


@pytest.mark.parametrize("source", ["host-data 'id:x'", "host-object 'id:x'"])
def test_async_host_gateways_fail_without_loading(source):
    entered = []

    async def load(object_id):
        entered.append(object_id)
        return {"hp": 10}

    with ScriptRunner(host_data=load) as runner:
        result = runner.handle_script(source)
        assert result.status == "err"
        assert "Async functions are unsupported" in result.error_message
        assert entered == []


def test_async_marked_method_is_rejected_and_keeps_original_identity():
    class Host:
        @slip_api_method
        async def action(self):
            raise AssertionError("must not execute")

    host = Host()
    with ScriptRunner(host_object=host) as runner:
        assert runner.root_scope["action"].__func__ is Host.action
        result = runner.handle_script("action")
        assert result.status == "err"
        assert "Async functions are unsupported" in result.error_message


def test_loops_execute_on_the_calling_thread_without_a_bridge():
    thread_ids = []

    def checkpoint(value):
        thread_ids.append(threading.get_ident())
        return value

    with ScriptRunner() as runner:
        runner.root_scope["checkpoint"] = checkpoint
        result = runner.handle_script("""
            total: 0
            for {i} 0 10 [total: + (checkpoint i)]
            foreach {n} #[1, 2] [total: + (checkpoint n)]
            total
        """)
        assert result.status == "ok", result.error_message
        assert result.value == 48
        assert thread_ids == [threading.get_ident()] * 12


def test_http_retries_use_native_blocking_backoff(monkeypatch):
    from slip import slip_resources

    requests, delays = [], []

    def respond(request):
        requests.append(request)
        if len(requests) < 3:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, text="done")

    monkeypatch.setattr(slip_resources.time, "sleep", delays.append)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script("https://api/data")
            assert result.status == "ok" and result.value == "done"
            assert len(requests) == 3 and delays == [0.2, 0.4]
        assert not client.is_closed


def test_interpreter_has_no_async_or_scheduler_path():
    names = "core", "library", "syntax", "embedding", "cache"
    for name in names:
        tree = ast.parse((DIRECTORY / f"slip/slip_{name}.py").read_text())
        for node in ast.walk(tree):
            assert not isinstance(node, (
                ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith,
            )), name
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports = [alias.name for alias in node.names] \
                    if isinstance(node, ast.Import) else [node.module]
                assert "asyncio" not in imports, name
    resources = ast.parse((DIRECTORY / "slip/slip_resources.py").read_text())
    assert [node.name for node in resources.body
            if isinstance(node, ast.AsyncFunctionDef)] == ["request_http"]
    scope = Scope(parent=language_scope())
    assert execute(parse("2 + 3"), scope) == 5
