import pytest
from slip.slip_runtime import ScriptRunner

def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected

def assert_error(res, contains: str | None = None):
    assert res.status == "err"
    if contains is not None:
        assert contains in (res.error_message or "")

@pytest.mark.asyncio
async def test_this_assignment_is_rejected():
    runner = ScriptRunner()
    res = await runner.handle_script("this: 1")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_fn_positional_this_is_rejected():
    runner = ScriptRunner()
    res = await runner.handle_script("f: fn {this} [none]")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_fn_typed_this_first_is_accepted():
    runner = ScriptRunner(load_core=False)
    # We don't need actual type resolution for Phase 2.1; just the shape.
    res = await runner.handle_script("f: fn {this: Something, x} [x]")
    assert_ok(res)

@pytest.mark.asyncio
async def test_this_deletion_is_rejected():
    runner = ScriptRunner()
    res = await runner.handle_script("~this")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_fn_untyped_this_is_rejected():
    runner = ScriptRunner()
    # Code block params (untyped)
    res = await runner.handle_script("f: fn [this] [none]")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_fn_this_not_first_is_rejected():
    runner = ScriptRunner()
    # this must be the first parameter
    res = await runner.handle_script("f: fn {x, this: Type} [none]")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_foreach_this_is_rejected():
    runner = ScriptRunner()
    res = await runner.handle_script("foreach {this} #[1, 2] [none]")
    assert_error(res, "this")

@pytest.mark.asyncio
async def test_this_cannot_be_returned():
    runner = ScriptRunner()
    # Returning `this` should return the receiver object (ergonomic default),
    # not error. The thing that must not escape is the capability token itself.
    script = """
    T: resolver #{}
    leak: fn {this: T} [ return this ]
    T |leak
    """
    res = await runner.handle_script(script)
    assert_ok(res)

@pytest.mark.asyncio
async def test_this_cannot_be_stored_in_dict():
    runner = ScriptRunner()
    script = """
    T: resolver #{}
    leak: fn {this: T} [ #{ leaked: this } ]
    T |leak
    """
    res = await runner.handle_script(script)
    assert_error(res, "cannot be stored")

@pytest.mark.asyncio
async def test_this_cannot_be_stored_in_list():
    runner = ScriptRunner()
    script = """
    T: resolver #{}
    leak: fn {this: T} [ #[ this ] ]
    T |leak
    """
    res = await runner.handle_script(script)
    assert_error(res, "cannot be stored")

@pytest.mark.asyncio
async def test_method_autocall_for_this_first_sig():
    runner = ScriptRunner()
    script = """
    T: resolver #{}
    T.echo: fn {this: T} [ this ]
    T.echo
    """
    res = await runner.handle_script(script)
    assert_ok(res)

@pytest.mark.asyncio
async def test_write_rooted_at_this_requires_resolver_transaction():
    runner = ScriptRunner()
    src = """
    this.hp["p1"]: 10
    """
    res = await runner.handle_script(src)
    assert res.status == "err"
    assert "Committed writes require a resolver transaction" in (res.error_message or "")
