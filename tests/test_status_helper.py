import pytest

from slip import ScriptRunner


@pytest.mark.asyncio
async def test_do_success_exposes_ok_status():
    result = await ScriptRunner().handle_script("probe: do [1]\nprobe.status")

    assert result.status == "ok", result.error_message
    assert result.value == "`ok`"


@pytest.mark.asyncio
async def test_do_failure_exposes_err_status():
    result = await ScriptRunner().handle_script(
        'probe: do [fail "x"]\nprobe.status'
    )

    assert result.status == "ok", result.error_message
    assert result.value == "`err`"
