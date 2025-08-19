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


@pytest.mark.asyncio
async def test_inherit_and_is_a_relationships():
    src = """
    Character: scope #{
        hp: 100,
        stamina: 100
    }
    Player: scope #{} |inherit Character

    -- Verify property lookup via prototype and is-a? checks
    #[ Player.stamina, is-a? Player Character, is-a? Character Player ]
    """
    res = await run_slip(src)
    assert_ok(res, [100, True, False])


@pytest.mark.asyncio
async def test_mixin_composes_capabilities_and_lookup_order():
    src = """
    Base: scope #{ a: 'parent', b: 'base' }
    Cap1: scope #{ a: 'mixin1', x: 'first' }
    Cap2: scope #{ a: 'mixin2', x: 'second', y: 'cap2' }

    obj: create Base
    mixin obj Cap1
    mixin obj Cap2

    -- Mixins are searched before parent; and earlier mixins win ties.
    -- Expect:
    --   obj.a -> from Cap1 ('mixin1') since mixins overshadow parent and Cap1 was added first
    --   obj.x -> from Cap1 ('first') due to insertion order precedence
    --   obj.b -> from Base parent
    #[ obj.a, obj.x, obj.b ]
    """
    res = await run_slip(src)
    assert_ok(res, ["mixin1", "first", "base"])


@pytest.mark.asyncio
async def test_create_overloads_and_configuration_block():
    src = """
    Character: scope #{}
    obj1: create
    obj2: create Character
    obj3: create Character [ name: "Kael" ]

    #[ is-scope? obj1, is-a? obj2 Character, obj3.name, is-a? obj3 Character ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, "Kael", True])


@pytest.mark.asyncio
async def test_schema_and_is_schema_predicate():
    src = """
    -- Define a schema. Use an empty dict to avoid resolving field type names.
    UserSchema: schema #{}

    #[ is-schema? UserSchema, is-a? UserSchema Schema, is-scope? UserSchema ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True])


@pytest.mark.asyncio
async def test_with_runs_block_and_returns_same_object():
    src = """
    obj: scope #{ a: 1 }
    res: obj |with [
        b: 2
    ]
    -- 'with' should return the same object; also verify the mutation
    #[ eq obj res, res.b ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, 2])


@pytest.mark.asyncio
async def test_is_a_false_for_non_scope_values():
    src = """
    -- Non-scope LHS yields false
    is-a? 5 Schema
    """
    res = await run_slip(src)
    assert_ok(res, False)


@pytest.mark.asyncio
async def test_mixin_avoids_duplicates_and_preserves_order():
    src = """
    A: scope #{ mark: 'A' }
    B: scope #{ mark: 'B' }

    o: create
    mixin o A
    mixin o A   -- duplicate should be ignored
    mixin o B

    -- Ensure only two mixins present and order is preserved (A, then B)
    #[ len o.meta.mixins, o.mark ]
    """
    res = await run_slip(src)
    assert_ok(res, [2, "A"])


@pytest.mark.asyncio
async def test_inherit_only_once_rule_errors_on_second_inherit():
    src = """
    Proto1: scope #{}
    Proto2: scope #{}
    o: create Proto1
    inherit o Proto2  -- should error (inherit can only be called once)
    """
    res = await run_slip(src)
    assert_error(res, "inherit can only be called once")
