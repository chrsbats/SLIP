import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_call_with_path_literal_dynamic_set():
    src = """
x: `y:`
(call x) 2
y
"""
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == "success"
    # Last expression evaluates to y, which should be 2
    assert res.value == 2
    assert runner.root_scope["y"] == 2

@pytest.mark.asyncio
async def test_import_with_path_literal_uses_cache(tmp_path):
    mod = tmp_path / "mod.slip"
    mod.write_text("value: 123\n", encoding="utf-8")
    locator = "file:///" + str(mod).lstrip("/")

    src = f"""
p: `{locator}`
m1: import p
m2: import p
eq m1 m2
"""
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == "success"
    # Cached module scopes should be the same object
    assert res.value is True

@pytest.mark.asyncio
async def test_import_with_string_url_via_call_caches_scope(tmp_path):
    mod = tmp_path / "mod2.slip"
    mod.write_text("value: 7\n", encoding="utf-8")
    locator = "file:///" + str(mod).lstrip("/")

    src = f"""
ps: '{locator}'
gp: call ps
m1: import gp
m2: import gp
eq m1 m2
"""
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == "error"
