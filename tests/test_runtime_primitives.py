import pytest

from slip import ScriptRunner


@pytest.mark.asyncio
async def test_if_with_code_variables_and_missing_else():
    runner = ScriptRunner()
    await runner._initialize()

    # else/then as variables pointing to code blocks
    res = await runner.handle_script("""
    then-block: [ 't' ]
    else-block: [ 'e' ]
    if [false] then-block else-block
    """)
    assert res.status == "success"
    assert res.value == "e"

    # Missing else returns none
    res2 = await runner.handle_script("if [false] [1]")
    assert res2.status == "success"
    assert res2.value is None


@pytest.mark.asyncio
async def test_foreach_over_mapping_keys_and_items():
    runner = ScriptRunner()
    await runner._initialize()

    # Single-var mapping iteration yields keys
    res = await runner.handle_script("""
    d: #{ a: 1, b: 2 }
    out: #[]
    foreach {k} d [ out: add out #[ k ] ]
    sort out
    """)
    assert res.status == "success"
    assert res.value == ["a", "b"]

    # Two-var mapping iteration yields pairs; pick value where key == 'a'
    res2 = await runner.handle_script("""
    d: #{ a: 1, b: 2 }
    sum: 0
    foreach {k, v} d [
      if [eq k 'a'] [
        sum: v
      ] [
        none
      ]
    ]
    sum
    """)
    assert res2.status == "success"
    assert res2.value == 1


@pytest.mark.asyncio
async def test_get_body_returns_code_for_typed_method():
    runner = ScriptRunner()
    await runner._initialize()

    res = await runner.handle_script("""
    add: fn {a: int, b: int} [ a + b ]
    body: get-body add {a: int, b: int}
    is-code? body
    """)
    assert res.status == "success"
    assert res.value is True


@pytest.mark.asyncio
async def test_test_and_test_all_helpers():
    runner = ScriptRunner()
    await runner._initialize()

    # One passing, one failing function
    res = await runner.handle_script("""
    good: fn {a, b} [ a + b ] |example { a: 2, b: 3 -> 5 }
    bad: fn {x} [ x + 1 ] |example { x: 2 -> 4 }
    #[ (eq (test good).status ok), (eq (test bad).status err) ]
    """)
    assert res.status == "success"
    assert res.value == [True, True]

    # test-all over current scope finds at least the two above
    res2 = await runner.handle_script("""
    out: test-all
    (out.value.passed >=  1) and ( out.value.passed + out.value.failed >= 1)
    """)
    assert res2.status == "success"
    assert res2.value is True


@pytest.mark.asyncio
async def test_channels_send_receive_and_task():
    runner = ScriptRunner()
    await runner._initialize()

    # Receive should await the task's send
    res = await runner.handle_script("""
    ch: make-channel
    task [ send ch 'hello' ]
    receive ch
    """)
    assert res.status == "success"
    assert res.value == "hello"


@pytest.mark.asyncio
async def test_run_with_accepts_zero_arity_callable_target_current_scope():
    runner = ScriptRunner()
    await runner._initialize()

    # Pass the zero-arity callable 'current-scope' as the target scope to run-with.
    res = await runner.handle_script("""
    run-with [ a: 123 ] current-scope
    a
    """)
    assert res.status == "success"
    assert res.value == 123  # 'a' bound into current scope by run-with


@pytest.mark.asyncio
async def test_get_body_missing_sig_errors_cleanly():
    runner = ScriptRunner()
    await runner._initialize()

    # Define a typed method, then request a mismatched signature body and expect an error
    res = await runner.handle_script("""
    add: fn {a: int, b: int} [ a + b ]
    probe: do [ get-body add {a: string, b: string} ]
    probe.outcome.status
    """)
    assert res.status == "success"
    # do should capture the PathNotFound and return outcome err
    # Either status is a path-literal `err` or an alias 'err' from core; compare via string for robustness
    from slip.slip_datatypes import PathLiteral, GetPath, Name
    status = res.value
    if isinstance(status, PathLiteral) and isinstance(status.inner, GetPath) and len(status.inner.segments) == 1 and isinstance(status.inner.segments[0], Name):
        assert status.inner.segments[0].text == "err"
    else:
        # In case the status is resolved to the alias value
        assert str(status).endswith("err")


@pytest.mark.asyncio
async def test_friendly_callable_name_prints_kebab_for_stdlib_method():
    runner = ScriptRunner()
    await runner._initialize()

    # Force an error while passing a StdLib method as an argument so the stacktrace prints it.
    # 'str-join' is a StdLib method exposed to SLIP; calling 'add 1 str-join' will error.
    res = await runner.handle_script("add 1 str-join")
    assert res.status == "error"
    # Ensure the stacktrace is present and shows 'str-join' (kebab-cased friendly name)
    em = res.error_message or ""
    assert "SLIP stacktrace:" in em
    assert "str-join" in em
