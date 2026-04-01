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
async def test_ref_reads_latest_value_from_scope():
    src = """
    x: 1
    r: ref `x`
    v1: r
    x: 2
    v2: r
    #[ v1, v2 ]
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2])


@pytest.mark.asyncio
async def test_ref_reads_nested_paths():
    src = """
    d: #{ user: #{ name: "Kael", hp: 100 } }
    r: ref `d.user.hp`
    r
    """
    res = await run_slip(src)
    assert_ok(res, 100)


@pytest.mark.asyncio
async def test_ref_reads_through_identity_boundary_for_reads():
    src = """
    Combat: resolver #{
      hp: #{ "p1": 55 }
    }
    r: ref `Combat::hp["p1"]`
    r
    """
    res = await run_slip(src)
    assert_ok(res, 55)


@pytest.mark.asyncio
async def test_ref_can_read_code_loaded_from_file_locator(tmp_path):
    # Create a module that computes a value using '+' (root.slip must be available)
    mod = tmp_path / "mod.slip"
    mod.write_text("x: 41\nx + 1\n", encoding="utf-8")
    url = f"file:///{str(mod).lstrip('/')}"

    runner = ScriptRunner()
    # Ensure relative/absolute file:// resolution is consistent for this test
    runner.source_dir = str(tmp_path)
    await runner._initialize()

    src = f"""
    code: {url}
    r: ref `{url}`
    -- Both should be Code values (file_get returns Code for .slip)
    is-code?: is-code? r
    -- run the dereferenced code
    v: run r
    #[ is-code?, v ]
    """
    res = await runner.handle_script(src)
    assert_ok(res, [True, 42])
