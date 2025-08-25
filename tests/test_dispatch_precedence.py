import pytest
from slip import ScriptRunner

@pytest.mark.asyncio
async def test_exact_arity_beats_variadic_after_partial():
    runner = ScriptRunner()
    src = """
inc: partial add 1
inc: fn {y} [ y + 1 ]
inc 10
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    assert res.value == 11

@pytest.mark.asyncio
async def test_compose_prefers_exact_over_variadic_after_partial():
    runner = ScriptRunner()

    # Prime the name with a variadic method via partial (rest param).
    res = await runner.handle_script("inc: partial add 1")
    assert res.status == 'success', res.error_message

    # Now define an exact-arity method later, and compose.
    script = """
double: fn {x} [ x * 2 ]
inc: fn {y} [ y + 1 ]
f: compose inc double
f 10
"""
    res = await runner.handle_script(script)
    # This should select the exact {y} method of inc during compose, returning 21.
    # If it fails, pytest will display res.error_message which includes the SLIP stacktrace
    # (look for 'all-args' and '(call add #[1])' to confirm the variadic path was taken).
    assert res.status == 'success', res.error_message
    assert res.value == 21

@pytest.mark.asyncio
async def test_foreach_chain_prefers_exact_over_variadic_after_partial():
    runner = ScriptRunner()

    # Seed with a variadic method via partial in a prior run (stateful across runs)
    res = await runner.handle_script("inc: partial add 1")
    assert res.status == 'success', res.error_message

    # Define an exact-arity one-arg method later and call through a foreach-driven chain (no compose)
    script = """
inc: fn {y} [ y + 1 ]

apply-each: fn {fs, x} [
    result: x
    foreach {f} fs [
        result: f result
    ]
    result
]

apply-each #[ inc ] 10
"""
    res = await runner.handle_script(script)
    # Expected: exact-arity inc should be selected, yielding 11.
    # Current bug: variadic (from partial) may win, causing "(call add #[1])" invalid-args.
    assert res.status == 'success', res.error_message
    assert res.value == 11
