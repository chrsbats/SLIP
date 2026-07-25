import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_execution_success_reflects_final_value_without_global_outcome():
    runner = ScriptRunner()
    res = await runner.handle_script("1 + 2")
    assert res.status == 'ok'
    assert res.value == 3
    assert "outcome" not in runner.root_scope

@pytest.mark.asyncio
async def test_execution_error_exposes_structured_error_without_global_outcome():
    runner = ScriptRunner()
    res = await runner.handle_script("1 + 'a'")
    assert res.status == 'err'
    assert res.value is None
    assert res.error["kind"] == "runtime"
    assert res.error["code"] == "type-error"
    assert "unsupported operand type" in res.error["message"]
    assert "outcome" not in runner.root_scope
