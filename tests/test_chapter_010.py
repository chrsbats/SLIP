import pytest

from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected


def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


# Chapter 10: Metaprogramming and Evaluation Control

@pytest.mark.asyncio
async def test_run_executes_code_in_current_scope_and_returns_last_value():
    src = """
    -- 'run' should execute code in the current scope and return the last value
    res: run [
      x: 1
      x + 2
    ]
    #[ res, x ]
    """
    res = await run_slip(src)
    assert_ok(res, [3, 1])


@pytest.mark.asyncio
async def test_run_empty_returns_none():
    res = await run_slip("run []")
    assert_ok(res, None)


@pytest.mark.asyncio
async def test_run_with_executes_in_provided_scope():
    src = """
    s: scope #{}
    out: run-with [
      a: 10
      a * 2
    ] s
    -- 'a' should be set on s, not in the current scope
    #[ out, s.a ]
    """
    res = await run_slip(src)
    assert_ok(res, [20, 10])


@pytest.mark.asyncio
async def test_list_constructor_evaluates_block_items():
    src = """
    xs: list [
      1
      1 + 1
      3
    ]
    xs
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2, 3])


@pytest.mark.asyncio
async def test_dict_constructor_evaluates_block_assignments():
    src = """
    d: dict [
      a: 10
      b: 5 + 1
    ]
    #[ d.a, d.b ]
    """
    res = await run_slip(src)
    assert_ok(res, [10, 6])


@pytest.mark.asyncio
async def test_code_is_first_class_and_can_be_run_later():
    src = """
    c: [
      y: 5
      y + 7
    ]
    -- Code value is unevaluated until run
    t1: is-code? c
    v: run c
    #[ t1, v, y ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 12, 5])


@pytest.mark.asyncio
async def test_fn_closure_captures_lexical_scope():
    src = """
    make-adder: fn {n} [
      fn {x} [ x + n ]
    ]
    add-10: make-adder 10
    add-10 7
    """
    res = await run_slip(src)
    assert_ok(res, 17)


@pytest.mark.asyncio
async def test_inject_in_run_substitutes_value():
    src = """
    my-var: 10
    run [
      result: (add (inject my-var) 5)
      result
    ]
    """
    res = await run_slip(src)
    assert_error = None
    assert_ok(res, 15)


@pytest.mark.asyncio
async def test_splice_in_run_spreads_list_into_args():
    src = """
    my-list: #[2, 3]
    run [
      sum: (add (splice my-list))
      sum
    ]
    """
    res = await run_slip(src)
    assert_ok(res, 5)


@pytest.mark.asyncio
async def test_to_path_converts_string_to_path_literal():
    src = """
    p: to-path 'a.b'
    eq p `a.b`
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_to_path_normalizes_runtime_path_value_to_literal():
    src = """
    p: to-path `a.b`
    eq p `a.b`
    """
    res = await run_slip(src)
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_current_scope_returns_scope():
    res = await run_slip("is-scope? (current-scope)")
    assert_ok(res, True)


@pytest.mark.asyncio
async def test_current_scope_reflects_lexical_scope_not_run_with_target():
    src = """
    s: scope #{}
    run-with [ a: 1 ] s

    -- Count occurrences of 'a' key in keys(s) and keys(current-scope)
    in-s: len (filter (fn {k} [ eq k 'a' ]) (keys s))
    in-cur: len (filter (fn {k} [ eq k 'a' ]) (keys (current-scope)))

    #[ in-s, in-cur ]
    """
    res = await run_slip(src)
    assert_ok(res, [1, 0])

@pytest.mark.asyncio
async def test_join_string_variant_kept_for_lists_of_strings():
    src = """
    xs: #['x', 'y', 'z']
    join xs ', '
    """
    res = await run_slip(src)
    assert_ok(res, "x, y, z")

@pytest.mark.asyncio
async def test_join_path_variant_concatenates_segments():
    res = await run_slip("eq (join `a.b` `c`) `a.b.c`")
    assert_ok(res, True)

@pytest.mark.asyncio
async def test_join_path_variant_with_string_and_path_mixture():
    res = await run_slip("eq (join `a` `b.c`) `a.b.c`")
    assert_ok(res, True)
