import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_status_on_plain_value_returns_ok_marker():
    runner = ScriptRunner()
    res = await runner.handle_script("status 1")
    assert res.status == 'ok'
    # SLIP value round-trips with backticks; host status is available via slip_status.
    assert res.value == "`ok`"
    assert res.slip_status == "`ok`"

@pytest.mark.asyncio
async def test_status_on_response_returns_response_status():
    runner = ScriptRunner()
    # Use the core-provided `err` literal via root.slip, so load_core must run.
    res = await runner.handle_script('status (response err "x")')
    assert res.status == 'ok'
    # SLIP value round-trips with backticks; host status is available via slip_status.
    assert res.value == "`err`"
    assert res.slip_status == "`ok`"
