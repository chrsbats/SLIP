import pytest

from slip import ScriptRunner
from slip.slip_datatypes import ProtocolFailure
from slip.slip_http import normalize_response_mode


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == 'ok', f"Expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected, f"Expected {expected!r}, got {res.value!r}"


def assert_error(res, contains: str | None = None):
    assert res.status == 'err', f"Expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


def package_response(config, status, value, headers):
    if normalize_response_mode(dict(config or {})) == 'full':
        return status, value, headers
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('removed_mode', ['lite', 'none'])
async def test_http_get_removed_response_modes_fail(monkeypatch, removed_mode):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        return package_response(config, 200, {"ok": True}, {"x-test": "1"})

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip(f"http://api/items#(response-mode: `{removed_mode}`)")
    assert_error(res, "only supports `full`")


@pytest.mark.asyncio
async def test_http_get_full_mode_returns_struct_with_headers(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        return package_response(
            config,
            200,
            {"ok": True},
            {"X-Test": "1", "Content-Type": "application/json"},
        )

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip("http://api/items#(response-mode: `full`)")
    expected = {
        "status": 200,
        "value": {"ok": True},
        "meta": {"headers": {"x-test": "1", "content-type": "application/json"}},
    }
    assert_ok(res, expected)


@pytest.mark.asyncio
async def test_http_get_default_returns_body_and_protocol_failure(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        if "missing" in url:
            raise ProtocolFailure(
                'http',
                f"HTTP 404 for {url}",
                status=404,
                data={"error": "not found"},
            )
        return {"ok": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip("http://api/items")
    assert_ok(res, {"ok": True})

    res = await run_slip("http://api/missing")
    assert_error(res, "HTTP 404")


@pytest.mark.asyncio
async def test_http_post_full_mode_returns_struct(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == 'POST'
        assert data is not None
        return package_response(config, 201, {"id": 7}, {"Location": "/items/7"})

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    src = "http://api/items#(response-mode: `full`)<- #{ name: 'a' }"
    res = await run_slip(src)
    assert_ok(res, {
        "status": 201,
        "value": {"id": 7},
        "meta": {"headers": {"location": "/items/7"}},
    })


@pytest.mark.asyncio
async def test_resource_get_default_returns_body(monkeypatch):
    async def fake_http_request(method: str, url: str, *, config=None, data=None):
        assert method == 'GET'
        return {"ok": True}

    monkeypatch.setattr("slip.slip_http.http_request", fake_http_request, raising=True)

    res = await run_slip("""
    r: resource `http://api/items`
    get r
    """)
    assert_ok(res, {"ok": True})
