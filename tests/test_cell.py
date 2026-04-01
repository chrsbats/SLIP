import pytest

from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


@pytest.mark.asyncio
async def test_cell_reads_current_values_via_refs():
    src = """
    x: 1
    rx: ref `x`
    c: cell {x: rx} [ x + 1 ]
    v1: c
    x: 2
    v2: c
    #[ v1, v2 ]
    """
    res = await run_slip(src)
    assert_ok(res, [2, 3])


@pytest.mark.asyncio
async def test_cell_accepts_path_literals_directly():
    src = """
    d: #{ hp: 50 }
    c: cell {hp: `d.hp`} [ hp < 60 ]
    c
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_cell_reads_through_identity_boundary():
    src = """
    Combat: resolver #{
      hp: #{ "p1": 55 }
    }
    c: cell {hp: `Combat::hp["p1"]`} [ hp + 5 ]
    c
    """
    res = await run_slip(src)
    assert_ok(res, 60)
