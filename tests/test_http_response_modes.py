import pytest
from slip import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', f"Expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected, f"Expected {expected!r}, got {res.value!r}"

def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"Expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"

@pytest.mark.asyncio
async def test_http_get_lite_mode_returns_status_and_value_list(monkeypatch):
    # Fake http_request that honors response-mode and returns body/tuple accordingly
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        cfg = dict(config or {})
        mode = cfg.get('response-mode')
        # Normalize enum-like path literal/string to plain string
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

        # Simulate simple endpoints
        status = 200
        value = {"ok": True}
        headers = {"x-test": "1", "content-type": "application/json"}

        # Package per mode
        if mode in ('lite', 'full'):
            return (status, value, headers)
        # Default strict (none): return body
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip("http://api/items#(response-mode: `lite`)")
    assert_ok(res, [200, {"ok": True}])

@pytest.mark.asyncio
async def test_http_get_full_mode_returns_struct_with_headers(monkeypatch):
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

        status = 200
        value = {"ok": True}
        headers = {"x-test": "1", "content-type": "application/json"}

        if mode in ('lite', 'full'):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip("http://api/items#(response-mode: `full`)")
    expected = {"status": 200, "value": {"ok": True}, "meta": {"headers": {"x-test": "1", "content-type": "application/json"}}}
    assert_ok(res, expected)

@pytest.mark.asyncio
async def test_http_get_default_none_returns_body_and_errors_on_non_2xx(monkeypatch):
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

        # Missing endpoint
        if "missing" in url:
            status = 404
            value = {"error": "not found"}
            headers = {"content-type": "application/json"}
            if mode in ('lite', 'full'):
                return (status, value, headers)
            raise RuntimeError(f"HTTP {status} for {url}: not found")

        # Default OK endpoint
        status = 200
        value = {"ok": True}
        headers = {"content-type": "application/json"}
        if mode in ('lite', 'full'):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    # No response-mode: returns bare body
    res = await run_slip("http://api/items")
    assert_ok(res, {"ok": True})

    # No response-mode on error: raises → script error
    res = await run_slip("http://api/missing")
    assert_error(res, "HTTP 404")

@pytest.mark.asyncio
async def test_http_post_with_lite_mode_packages_result(monkeypatch):
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

        if method.upper() == "POST":
            status = 201
            value = {"id": 7}
            headers = {"location": "/items/7"}
            if mode in ('lite', 'full'):
                return (status, value, headers)
            return value
        # Fallback for GET
        status = 200
        value = {"ok": True}
        headers = {}
        if mode in ('lite', 'full'):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    src = "http://api/items#(response-mode: `lite`)<- #{ name: 'a' }"
    res = await run_slip(src)
    assert_ok(res, [201, {"id": 7}])

@pytest.mark.asyncio
async def test_resource_get_lite_mode_packages_result(monkeypatch):
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

        status = 200
        value = {"ok": True}
        headers = {"x-test": "1"}
        if mode in ('lite', 'full'):
            return (status, value, headers)
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    src = """
    r: resource `http://api/items#(response-mode: `lite`)`
    get r
    """
    res = await run_slip(src)
    assert_ok(res, [200, {"ok": True}])

@pytest.mark.asyncio
async def test_http_get_explicit_none_mode_behaves_like_default(monkeypatch):
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

        status = 200
        value = {"ok": True}
        headers = {}
        if mode in ('lite', 'full'):
            return (status, value, headers)
        # Explicit 'none' or unset → return body as default
        return value

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    # Explicit none mode
    res = await run_slip("http://api/items#(response-mode: `none`)")
    assert_ok(res, {"ok": True})
