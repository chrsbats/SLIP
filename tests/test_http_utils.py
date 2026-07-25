import pytest

from slip.slip_datatypes import ProtocolFailure
from slip.slip_http import normalize_response_mode, http_request

@pytest.mark.asyncio
async def test_http_request_default_success_and_modes(monkeypatch):
    # Stub AsyncClient
    class DummyResp:
        def __init__(self, status, content, headers):
            self.status_code = status
            self._content = content
            self.headers = headers
            self.text = content.decode("utf-8", errors="ignore")

        @property
        def content(self):
            return self._content

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def request(self, method, url, headers=None, params=None, content=None):
            # Echo the request content-type into a response header for assertion
            req_ct = (headers or {}).get("Content-Type")
            # Default: JSON body; the JSON is small and tests deserialization
            body = b'{"hello":"world"}'
            return DummyResp(
                200,
                body,
                {"Content-Type": "application/json", "X-Req-Content-Type": req_ct or ""}
            )

    # Monkeypatch httpx.AsyncClient used by http_request
    import slip.slip_http as slip_http_mod
    monkeypatch.setattr(slip_http_mod, "httpx", type("X", (), {"AsyncClient": DummyAsyncClient}))

    # default (no response-mode): returns deserialized body
    out = await http_request("GET", "http://example/api", config={"retries": 0})
    assert isinstance(out, dict) and out["hello"] == "world"

    # Removed modes fail rather than silently changing transport behavior.
    for mode in ("lite", "none"):
        with pytest.raises(ValueError, match="only supports `full`"):
            await http_request(
                "GET",
                "http://example/api",
                config={"response-mode": mode, "retries": 0},
            )

    # full → tuple (status, value, headers-lowercased) – caller packages to dict elsewhere
    status, value, headers = await http_request("GET", "http://example/api", config={"response-mode": "full", "retries": 0})
    assert status == 200
    assert value == {"hello": "world"}
    assert headers.get("content-type") == "application/json"

    # Verify default Content-Type for text body on write (echoed back in response headers)
    status, value, headers = await http_request(
        "PUT",
        "http://example/api",
        config={"response-mode": "full", "retries": 0},
        data="plain text body"
    )
    # The request header should have been set by http_request when content is present
    assert headers.get("x-req-content-type", "").startswith("text/plain")

def test_normalize_response_mode_variants():
    assert normalize_response_mode({}) is None
    assert normalize_response_mode({"response-mode": "FULL"}) == "full"
    for config in (
        {"lite": True},
        {"full": True},
        {"response-mode": "lite"},
        {"response-mode": "none"},
        {"response-mode": "unknown"},
    ):
        with pytest.raises(ValueError):
            normalize_response_mode(config)

@pytest.mark.asyncio
async def test_http_request_non_2xx_is_protocol_failure_by_default(monkeypatch):
    class DummyResp:
        def __init__(self, status, content, headers):
            self.status_code = status
            self._content = content
            self.headers = headers
            self.text = content.decode("utf-8", errors="ignore")
        @property
        def content(self):
            return self._content

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def request(self, method, url, headers=None, params=None, content=None):
            return DummyResp(500, b"server error", {"Content-Type": "text/plain"})

    import slip.slip_http as slip_http_mod
    monkeypatch.setattr(slip_http_mod, "httpx", type("X", (), {"AsyncClient": DummyAsyncClient}))

    with pytest.raises(ProtocolFailure) as exc_info:
        await http_request("GET", "http://example/fail", config={"retries": 0})

    assert exc_info.value.status == 500
    assert exc_info.value.data == "server error"

    status, value, headers = await http_request(
        "GET",
        "http://example/fail",
        config={"response-mode": "full", "retries": 0},
    )
    assert status == 500
    assert value == "server error"
    assert headers["content-type"] == "text/plain"


@pytest.mark.asyncio
async def test_http_request_network_error_is_protocol_failure(monkeypatch):
    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, headers=None, params=None, content=None):
            raise OSError("connection refused")

    import slip.slip_http as slip_http_mod
    monkeypatch.setattr(slip_http_mod, "httpx", type("X", (), {"AsyncClient": DummyAsyncClient}))

    with pytest.raises(ProtocolFailure) as exc_info:
        await http_request("GET", "http://example/fail", config={"retries": 0})

    assert "connection refused" in exc_info.value.message
    assert exc_info.value.status is None
