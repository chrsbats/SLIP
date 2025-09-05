import pytest

from slip import ScriptRunner


@pytest.mark.asyncio
async def test_resource_get_lite_and_full(monkeypatch):
    captured = {}

    async def fake_http_get(url, cfg):
        captured["url"] = url
        captured["cfg"] = dict(cfg or {})
        # Return a tuple like httpx path would package for lite/full
        return (201, {"ok": True}, {"Content-Type": "application/json", "X-Test": "1"})

    monkeypatch.setattr("slip.slip_http.http_get", fake_http_get)

    # Lite mode via #(lite: true)
    runner = ScriptRunner()
    await runner._initialize()
    res = await runner.handle_script("""
    r: resource `http://example.com/data#(lite: true)`
    get r
    """)
    assert res.status == "success"
    assert res.value == [201, {"ok": True}]

    # Full mode via #(full: true)
    runner = ScriptRunner()
    await runner._initialize()
    res2 = await runner.handle_script("""
    r: resource `http://example.com/data#(full: true)`
    get r
    """)
    assert res2.status == "success"
    assert isinstance(res2.value, dict)
    assert res2.value["status"] == 201
    assert res2.value["value"] == {"ok": True}
    # headers are lower-cased in meta
    assert "meta" in res2.value and "headers" in res2.value["meta"]
    assert res2.value["meta"]["headers"]["x-test"] == "1"


@pytest.mark.asyncio
async def test_put_with_content_type_serialization(monkeypatch, tmp_path):
    recorded = {}

    async def fake_http_put(url, payload, cfg):
        recorded["url"] = url
        recorded["payload"] = payload
        recorded["cfg"] = dict(cfg or {})
        # Echo a recognizable raw result
        return ("OK", 204, {})

    monkeypatch.setattr("slip.slip_http.http_put", fake_http_put)

    runner = ScriptRunner()
    await runner._initialize()
    # JSON content-type triggers serialization of the dict payload
    res = await runner.handle_script("""
    r: resource `http://example.com/items#(content-type: "application/json")`
    put r #{ a: 1, b: 2 }
    """)
    assert res.status == "success"
    # Ensure payload is a JSON string
    assert isinstance(recorded.get("payload"), str)
    assert '"a": 1' in recorded["payload"] and '"b": 2' in recorded["payload"]
    # Header promotion happens
    assert "headers" in recorded["cfg"]
    assert recorded["cfg"]["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_import_file_module_and_caching(tmp_path):
    mod_path = tmp_path / "mod.slip"
    mod_path.write_text("x: 2\ny: 3\n")

    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)
    await runner._initialize()

    # Import using a path literal and assert values visible
    res = await runner.handle_script("""
    m1: import `file://./mod.slip`
    #[ m1.x, m1.y ]
    """)
    assert res.status == "success"
    assert res.value == [2, 3]

    # Same module imported twice should return the same scope object (identity)
    res2 = await runner.handle_script("""
    m1: import `file://./mod.slip`
    m2: import `file://./mod.slip`
    eq m1 m2
    """)
    assert res2.status == "success"
    assert res2.value is True

    # Also support string form
    res3 = await runner.handle_script("""
    m: import 'file://./mod.slip'
    m.x
    """)
    assert res3.status == "success"
    assert res3.value == 2
