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


@pytest.mark.asyncio
async def test_http_delete_lite_mode_direct_del_packages_result(monkeypatch):
    # Stub http_request to exercise DELETE packaging
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        try:
            from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name
            if isinstance(mode, _PL):
                inner = getattr(mode, 'inner', None)
                if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                    mode = inner.segments[0].text
            if isinstance(mode, _GP) and len(mode.segments) == 1 and isinstance(mode.segments[0], _Name):
                mode = mode.segments[0].text
        except Exception:
            pass
        if isinstance(mode, str):
            mode = mode.strip().strip('`').lower()
        if method.upper() == "DELETE":
            status = 204
            value = {"deleted": True}
            headers = {"x-test": "1"}
            if mode in ("lite", "full"):
                return (status, value, headers)
            return value
        # Default GET body
        status = 200
        value = {"ok": True}
        headers = {}
        if mode in ("lite", "full"):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    # Direct del-path with lite mode should return [status, value]
    res = await runner.handle_script("~http://api/items#(response-mode: `lite`)")
    assert_ok(res, [204, {"deleted": True}])


@pytest.mark.asyncio
async def test_http_delete_full_mode_direct_del_packages_result(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        try:
            from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name
            if isinstance(mode, _PL):
                inner = getattr(mode, 'inner', None)
                if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                    mode = inner.segments[0].text
            if isinstance(mode, _GP) and len(mode.segments) == 1 and isinstance(mode.segments[0], _Name):
                mode = mode.segments[0].text
        except Exception:
            pass
        if isinstance(mode, str):
            mode = mode.strip().strip('`').lower()
        status = 204
        value = {"deleted": True}
        headers = {"x-test": "1", "content-type": "application/json"}
        if method.upper() == "DELETE":
            if mode in ("lite", "full"):
                return (status, value, headers)
            return value
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    res = await runner.handle_script("~http://api/items#(response-mode: `full`)")
    expected = {"status": 204, "value": {"deleted": True}, "meta": {"headers": {"x-test": "1", "content-type": "application/json"}}}
    assert_ok(res, expected)


@pytest.mark.asyncio
async def test_resource_delete_lite_mode_packages_result(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        if isinstance(mode, str):
            mode = mode.strip().strip('`').lower()
        status = 204
        value = {"deleted": True}
        headers = {"x-test": "1"}
        if method.upper() == "DELETE":
            if mode in ("lite", "full"):
                return (status, value, headers)
            return value
        return {"ok": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = """
    r: resource `http://api/items#(response-mode: `lite`)`
    del r
    """
    res = await runner.handle_script(src)
    assert_ok(res, [204, {"deleted": True}])


@pytest.mark.asyncio
async def test_resource_put_full_mode_packages_result(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        if isinstance(mode, str):
            mode = mode.strip().strip('`').lower()
        status = 200
        value = {"ok": True}
        headers = {"x-test": "1"}
        if method.upper() == "PUT":
            if mode in ("lite", "full"):
                return (status, value, headers)
            return value
        return value

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
async def test_resource_get_explicit_none_mode_behaves_like_default(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        # Return body by default; none mode should not package/raise
        status = 200
        value = {"ok": True}
        headers = {}
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        if isinstance(mode, str):
            mode = mode.strip().strip('`').lower()
        if mode in ("lite", "full"):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    src = """
    r: resource `http://api/items#(response-mode: `none`)`
    get r
    """
    res = await runner.handle_script(src)
    assert_ok(res, {"ok": True})


@pytest.mark.asyncio
async def test_legacy_flags_map_to_response_mode_for_get_and_delete(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = None
        if cfg.get('lite') is True:
            mode = 'lite'
        if cfg.get('full') is True:
            mode = 'full'
        status = 200 if method.upper() == "GET" else 204
        value = {"ok": True} if method.upper() == "GET" else {"deleted": True}
        headers = {"x-test": "1"}
        if mode in ("lite", "full"):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    runner = ScriptRunner()
    # GET with legacy lite flag
    res = await runner.handle_script("http://api/items#(lite: true)")
    assert_ok(res, [200, {"ok": True}])

    # DELETE with legacy full flag
    res = await runner.handle_script("~http://api/items#(full: true)")
    assert res.status == 'success'
    assert res.value["status"] == 204
    assert res.value["value"] == {"deleted": True}
