
def test_exact_arity_beats_variadic_after_partial(runner):
    src = """
inc: partial add 1
inc: fn {y} [ y + 1 ]
inc 10
"""
    res = runner.handle_script(src)
    assert res.status == 'ok', res.error_message
    assert res.value == 11


def test_compose_prefers_exact_over_variadic_after_partial(runner):

    # Prime the name with a variadic method via partial (rest param).
    res = runner.handle_script("inc: partial add 1")
    assert res.status == 'ok', res.error_message

    # Now define an exact-arity method later, and compose.
    script = """
double: fn {x} [ x * 2 ]
inc: fn {y} [ y + 1 ]
f: compose inc double
f 10
"""
    res = runner.handle_script(script)
    # Select the exact {y} method of inc during compose.
    assert res.status == 'ok', res.error_message
    assert res.value == 21


def test_foreach_chain_prefers_exact_over_variadic_after_partial(runner):

    # Seed a variadic method in a prior run.
    res = runner.handle_script("inc: partial add 1")
    assert res.status == 'ok', res.error_message

    # Select the later exact-arity method through a foreach-driven chain.
    script = """
inc: fn {y} [ y + 1 ]

apply-each: fn {fs, x} [
    result: x
    foreach {f} fs [
        result: f result
    ]
    result
]

apply-each #[core-function `inc`] 10
"""
    res = runner.handle_script(script)
    # Expected: exact-arity inc should be selected, yielding 11.
    assert res.status == 'ok', res.error_message
    assert res.value == 11
