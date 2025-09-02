import pytest
from slip.slip_runtime import ScriptRunner

async def run_slip(src: str):
    runner = ScriptRunner(load_core=True)
    return await runner.handle_script(src)

def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
    if expected is not None:
        assert res.value == expected

def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got {res.status} with value {res.value!r}"
    if contains:
        msg = res.error_message or ""
        assert contains in msg, f"error message did not contain {contains!r}: {msg!r}"

# 1.1 Parsing and 1.2 Evaluation: flat parsing, left-to-right, grouping

@pytest.mark.asyncio
async def test_script_returns_last_expression_value():
    res = await run_slip("1\n2\n3")
    assert_ok(res, 3)

@pytest.mark.asyncio
async def test_prefix_call_and_infix_call_equivalence():
    res = await run_slip("add 10 5")
    assert_ok(res, 15)
    res = await run_slip("10 + 5")
    assert_ok(res, 15)

@pytest.mark.asyncio
async def test_left_to_right_and_parentheses_control_order():
    src = """
    result: 10 + 5 * 2
    result
    """
    res = await run_slip(src)
    assert_ok(res, 30)

    src = """
    result: 10 + (5 * 2)
    result
    """
    res = await run_slip(src)
    assert_ok(res, 20)

@pytest.mark.asyncio
async def test_group_evaluates_nested_expression_and_returns_value():
    src = """
    x: (add 2 3)
    x
    """
    res = await run_slip(src)
    assert_ok(res, 5)

@pytest.mark.asyncio
async def test_group_with_multiple_expressions_returns_last_value():
    src = """
    x: (a: 1; a + 2)
    x
    """
    res = await run_slip(src)
    assert_ok(res, 3)

@pytest.mark.asyncio
async def test_semicolon_separators_between_expressions():
    src = "a: 1; b: 2\nb"
    res = await run_slip(src)
    assert_ok(res, 2)

# 1.3 Container Literals and Evaluation

@pytest.mark.asyncio
async def test_code_block_is_unevaluated_until_run():
    src = """
    x: 1
    block: [ x: 2 ]
    -- still 1 because block not run
    x
    """
    res = await run_slip(src)
    assert_ok(res, 1)

    src = """
    x: 1
    block: [ x: 2 ]
    run block
    x
    """
    res = await run_slip(src)
    assert_ok(res, 1)

@pytest.mark.asyncio
async def test_code_block_type_is_code():
    src = """
    block: [ 1 ]
    eq (type-of block) `code`
    """
    res = await run_slip(src)
    assert_ok(res, True)

@pytest.mark.asyncio
async def test_list_and_dict_literals_construct_values():
    src = """
    xs: #[ 1, 2, 3 ]
    xs
    """
    res = await run_slip(src)
    assert_ok(res, [1, 2, 3])

    src = """
    d: #{ a: 1, b: 2 }
    d.a + d.b
    """
    res = await run_slip(src)
    assert_ok(res, 3)

# 1.2 Implicit pipe call (explicit piped-path in second position)

@pytest.mark.asyncio
async def test_explicit_pipe_operator_triggers_implicit_pipe_call():
    res = await run_slip("10 |add 5")
    assert_ok(res, 15)

# 1.4 Valid/Invalid Expression Forms

@pytest.mark.asyncio
async def test_del_path_cannot_participate_in_larger_expression():
    src = """
    a: 1
    ~a + 1
    """
    res = await run_slip(src)
    assert_error(res, "del-path cannot be part of a larger expression")

@pytest.mark.asyncio
async def test_piped_path_cannot_be_first_term_of_expression():
    # Using a piped-path as the first term should fail at runtime.
    src = "|add 1 2"
    res = await run_slip(src)
    # Error wording is standardized by the runtime; just assert failure.
    assert res.status == 'error'

@pytest.mark.asyncio
async def test_set_path_cannot_appear_mid_expression():
    # The evaluator should fail when a set-path appears where a normal value is expected.
    src = "10 + a: 20"
    res = await run_slip(src)
    # Error wording may vary; asserting error status is sufficient here.
    assert res.status == 'error'

@pytest.mark.asyncio
async def test_operator_alias_assignment_is_not_update():
    # Define a fresh alias and use it; should not attempt to read existing value of '+'
    src = """
    plus-op: |add
    10 plus-op 5
    """
    res = await run_slip(src)
    assert_ok(res, 15)
