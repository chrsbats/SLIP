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
async def test_do_captures_effects_and_ok_value():
    src = """
    emit "debug" "before"
    r: do [
      emit "debug" "in-1"
      emit "debug" "in-2"
      7
    ]
    emit "debug" "after"
    #[ r.outcome.status = ok, r.outcome.value, len r.effects, r.effects[0].message, r.effects[1].message ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 7, 2, "in-1", "in-2"])


@pytest.mark.asyncio
async def test_do_unwraps_return_and_preserves_response():
    src = """
    r1: do [ respond ok 123 ]
    r2: do [ response err "bad" ]
    #[ r1.outcome.status = ok, r1.outcome.value, r2.outcome.status = err, r2.outcome.value ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 123, True, "bad"])


@pytest.mark.asyncio
async def test_do_captures_err_on_exception():
    src = """
    r: do [ add "a" 1 ]
    #[ r.outcome.status = err ]
    """
    res = await run_slip(src)
    assert_ok(res, [True])


@pytest.mark.asyncio
async def test_do_accepts_code_variable():
    src = """
    blk: [
      emit "debug" "v"
      1
    ]
    r: do blk
    #[ r.outcome.status = ok, r.outcome.value, len r.effects, r.effects[0].message ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 1, 1, "v"])


@pytest.mark.asyncio
async def test_do_requires_code_argument_errors():
    src = "do 1"
    res = await run_slip(src)
    assert_error(res, "do")
