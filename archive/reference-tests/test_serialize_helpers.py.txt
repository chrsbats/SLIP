import pytest

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


@pytest.mark.asyncio
async def test_to_and_from_json_with_path_literal_format():
    runner = ScriptRunner()
    res = await runner.handle_script("""
    data: #{ name: "Karl", hp: 120 }
    text: to `json` data
    roundtrip: from `json` text
    #[ eq (type-of text) `string`, roundtrip.name, roundtrip.hp ]
    """)
    assert_ok(res, [True, "Karl", 120])


@pytest.mark.asyncio
async def test_to_and_from_json_with_string_format():
    runner = ScriptRunner()
    res = await runner.handle_script("""
    text: to 'json' #[1, 2, 3]
    data: from 'json' text
    #[ eq (type-of data) `list`, data[0], data[2] ]
    """)
    assert_ok(res, [True, 1, 3])


@pytest.mark.asyncio
async def test_to_and_from_yaml():
    runner = ScriptRunner()
    res = await runner.handle_script("""
    data: #{ player: "Karl", hp: 120 }
    text: to `yaml` data
    out: from `yaml` text
    #[ out.player, out.hp ]
    """)
    assert_ok(res, ["Karl", 120])


@pytest.mark.asyncio
async def test_to_and_from_toml():
    runner = ScriptRunner()
    res = await runner.handle_script("""
    data: #{ player: "Karl", hp: 120 }
    text: to `toml` data
    out: from `toml` text
    #[ out.player, out.hp ]
    """)
    assert_ok(res, ["Karl", 120])
