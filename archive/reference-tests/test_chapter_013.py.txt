import pytest

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == 'ok', f"Expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected, f"Expected {expected!r}, got {res.value!r}"


def assert_error(res, contains: str | None = None):
    assert res.status == 'err', f"Expected error, got {res.status} with value {res.value!r}"
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


@pytest.mark.asyncio
async def test_http_delete_default_returns_body(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == "DELETE"
        return {"deleted": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    res = await runner.handle_script("~http://api/items")
    assert_ok(res, {"deleted": True})


@pytest.mark.asyncio
async def test_http_delete_full_mode_direct_del_packages_result(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == "DELETE"
        return 204, {"deleted": True}, {
            "X-Test": "1",
            "Content-Type": "application/json",
        }

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    res = await runner.handle_script("~http://api/items#(response-mode: `full`)")
    expected = {"status": 204, "value": {"deleted": True}, "meta": {"headers": {"x-test": "1", "content-type": "application/json"}}}
    assert_ok(res, expected)


@pytest.mark.asyncio
async def test_resource_delete_default_returns_body(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == "DELETE"
        return {"deleted": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = """
    r: resource `http://api/items`
    del r
    """
    res = await runner.handle_script(src)
    assert_ok(res, {"deleted": True})


@pytest.mark.asyncio
async def test_resource_put_full_mode_packages_result(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == "PUT"
        return 200, {"ok": True}, {"X-Test": "1"}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = """
    r: resource `http://api/items#(response-mode: `full`)`
    put r #{ name: 'a' }
    """
    res = await runner.handle_script(src)
    expected = {"status": 200, "value": {"ok": True}, "meta": {"headers": {"x-test": "1"}}}
    assert_ok(res, expected)


@pytest.mark.asyncio
async def test_direct_put_assignment_returns_rhs_even_with_response_mode(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        # Return something recognizable; evaluator should ignore and return RHS
        status = 200
        value = {"server": "ignored"}
        headers = {}
        return (status, value, headers)

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = "http://api/items#(response-mode: `full`) #{ name: 'a' }"
    res = await runner.handle_script(src)
    assert_ok(res, {"name": "a"})


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['lite', 'none'])
async def test_resource_get_removed_modes_fail(monkeypatch, mode):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        return {"ok": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = f"""
    r: resource `http://api/items#(response-mode: `{mode}`)`
    get r
    """
    res = await runner.handle_script(src)
    assert_error(res, "only supports `full`")


@pytest.mark.asyncio
async def test_legacy_http_flags_fail(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        if method == "GET":
            return {"ok": True}
        return {"deleted": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    res = await runner.handle_script("http://api/items#(lite: true)")
    assert_error(res, "legacy HTTP response flags were removed")

    res = await runner.handle_script("~http://api/items#(full: true)")
    assert_error(res, "legacy HTTP response flags were removed")
