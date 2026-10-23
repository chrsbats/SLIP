import functools

import pytest

from slip import ScriptRunner, SLIPHost
from slip.slip_runtime import slip_api_method


def assert_ok(res, expected=None):
    assert res.status == 'ok', f"expected success, got {res}"
    if expected is not None:
        assert res.value == expected, f"expected {expected!r}, got {res.value!r}"


class MyHost(SLIPHost):
    def __init__(self):
        super().__init__()
        self._data = {"hp": 100}

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]

    @slip_api_method
    def take_damage(self, amount: int):
        self._data["hp"] -= int(amount)
        return self._data["hp"]

    # Name chosen to collide with stdlib 'add' to test shadowing
    @slip_api_method
    def add(self, a, b):
        # Distinctive behavior to prove host method is called
        return int(a) + int(b) + 1000


@pytest.mark.asyncio
async def test_host_methods_exposed_as_kebab_case_and_callable():
    host = MyHost()
    runner = ScriptRunner(host_object=host)
    res = await runner.handle_script("take-damage 5")
    assert_ok(res, 95)
    # Ensure host state actually changed
    assert host["hp"] == 95


@pytest.mark.asyncio
async def test_host_methods_shadow_stdlib_and_local_overrides_host():
    host = MyHost()
    runner = ScriptRunner(host_object=host)
    # Host 'add' should shadow stdlib add
    res = await runner.handle_script("add 1 2")
    assert_ok(res, 1003)  # host add: 1 + 2 + 1000

    # A local binding should shadow the host binding within its lexical scope
    src = """
    f: fn {x, y} [
      add: fn {a, b} [ a - b ]
      add x y
    ]
    f 5 3
    """
    res2 = await runner.handle_script(src)
    assert_ok(res2, 2)


@pytest.mark.asyncio
async def test_host_object_gateway_returns_handle_and_allows_data_access():
    host = MyHost()
    runner = ScriptRunner(host_object=host)

    # Provide the gateway function explicitly (per spec 12.5)
    def host_object(object_id: str):
        return host if object_id == "main" else None

    runner.root_scope["host-object"] = host_object

    # Read via __getitem__
    res = await runner.handle_script("""
    obj: host-object 'main'
    obj.hp
    """)
    assert_ok(res, 100)

    # Write via __setitem__ and verify
    res2 = await runner.handle_script("""
    obj: host-object 'main'
    obj.hp: 80
    obj.hp
    """)
    assert_ok(res2, 80)
    assert host["hp"] == 80


@pytest.mark.asyncio
async def test_host_data_async_non_weakref_loader_is_called_once():
    class AsyncLoader:
        __slots__ = ("calls",)

        def __init__(self):
            self.calls = []

        async def __call__(self, object_id):
            self.calls.append(object_id)
            return {"id": object_id, "value": 11}

    loader = AsyncLoader()
    runner = ScriptRunner(host_data=loader)

    res = await runner.handle_script("data: host-data 'item-1'\ndata.value")

    assert_ok(res, 11)
    assert loader.calls == ["item-1"]


@pytest.mark.asyncio
async def test_equal_host_loaders_keep_their_own_call_behavior():
    class EqualPartial(functools.partial):
        def __hash__(self):
            return 1

        def __eq__(self, other):
            return isinstance(other, EqualPartial)

    async def async_loader(object_id):
        return {"id": object_id, "value": 1}

    def sync_loader(object_id):
        return {"id": object_id, "value": 2}

    async_callback = EqualPartial(async_loader)
    sync_callback = EqualPartial(sync_loader)
    assert async_callback == sync_callback

    async_runner = ScriptRunner(host_data=async_callback)
    sync_runner = ScriptRunner(host_data=sync_callback)

    async_result = await async_runner.handle_script(
        "data: host-data 'item-1'\ndata.value"
    )
    sync_result = await sync_runner.handle_script(
        "data: host-data 'item-1'\ndata.value"
    )

    assert_ok(async_result, 1)
    assert_ok(sync_result, 2)
