import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_http_get_applies_trailing_segments_client_side(monkeypatch):
    # Stub http_get to return a list of dicts
    async def fake_http_get(url, cfg):
        assert url == "http://game-api/players"
        return [
            {"name": "Jaina", "class": "Mage", "is-active": True, "hp": 120},
            {"name": "Karl",  "class": "Warrior", "is-active": True, "hp": 150},
            {"name": "Medivh","class": "Mage", "is-active": False, "hp": 200},
            {"name": "Thrall","class": "Shaman", "is-active": True, "hp": 130},
        ]
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_get", fake_http_get, raising=True)

    runner = ScriptRunner()
    src = "\n".join([
        "data: http://game-api/players",
        "mage-names: data[.class = 'Mage' and .is-active = true and .hp > 100].name",
        "mage-names",
    ])
    res = await runner.handle_script(src)
    if res.status != "success":
        print("\n--- DEBUG error_message ---\n", res.error_message, "\n---------------------------\n")
    assert res.status == "success"
    assert res.value == ["Jaina"]

@pytest.mark.asyncio
async def test_http_write_with_trailing_segments_errors(monkeypatch):
    # Prevent real network in case: stub http_put
    async def fake_http_put(url, data, cfg):  # should not be called
        raise AssertionError("http_put should not be invoked when trailing segments are present")
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_put", fake_http_put, raising=True)

    runner = ScriptRunner()
    src = "http://game-api/players.name: 'X'"
    res = await runner.handle_script(src)
    assert res.status == "error"
    assert "TypeError:" in (res.error_message or "")
