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
async def test_response_constructor_and_fields():
    src = """
    r: response `ok` 123
    #[ eq r.status ok, r.value ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 123])


@pytest.mark.asyncio
async def test_respond_exits_function_and_returns_response():
    src = """
    f: fn {} [
      respond ok 7
      999  -- should not run
    ]
    out: f
    #[ eq out.status ok, out.value ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 7])


@pytest.mark.asyncio
async def test_respond_err_status_and_payload():
    src = """
    f: fn {} [
      respond err "oops"
      "unreachable"
    ]
    out: f
    #[ eq out.status err, out.value ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, "oops"])


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
