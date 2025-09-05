import pytest

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

    # lite → tuple (status, value, headers-lowercased)
    status, value, headers = await http_request("GET", "http://example/api", config={"response-mode": "lite", "retries": 0})
    assert status == 200
    assert value == {"hello": "world"}
    assert isinstance(headers, dict) and "content-type" in headers

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
    # None
    assert normalize_response_mode({}) is None
    # legacy flags
    assert normalize_response_mode({"lite": True}) == "lite"
    assert normalize_response_mode({"full": True}) == "full"
    # string (case-insensitive)
    assert normalize_response_mode({"response-mode": "lite"}) == "lite"
    assert normalize_response_mode({"response-mode": "FULL"}) == "full"
    assert normalize_response_mode({"response-mode": "none"}) == "none"
    # invalid string → None
    assert normalize_response_mode({"response-mode": "unknown"}) is None

@pytest.mark.asyncio
async def test_http_request_non_2xx_raises(monkeypatch):
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

    with pytest.raises(RuntimeError):
        await http_request("GET", "http://example/fail", config={"retries": 0})
