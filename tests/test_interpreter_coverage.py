import pytest

from slip import ScriptRunner
from slip.slip_datatypes import PathLiteral, GetPath, Name

async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected

def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"

@pytest.mark.asyncio
async def test_alias_assignment_writes_to_inner_path():
    src = """
    y: 0
    alias: `y`
    x: alias
    x: 42
    y
    """
    res = await run_slip(src)
    assert_ok(res, 42)

@pytest.mark.asyncio
async def test_zero_arity_autocall_for_argument_current_scope():
    src = """
    needs-scope: fn {s} [ is-scope? s ]
    needs-scope current-scope
    """
    res = await run_slip(src)
    assert_ok(res, True)

@pytest.mark.asyncio
async def test_delete_prunes_empty_scopes_upward():
    src = """
    s: scope #{}
    s.a: scope #{}
    s.a.b: 1
    ~s.a.b
    has-a: (has-key? s 'a')
    has-a
    """
    res = await run_slip(src)
    assert_ok(res, False)

@pytest.mark.asyncio
async def test_examples_synthesize_methods_and_dispatch_with_do_capture():
    src = """
    adder: fn {a, b} [ a + b ] |example { a: 2, b: 3 -> 5 }
    okv: adder 2 3
    probe: do [ adder 'x' 'y' ]
    #[ okv, probe.outcome.status ]
    """
    res = await run_slip(src)
    assert res.status == 'success'
    okv, status = res.value
    assert okv == 5
    # status is a PathLiteral(`err`)
    assert isinstance(status, PathLiteral)
    assert isinstance(status.inner, GetPath)
    assert len(status.inner.segments) == 1
    assert isinstance(status.inner.segments[0], Name)
    assert status.inner.segments[0].text == 'err'

@pytest.mark.asyncio
async def test_error_format_includes_function_name_for_invalid_args():
    res = await run_slip("add 1 'a'")
    assert_error(res, "TypeError: invalid-args in (add)")

@pytest.mark.asyncio
async def test_exact_arity_preferred_over_variadic_in_dispatch():
    src = """
    f: fn {a, b} [ #[a, b, 'exact'] ]
    f: fn {a, rest...} [ #[a, (len rest), 'variadic'] ]
    f 1 2
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2, 'exact'])
