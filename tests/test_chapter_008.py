import pytest

from slip import ScriptRunner
from slip.slip_printer import Printer
from slip.slip_datatypes import PathLiteral


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


# Chapter 8: Advanced Features and Patterns
# 8.1 Transient Path Configuration with #(...)

@pytest.mark.asyncio
async def test_get_path_meta_block_is_ignored_on_read():
    src = """
    x: 42
    x#(timeout: 2)
    """
    res = await run_slip(src)
    assert_ok(res, 42)


@pytest.mark.asyncio
async def test_set_path_meta_block_is_ignored_on_write():
    src = """
    y: 0
    y#(note: 'tmp'): 123
    y
    """
    res = await run_slip(src)
    assert_ok(res, 123)


@pytest.mark.asyncio
async def test_del_path_meta_block_is_ignored_on_delete():
    src = """
    z: 7
    ~z#(soft-delete: true)
    z
    """
    res = await run_slip(src)
    assert_error(res, "PathNotFound: z")


@pytest.mark.asyncio
async def test_path_literal_with_meta_round_trips_via_printer():
    src = """
    `a#(flag: true)`
    """
    res = await run_slip(src)
    assert res.status == 'success'
    val = res.value
    assert isinstance(val, PathLiteral)
    # Ensure the meta attachment survives and pretty-prints back to the same shape
    pf = Printer().pformat
    assert pf(val) == "`a#(flag: true)`"


# 8.2 Example-Driven Development with |example
# Note: The chapter describes an |example helper. It is not currently present
# in the core library, so using it should produce a missing path error.

@pytest.mark.asyncio
async def test_example_helper_attaches_metadata():
    src = """
    f: fn {x} [ x ]
    f |example { x: 1 -> 1 }
    len f.meta.examples
    """
    res = await run_slip(src)
    assert_ok(res, 1)


@pytest.mark.asyncio
async def test_example_driven_synthesis_registers_typed_methods_and_dispatches():
    src = """
    -- One body with two examples should synthesize two typed methods
    add: fn {a, b} [
      a + b
    ] |example { a: 2,   b: 3   -> 5 }    -- {int, int}
      |example { a: 2.5, b: 3.5 -> 6.0 }  -- {float, float}

    #[ add 2 3, add 2.5 3.5 ]
    """
    res = await run_slip(src)
    assert_ok(res, [5, 6.0])

@pytest.mark.asyncio
async def test_local_scope_shadowing_of_functions_and_bindings():
    src = """
    -- Global binding
    f: fn {x} [ 'global' ]
    a: 1

    -- Define a function that creates local shadows
    g: fn {} [
      f: fn {x} [ 'local' ]  -- local definition shadows global 'f'
      a: 2                    -- local variable shadows global 'a'
      #[ f 10, a ]
    ]

    -- Outside, globals remain unchanged; inside, locals are used
    #[ f 1, a, g ]
    """
    res = await run_slip(src)
    # Expected:
    # - Outside: f 1 -> 'global', a -> 1
    # - Inside g: [ 'local', 2 ]
    assert_ok(res, ['global', 1, ['local', 2]])


@pytest.mark.asyncio
async def test_guarded_method_outranks_general_when_predicate_passes():
    src = """
    -- General method
    choose: fn {x} [ "general" ]
    -- Guarded method for x > 10
    choose: fn {x} [ "guarded" ] |guard [ x > 10 ]
    #[ choose 5, choose 15 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["general", "guarded"])


@pytest.mark.asyncio
async def test_guard_multiple_guards_all_must_pass():
    src = """
    choose: fn {x} [ "ok" ] |guard [ x > 0 ] |guard [ x < 10 ]
    choose: fn {x} [ "fallback" ]
    #[ choose -1, choose 5, choose 15 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["fallback", "ok", "fallback"])


@pytest.mark.asyncio
async def test_guard_uses_bound_keywords_and_rest():
    src = """
    compute: fn {a, b, rest...} [ "ok" ]
      |guard [ a = 1 ]
      |guard [ (len rest) > 0 ]
    compute: fn {a, b} [ "fallback" ]
    #[ compute 1 2, compute 1 2 3, compute 2 2 9 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["fallback", "ok", "fallback"])


@pytest.mark.asyncio
async def test_guard_preserved_across_example_synthesis_for_typed_clone():
    src = """
    -- Untyped body with example to synthesize {int,int}, plus guard
    add: fn {a, b} [ "guarded" ]
      |guard [ a > b ]
      |example { a: 2, b: 1 -> none }

    -- Explicit plain typed fallback for the same signature
    add: fn {a: `int`, b: `int`} [ "plain" ]

    #[ add 2 1, add 1 2 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["guarded", "plain"])


@pytest.mark.asyncio
async def test_guard_can_access_lexical_closure_vars():
    src = """
    y: 10
    f: fn {x} [ "gt" ] |guard [ x > y ]
    f: fn {x} [ "fallback" ]
    #[ f 20, f 5 ]
    """
    res = await run_slip(src)
    assert_ok(res, ["gt", "fallback"])


@pytest.mark.asyncio
async def test_guard_scoping_and_shadowing_local_generic_container():
    src = """
    -- Parent scope function
    choose: fn {x} [ "parent" ]

    -- Local shadowing with its own generic container and guards
    runner: fn {} [
      choose: fn {x} [ "local" ]
      choose: fn {x} [ "special" ] |guard [ x = 42 ]
      #[ choose 42, choose 1 ]
    ]

    #[ choose 42, runner ]
    """
    res = await run_slip(src)
    assert_ok(res, ["parent", ["special", "local"]])
