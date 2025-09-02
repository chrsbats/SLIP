import pytest

from slip import ScriptRunner, SLIPHost
from slip.slip_runtime import slip_api_method


def assert_ok(res, expected=None):
    assert res.status == "success", f"expected success, got {res}"
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
