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


# 4.1 Implicit Pipe Call: infix uses piped operators
@pytest.mark.asyncio
async def test_infix_addition_via_implicit_pipe():
    res = await run_slip("10 + 5")
    assert_ok(res, 15)

# 4.2 Left-to-right chaining for infix
@pytest.mark.asyncio
async def test_infix_left_to_right_chaining():
    res = await run_slip("10 + 5 * 2")
    assert_ok(res, 30)

# 4.6 Parentheses control order
@pytest.mark.asyncio
async def test_parentheses_override_left_to_right():
    res = await run_slip("10 + (5 * 2)")
    assert_ok(res, 20)

# 4.3 Explicit pipe: simple and unary piped call
@pytest.mark.asyncio
async def test_explicit_pipe_binary_and_unary_calls():
    # Binary call via explicit pipe
    res = await run_slip("10 |add 5")
    assert_ok(res, 15)

    # Unary piped call: lhs is fed as the single argument
    res = await run_slip("2 |exp")
    # exp(2) ~= 7.38905609893; allow float tolerance
    assert res.status == 'success'
    assert res.value == pytest.approx(7.38905609893, rel=1e-9)

# 4.7 Chained pipes (general functions)
@pytest.mark.asyncio
async def test_chained_explicit_pipes_with_arithmetic():
    # (10 |add 5) |mul 2 -> 30
    res = await run_slip("10 |add 5 |mul 2")
    assert_ok(res, 30)

# 4.2 Mix prefix call followed by a piped operator
@pytest.mark.asyncio
async def test_prefix_then_piped_operator_chain():
    res = await run_slip("add 10 5 |mul 3")
    assert_ok(res, 45)

# 4.4 Operator definitions: rebind '+' at root, then use it
@pytest.mark.asyncio
async def test_rebind_operator_alias_via_root_path():
    src = """
    /+: |sub
    10 + 2
    """
    res = await run_slip(src)
    assert_ok(res, 8)

# 4.5 No double pipe rule: cannot explicit-pipe an already piped alias
@pytest.mark.asyncio
async def test_explicit_pipe_on_piped_alias_errors():
    # 'and' is already an alias to a piped path in the core library.
    # Using '|and' should be rejected at runtime (double pipe).
    res = await run_slip("true |and false")
    assert_error(res)  # wording is runtime-defined; asserting error is sufficient

# Extra: unary piped op inside a chain
@pytest.mark.asyncio
async def test_unary_then_piped_chain():
    res = await run_slip("2 |exp |to-int")
    assert_ok(res, 7)
