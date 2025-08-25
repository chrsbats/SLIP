import pytest
from slip import ScriptRunner
from slip.slip_datatypes import Response, PathLiteral, GetPath, Name

def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected

def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"

def is_resp_ok(resp: Response) -> bool:
    return isinstance(resp, Response) and resp.status == PathLiteral(GetPath([Name("ok")]))

def is_resp_err(resp: Response) -> bool:
    return isinstance(resp, Response) and resp.status == PathLiteral(GetPath([Name("err")]))

@pytest.mark.asyncio
async def test_example_inline_and_test_single_function_passes():
    runner = ScriptRunner()
    src = """
add: fn {x, y} [ x + y ] |example { x: 2, y: 3 -> 5 }
test add
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_ok(resp), f"expected ok response, got {resp!r}"
    assert resp.value == 1  # one example passed

@pytest.mark.asyncio
async def test_example_with_names_from_scope_and_failure_reporting():
    runner = ScriptRunner()
    src = """
x: 2
y: 3
want: 4
add: fn {x, y} [ x + y ]
add |example { x, y -> want }
test add
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_err(resp), f"expected err response, got {resp!r}"
    # One failure entry with expected/actual recorded
    assert isinstance(resp.value, list) and resp.value, f"failures missing: {resp.value!r}"
    failure = resp.value[0]
    assert "index" in failure
    assert failure.get("expected") == 4
    assert failure.get("actual") == 5

@pytest.mark.asyncio
async def test_test_all_scans_given_scope_and_succeeds():
    runner = ScriptRunner()
    src = """
mod: scope #{}
run-with [
  add: fn {x, y} [ x + y ] |example { x: 1, y: 2 -> 3 }
  mul: fn {x, y} [ x * y ] |example { x: 2, y: 3 -> 6 }
] mod
test-all mod
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    summary_resp = res.value
    assert is_resp_ok(summary_resp), f"expected ok summary response, got {summary_resp!r}"
    summary = summary_resp.value
    assert isinstance(summary, dict)
    assert summary.get("with-examples") == 2
    assert summary.get("failed") == 0
    assert summary.get("passed") == 2
    assert summary.get("details") == []

@pytest.mark.asyncio
async def test_test_all_reports_failures_per_function():
    runner = ScriptRunner()
    src = """
mod: scope #{}
run-with [
  f: fn {x} [ x + 1 ]
  f |example { x: 1 -> 2 }   -- passes
  f |example { x: 1 -> 3 }   -- fails
] mod
test-all mod
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    summary_resp = res.value
    assert is_resp_err(summary_resp), f"expected err summary response, got {summary_resp!r}"
    summary = summary_resp.value
    assert summary.get("with-examples") == 1
    assert summary.get("failed") == 1
    assert isinstance(summary.get("details"), list) and summary["details"], f"details missing: {summary!r}"
    entry = summary["details"][0]
    assert entry.get("name") == "f"
    assert isinstance(entry.get("failures"), list) and entry["failures"], "function failures missing"

@pytest.mark.asyncio
async def test_generic_aggregation_method_and_container_examples():
    runner = ScriptRunner()
    src = """
g: fn {x} [ x ] |example { x: 1 -> 1 }    -- example attached to method
g: fn {x, y} [ x + y ]                     -- second method
g |example { x: 2, y: 3 -> 5 }             -- example attached to container
test g
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_ok(resp), f"expected ok response, got {resp!r}"
    # Both examples should be discovered (method-level + container-level)
    assert resp.value == 2

@pytest.mark.asyncio
async def test_test_records_errors_from_example_execution():
    runner = ScriptRunner()
    src = """
div-fn: fn {x, y} [ x / y ]
div-fn |example { x: 1, y: 0 -> none }
test div-fn
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_err(resp), f"expected err response, got {resp!r}"
    errs = resp.value
    assert isinstance(errs, list) and errs, f"errors payload missing: {errs!r}"
    assert "error" in errs[0]
    # Message content may vary by platform; require division mention
    assert "division" in errs[0]["error"].lower()

@pytest.mark.asyncio
async def test_chain_multiple_examples_and_count():
    runner = ScriptRunner()
    src = """
h: fn {x} [ x + 1 ] |example { x: 1 -> 2 } |example { x: 2 -> 3 }
test h
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_ok(resp), f"expected ok response, got {resp!r}"
    assert resp.value == 2

@pytest.mark.asyncio
async def test_example_with_positional_names_without_keywords():
    runner = ScriptRunner()
    src = """
a: 10
b: 32
want: 42
sum: fn {x, y} [ x + y ]
sum |example { x, y -> want }
test sum
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    resp = res.value
    assert is_resp_ok(resp), f"expected ok response, got {resp!r}"
    assert resp.value == 1
