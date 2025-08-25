import pytest
from slip import ScriptRunner

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
async def test_call_get_path_returns_value_when_not_callable():
    src = """
    x: 2
    call `x`
    """
    res = await run_slip(src)
    assert_ok(res, 2)

@pytest.mark.asyncio
async def test_call_get_path_with_args_errors_when_target_not_callable():
    src = """
    x: 2
    call `x` #[1]
    """
    res = await run_slip(src)
    assert_error(res, "invalid-args")

@pytest.mark.asyncio
async def test_call_get_path_resolves_function_and_calls_zero_arity():
    src = """
    g: fn {} [ 5 ]
    call `g`
    """
    res = await run_slip(src)
    assert_ok(res, 5)

@pytest.mark.asyncio
async def test_call_direct_callable_zero_arity():
    src = """
    f: fn {} [ 42 ]
    call f
    """
    res = await run_slip(src)
    assert_ok(res, 42)

@pytest.mark.asyncio
async def test_call_set_path_arity_and_success_variants():
    # Error: set-path requires exactly one arg
    res_err0 = await run_slip("call `z:` #[]")
    assert_error(res_err0, "invalid-args")
    res_err2 = await run_slip("call `z:` #[1, 2]")
    assert_error(res_err2, "invalid-args")
    # Success: one arg -> writes and returns value; verify read-back
    src_ok = """
    call `z:` #[7]
    z
    """
    res_ok = await run_slip(src_ok)
    assert_ok(res_ok, 7)

@pytest.mark.asyncio
async def test_call_del_path_both_forms_delete():
    # No-args form deletes
    src1 = """
    y: 1
    call `~y`
    y
    """
    res1 = await run_slip(src1)
    assert_error(res1, "PathNotFound: y")
    # Explicit empty-args list also deletes
    src2 = """
    y: 1
    call `~y` #[]
    y
    """
    res2 = await run_slip(src2)
    assert_error(res2, "PathNotFound: y")

@pytest.mark.asyncio
async def test_call_del_path_with_args_errors():
    res = await run_slip("y: 1\ncall `~y` #[1]")
    assert_error(res, "invalid-args")

@pytest.mark.asyncio
async def test_call_string_constructs_path_literal_including_urls():
    # Simple dotted string -> PathLiteral
    src1 = """
    p: call 'a.b'
    eq p `a.b`
    """
    res1 = await run_slip(src1)
    assert_ok(res1, True)
    # URL string kept as single segment -> PathLiteral of full URL
    src2 = """
    p: call 'http://example.com/api'
    eq p `http://example.com/api`
    """
    res2 = await run_slip(src2)
    assert_ok(res2, True)

@pytest.mark.asyncio
async def test_call_unresolvable_get_path_literal_returns_literal():
    src = """
    p: call `does.not.exist`
    eq p `does.not.exist`
    """
    res = await run_slip(src)
    assert_ok(res, True)
