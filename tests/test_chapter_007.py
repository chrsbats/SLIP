import pytest

from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == 'ok', res.error_message
    if expected is not None:
        assert res.value == expected


def assert_error(res, contains: str | None = None):
    assert res.status == 'err', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


@pytest.mark.asyncio
async def test_function_returns_ordinary_success_value():
    src = """
    f: fn {} [ 123 ]
    f
    """
    res = await run_slip(src)
    assert_ok(res, 123)


@pytest.mark.asyncio
async def test_return_exits_function_with_success_value():
    src = """
    f: fn {} [
      return 7
      999  -- should not run
    ]
    f
    """
    res = await run_slip(src)
    assert_ok(res, 7)


@pytest.mark.asyncio
async def test_fail_exits_function_with_error():
    src = """
    f: fn {} [
      fail "oops"
      "unreachable"
    ]
    f
    """
    res = await run_slip(src)
    assert_error(res, "oops")


@pytest.mark.asyncio
async def test_return_primitive_at_top_level_and_in_function():
    # Top-level return should succeed with the inner value
    res = await run_slip("return 42")
    assert_ok(res, 42)

    # And inside a function it should exit early and yield the value
    src = """
    g: fn {} [
      x: 1
      return 99
      x: 2  -- not executed
    ]
    g
    """
    res2 = await run_slip(src)
    assert_ok(res2, 99)


@pytest.mark.asyncio
async def test_emit_records_side_effects():
    src = """
    emit "stdout" "Hello, world!"
    1 + 1
    """
    res = await run_slip(src)
    assert_ok(res, 2)
    assert res.side_effects == [{'topics': ['stdout'], 'message': 'Hello, world!'}]


@pytest.mark.asyncio
async def test_status_aliases_bound_call_literals():
    src = """
    #[ eq ok `ok`, eq err `err`, eq not-found `not-found`, eq invalid `invalid` ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True, True])
