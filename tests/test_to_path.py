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
    if res.status != 'ok':
        raise AssertionError(f"ERROR:\n{res.error_message}\n\nEFFECTS:\n{res.side_effects}")
    assert res.status == 'ok'
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
m1.value: 999
#[ m1.value != m2.value, eq m1 m2 ]
"""
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == 'ok', f"ERROR:\n{res.error_message}\n\nEFFECTS:\n{res.side_effects}"
    # Shadowing: m1 change doesn't affect m2, and they are not the same object
    assert res.value == [True, False]

@pytest.mark.asyncio
async def test_import_with_string_url_via_call_caches_scope(tmp_path):
    mod = tmp_path / "mod2.slip"
    mod.write_text("value: 7\n", encoding="utf-8")
    locator = "file:///" + str(mod).lstrip("/")

    src = f"""
ps: '{locator}'
gp: call ps
-- gp is now a GetPath object. import extracts the locator from it.
m1: import gp
m2: import gp
m1.value: 999
#[ m1.value != m2.value, eq m1 m2 ]
"""
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == 'ok', f"ERROR:\n{res.error_message}\n\nEFFECTS:\n{res.side_effects}"
    # Shadowing: m1 change doesn't affect m2, and they are not the same object
    assert res.value == [True, False]
