import pytest

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == 'success', f"Expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected, f"Expected {expected!r}, got {res.value!r}"


def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"Expected error, got {res.status} with value {res.value!r}"
    if contains:
        assert contains in (res.error_message or ""), f"Expected error to contain {contains!r}, got: {res.error_message!r}"


@pytest.mark.asyncio
async def test_execution_success_and_side_effects_are_recorded_in_order():
    runner = ScriptRunner()
    src = """
emit "combat" "start"
emit #["visual", "sound"] "boom"
42
"""
    res = await runner.handle_script(src)
    assert_ok(res, 42)
    assert res.side_effects == [
        {"topics": ["combat"], "message": "start"},
        {"topics": ["visual", "sound"], "message": "boom"},
    ]


@pytest.mark.asyncio
async def test_error_formatting_includes_line_and_path_message_and_stderr_side_effect():
    runner = ScriptRunner()
    res = await runner.handle_script("foo")
    assert_error(res, "PathNotFound: foo")

    formatted = res.format_error()
    assert "Error on line 1" in formatted
    assert "PathNotFound: foo" in formatted

    # Ensure a stderr side-effect was recorded with the formatted message
    assert any("stderr" in (eff.get("topics") or []) and "PathNotFound: foo" in (eff.get("message") or "")
               for eff in res.side_effects)


@pytest.mark.asyncio
async def test_top_level_return_unwraps_to_success_value():
    runner = ScriptRunner()
    res = await runner.handle_script("return 99")
    assert_ok(res, 99)
