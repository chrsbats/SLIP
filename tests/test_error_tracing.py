import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_runtime_type_error_infix_add_traces_and_stderr():
    runner = ScriptRunner(load_core=False)
    res = await runner.handle_script("+: |add; 1 + 'a'")
    assert res.status == 'err'
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
    # Exactly one stderr for this uncaught-exception flow
    assert len(stderr_effects) == 1, f"expected exactly one stderr side-effect, got: {stderr_effects}"
    assert msg in stderr_effects[-1]['message']

    # Host-facing ExecutionResult should NOT expose SLIP datatypes (Outcome/PathLiteral/etc.)
    outcome = getattr(res, "outcome", None)
    assert outcome is None

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
    assert res.status == 'err', res.error_message
    msg = res.error_message or ''


    print(msg)
    # Underlying exception and stacktrace
    assert ("ZeroDivisionError" in msg) or ("division" in msg.lower())
    assert "SLIP stacktrace" in msg

    # The error should include a location and the exact source line as written.
    assert "in line" in msg
    assert "boom: fn {x} [ x |div 0 ]" in msg

    # Stacktrace should show surface syntax (homoiconic form).
    assert "|div" in msg

@pytest.mark.asyncio
async def test_parse_error_emits_stderr():
    runner = ScriptRunner(load_core=False)
    # Space before ':' should fail to tokenize as a set-path
    res = await runner.handle_script("x : 1")
    assert res.status == 'err'
    assert res.error_message and "ParseError:" in res.error_message

    stderr_effects = [e for e in res.side_effects if e.get('topics') == ['stderr']]
    assert stderr_effects, f"stderr side effect missing: {res.side_effects}"
    # Side-effect message should be related to the parse failure
    assert stderr_effects[-1]['message'] != ""

@pytest.mark.asyncio
async def test_successful_script_sets_outcome_status_and_value():
    runner = ScriptRunner(load_core=False)
    res = await runner.handle_script("1")
    # Host-level status should be unified 'ok'
    assert res.status == 'ok'
    # Host-facing ExecutionResult should NOT expose SLIP datatypes (Outcome/PathLiteral/etc.)
    outcome = getattr(res, "outcome", None)
    assert outcome is None
    assert res.value == 1

@pytest.mark.asyncio
async def test_return_inside_script_remains_normal_success():
    runner = ScriptRunner(load_core=False)
    # A top-level `return` response should be unwrapped by the host and treated
    # as a normal successful run (no extra status leakage).
    res = await runner.handle_script("return 42")
    assert res.status == 'ok'
    assert res.value == 42
    # Host-facing ExecutionResult should NOT expose SLIP datatypes (Outcome/PathLiteral/etc.)
    outcome = getattr(res, "outcome", None)
    assert outcome is None
