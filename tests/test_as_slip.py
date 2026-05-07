import pytest

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


def assert_error(res, contains: str | None = None):
    assert res.status == "err", f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or "")


@pytest.mark.asyncio
async def test_as_slip_leaves_plain_data_as_dicts_and_lists():
    runner = ScriptRunner()
    runner.root_scope["data"] = {"a": {"b": 1}, "xs": [1, {"c": 2}]}

    res = await runner.handle_script("""
    out: as-slip data
    #[ eq (type-of out) `dict`, out.a.b, out.xs[1].c ]
    """)

    assert_ok(res, [True, 1, 2])


@pytest.mark.asyncio
async def test_as_slip_rehydrates_scope_and_nested_scope():
    runner = ScriptRunner()
    runner.root_scope["data"] = {
        "__slip__": {"type": "scope"},
        "hp": 10,
        "child": {
            "__slip__": {"type": "scope"},
            "name": "Karl",
        },
    }

    res = await runner.handle_script("""
    obj: as-slip data
    #[
      eq (type-of obj) `scope`,
      obj.hp,
      eq (type-of obj.child) `scope`,
      obj.child.name
    ]
    """)

    assert_ok(res, [True, 10, True, "Karl"])


@pytest.mark.asyncio
async def test_as_slip_rehydrated_scope_participates_in_dispatch_from_host_object():
    runner = ScriptRunner()

    REGISTRY = {
        "player-1": {
            "__slip__": {"type": "scope", "prototype": "Character"},
            "hp": 77,
        }
    }

    def host_object(object_id: str):
        return REGISTRY.get(object_id)

    runner.root_scope["host-object"] = host_object

    res = await runner.handle_script("""
    Character: scope #{}
    describe: fn {x: Character} [ "typed" ]
    describe: fn {x} [ "fallback" ]

    obj: as-slip (host-object "player-1")
    #[ describe obj, obj.hp ]
    """)

    assert_ok(res, ["typed", 77])


@pytest.mark.asyncio
async def test_as_slip_auto_creates_missing_prototype_and_dispatches():
    runner = ScriptRunner()
    runner.root_scope["data"] = {
        "__slip__": {"type": "scope", "prototype": "MissingType"},
        "hp": 10,
    }

    res = await runner.handle_script("""
    describe: fn {x: MissingType} [ "typed" ]
    describe: fn {x} [ "fallback" ]

    obj: as-slip data
    #[ describe obj, obj.hp, is-a? obj MissingType ]
    """)

    assert_ok(res, ["typed", 10, True])


@pytest.mark.asyncio
async def test_as_slip_reuses_generated_prototype_within_runner():
    runner = ScriptRunner()
    runner.root_scope["a"] = {
        "__slip__": {"type": "scope", "prototype": "Ghost"},
        "hp": 1,
    }
    runner.root_scope["b"] = {
        "__slip__": {"type": "scope", "prototype": "Ghost"},
        "hp": 2,
    }

    res = await runner.handle_script("""
    a1: as-slip a
    b1: as-slip b
    #[ is-a? a1 Ghost, is-a? b1 Ghost, eq a1.meta.parent b1.meta.parent ]
    """)

    assert_ok(res, [True, True, True])


@pytest.mark.asyncio
async def test_as_slip_prefers_existing_local_prototype():
    runner = ScriptRunner()
    runner.root_scope["data"] = {
        "__slip__": {"type": "scope", "prototype": "Character"},
        "hp": 10,
    }

    res = await runner.handle_script("""
    Character: scope #{ kind: "local" }
    obj: as-slip data
    #[ is-a? obj Character, obj.kind, obj.hp ]
    """)

    assert_ok(res, [True, "local", 10])


@pytest.mark.asyncio
async def test_as_slip_errors_if_existing_prototype_name_is_not_scope():
    runner = ScriptRunner()
    runner.root_scope["MissingType"] = 123
    runner.root_scope["data"] = {
        "__slip__": {"type": "scope", "prototype": "MissingType"},
        "hp": 10,
    }

    res = await runner.handle_script("as-slip data")

    assert_error(res, "invalid-args in (as-slip)")
