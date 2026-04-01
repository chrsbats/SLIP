import asyncio
import pytest

from slip import ScriptRunner
from slip.slip_runtime import SLIPHost, slip_api_method


def assert_ok(res, expected=None):
    assert res.status == "ok", (
        f"Expected success, got {res.status}: {res.error_message}"
    )
    if expected is not None:
        assert res.value == expected, f"Expected {expected!r}, got {res.value!r}"


def assert_error(res, contains: str | None = None):
    assert res.status == "err", (
        f"Expected error, got {res.status} with value {res.value!r}"
    )
    if contains:
        assert contains in (res.error_message or ""), (
            f"Expected error to contain {contains!r}, got: {res.error_message!r}"
        )


class MyHost(SLIPHost):
    def __init__(self):
        super().__init__()
        self._data = {"hp": 0}

    # Mapping contract for data access
    def __getitem__(self, key):
        if key.startswith("_"):
            raise KeyError("private")
        return self._data[key]

    def __setitem__(self, key, value):
        if key.startswith("_"):
            raise KeyError("private")
        self._data[key] = value

    def __delitem__(self, key):
        if key.startswith("_"):
            raise KeyError("private")
        del self._data[key]

    # Exposed API method (kebab-case: take-damage)
    @slip_api_method
    def take_damage(self, amount: int):
        self._data["hp"] -= amount

    # Not exposed (no decorator)
    def internal_calculation(self):
        return 42


@pytest.mark.asyncio
async def test_host_object_data_access_get_set_and_delete_raises_not_found():
    runner = ScriptRunner()
    host = MyHost()
    runner.root_scope["obj"] = host

    # Set then read (via mapping contract)
    res = await runner.handle_script("obj.hp: 80\nobj.hp")
    assert_ok(res, 80)

    # Delete then attempt to read -> PathNotFound
    res = await runner.handle_script("obj.tmp: 1\n~obj.tmp\nobj.tmp")
    assert_error(res, "PathNotFound: tmp")


@pytest.mark.asyncio
async def test_kebab_case_binding_to_decorated_method():
    runner = ScriptRunner()
    host = MyHost()
    host._data["hp"] = 10

    # Bind the bound Python method into the script scope using kebab-case
    runner.root_scope["obj"] = host
    runner.root_scope["take-damage"] = host.take_damage

    src = """
-- call exposed method and then read updated hp
take-damage 3
obj.hp
"""
    res = await runner.handle_script(src)
    assert_ok(res, 7)

    # A non-decorated method is not bound; calling it should fail to resolve
    res2 = await runner.handle_script("internal-calculation 0")
    assert_error(res2, "PathNotFound")


@pytest.mark.asyncio
async def test_host_object_gateway_function():
    runner = ScriptRunner()
    host = MyHost()

    REGISTRY = {"player-1": host}

    def host_object(object_id: str):
        return REGISTRY.get(object_id)

    # Bind gateway into scope under kebab-case name
    runner.root_scope["host-object"] = host_object

    src = """
obj: host-object "player-1"
obj.hp: 5
obj.hp
"""
    res = await runner.handle_script(src)
    assert_ok(res, 5)


@pytest.mark.asyncio
async def test_host_data_builtin_returns_raw_data_and_host_object_rehydrates():
    registry = {
        "player-1": {
            "__slip__": {"type": "scope", "prototype": "Character"},
            "hp": 7,
            "location": {"name": "Town"},
        }
    }

    def host_data(object_id: str):
        return registry.get(object_id)

    runner = ScriptRunner(host_data=host_data)

    res = await runner.handle_script("""
    Character: scope #{}
    raw: host-data "player-1"
    obj: host-object "player-1"
    #[
      eq (type-of raw) `dict`,
      eq (type-of obj) `scope`,
      obj.hp,
      eq (type-of obj.location) `dict`
    ]
    """)
    assert_ok(res, [True, True, 7, True])


@pytest.mark.asyncio
async def test_host_object_dispatches_and_preserves_identity_within_run():
    location = {
        "__slip__": {"type": "scope", "prototype": "Location"},
        "name": "Town",
    }
    person = {
        "__slip__": {"type": "scope", "prototype": "Person"},
        "name": "Karl",
        "location": location,
    }
    registry = {"person-1": person, "location-1": location}

    def host_data(object_id: str):
        return registry.get(object_id)

    runner = ScriptRunner(host_data=host_data)

    res = await runner.handle_script("""
    Person: scope #{}
    Location: scope #{}

    describe: fn {x: Person} [ "person" ]
    describe: fn {x: Location} [ "location" ]
    describe: fn {x} [ "other" ]

    p: host-object "person-1"
    l1: p.location
    l2: host-object "location-1"
    l1.name: "Harbor"

    #[ describe p, describe l1, l2.name ]
    """)
    assert_ok(res, ["person", "location", "Harbor"])


@pytest.mark.asyncio
async def test_cancel_tasks_via_exposed_method_zero_arity_call():
    runner = ScriptRunner()
    host = MyHost()

    # Create a couple of long-lived tasks and register them with the host
    async def dummy():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    t1 = asyncio.create_task(dummy())
    t2 = asyncio.create_task(dummy())
    host._register_task(t1)
    host._register_task(t2)

    # Expose the zero-arity cancel-tasks method as a top-level function
    runner.root_scope["cancel-tasks"] = host.cancel_tasks

    # Invoke from SLIP with no args; should return the number of canceled tasks
    res = await runner.handle_script("cancel-tasks")
    assert_ok(res, 2)

    # Ensure tasks are indeed canceled
    await asyncio.sleep(0)  # let cancellations propagate
    assert len(host.active_slip_tasks) == 0
