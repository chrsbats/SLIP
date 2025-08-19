import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_runtime_type_error_infix_add_traces_and_stderr():
    runner = ScriptRunner(load_core=False)
    res = await runner.handle_script("+: |add; 1 + 'a'")
    assert res.status == 'error'
    msg = res.error_message or ''
    print(msg)
    # Basic runtime error signal
    assert "TypeError" in msg

    # Location and context
    assert "line 1" in msg
    assert "1 + 'a'" in msg
    assert "^" in msg

    # SLIP stacktrace present
    assert "SLIP stacktrace:" in msg

    # Consolidated stderr side-effect contains the formatted error
    stderr_effects = [e for e in res.side_effects if e.get('topics') == ['stderr']]
    assert stderr_effects, f"stderr side effect missing: {res.side_effects}"
    assert msg in stderr_effects[-1]['message']

@pytest.mark.asyncio
async def test_stacktrace_shows_function_chain_and_context():
    runner = ScriptRunner(load_core=False)
    script = """
boom: fn {x} [ x |div 0 ]
call-boom: fn {y} [ boom y ]
outer: fn {z} [ call-boom z ]
outer 5
"""
    res = await runner.handle_script(script)
    assert res.status == 'error', res.error_message
    msg = res.error_message or ''


    print(msg)
    # Underlying exception and stacktrace
    assert ("ZeroDivisionError" in msg) or ("division" in msg.lower())
    assert "SLIP stacktrace" in msg

    # Frames should include the operator and our function names
    assert "(div 5 0)" in msg
    assert "(boom 5)" in msg
    assert "(call-boom 5)" in msg
    assert "(outer 5)" in msg

    # Top-frame source context should include the failing source
    assert "x |div 0" in msg

@pytest.mark.asyncio
async def test_parse_error_emits_stderr():
    runner = ScriptRunner(load_core=False)
    # Space before ':' should fail to tokenize as a set-path
    res = await runner.handle_script("x : 1")
    assert res.status == 'error'
    assert res.error_message and "ParseError:" in res.error_message

    stderr_effects = [e for e in res.side_effects if e.get('topics') == ['stderr']]
    assert stderr_effects, f"stderr side effect missing: {res.side_effects}"
    # Side-effect message should be related to the parse failure
    assert stderr_effects[-1]['message'] != ""
