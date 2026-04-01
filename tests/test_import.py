import os
import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_import_file_module_caches(tmp_path):
    # Create a simple module
    mod_path = tmp_path / "math.slip"
    mod_path.write_text(
        "value: 7\n"
        "add: fn {a, b} [ a + b ]\n",
        encoding="utf-8",
    )

    src = f"""
    math1: import `file://{mod_path.as_posix()}`
    math2: import `file://{mod_path.as_posix()}`
    
    -- Shadowing check: modify math1, math2 should remain unchanged
    math1.value: 100
    
    diff: math1.value != math2.value
    same-identity: math1 = math2
    
    result: math2.add 2 3
    result
    """
    print("SOURCE")
    print(src)
    runner = ScriptRunner()
    runner.source_dir = tmp_path.as_posix()
    res = await runner.handle_script(src)
    if res.status != 'ok':
        print("\nDEBUG:", res.format_error())
        print("SIDE_EFFECTS:", res.side_effects)
    assert res.status == 'ok', f"\n{res.format_error()}\nside_effects={res.side_effects!r}"
    # Last expression returns 5 (2 + 3) from math2, which was not modified
    assert res.value == 5
    # Shadowing: math1.value was changed to 100, math2.value remains 7
    assert runner.root_scope['diff'] is True
    # Identity should be false because each import returns a new shadow scope
    assert runner.root_scope['same-identity'] is False

@pytest.mark.asyncio
async def test_file_slip_returns_code_block_not_executed(tmp_path):
    # Write a module that would assign a binding if it were executed
    mod_path = tmp_path / "mod.slip"
    mod_path.write_text(
        "ran: 1\n",
        encoding="utf-8",
    )

    src = f"""
    c: file://{mod_path.as_posix()}
    is-code: is-code? c
    is-code
    """

    runner = ScriptRunner()
    runner.source_dir = tmp_path.as_posix()
    res = await runner.handle_script(src)
    assert res.status == 'ok'
    # The file:// read of a .slip file should return a Code block (not execute it)
    assert res.value is True
    # And the module code must not have executed implicitly
    assert 'ran' not in runner.root_scope.bindings

@pytest.mark.asyncio
async def test_call_allows_assignment_from_path_literal():
    src = """
    x: `y:`
    (call x) 2
    y
    """
    runner = ScriptRunner()
    res = await runner.handle_script(src)
    assert res.status == 'ok'
    assert res.value == 2
