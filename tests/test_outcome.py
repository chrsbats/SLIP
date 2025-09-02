import pytest
from slip.slip_runtime import ScriptRunner
from slip.slip_datatypes import PathLiteral, GetPath, Name

@pytest.mark.asyncio
async def test_outcome_success_reflects_final_value():
    runner = ScriptRunner()
    res = await runner.handle_script("1 + 2")
    assert res.status == "success"
    outcome = runner.root_scope["outcome"]
    assert isinstance(outcome.status, PathLiteral)
    assert outcome.status == PathLiteral(GetPath([Name("ok")]))
    assert outcome.value == 3

@pytest.mark.asyncio
async def test_outcome_error_reflects_formatted_error():
    runner = ScriptRunner()
    res = await runner.handle_script("1 + 'a'")
    assert res.status == "error"
    outcome = runner.root_scope["outcome"]
    assert isinstance(outcome.status, PathLiteral)
    assert outcome.status == PathLiteral(GetPath([Name("err")]))
    assert isinstance(outcome.value, str)
    assert "TypeError:" in outcome.value
