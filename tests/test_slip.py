import pytest
import asyncio
import collections.abc
from unittest.mock import Mock, MagicMock

from slip.slip_runtime import SlipObject, SLIPModule, SLIPHost, StdLib
from slip.slip_datatypes import Scope, Code

# --- SlipObject Tests ---

def test_slip_object_is_dict():
    obj = SlipObject()
    assert isinstance(obj, collections.abc.MutableMapping)
    obj['a'] = 1
    assert obj['a'] == 1

def test_slip_object_hashing_and_equality():
    obj1 = SlipObject()
    obj2 = SlipObject()
    obj1_alias = obj1

    assert obj1 == obj1_alias
    print("1",obj1)
    print("2",obj2)
    assert obj1 != obj2
    assert hash(obj1) == hash(obj1_alias)


    assert hash(obj1) != hash(obj2)

    # Equality with regular dicts is still value-based
    obj1['a'] = 1
    assert obj1 == {'a': 1}


# --- SLIPModule Tests ---

def test_slip_module():
    env = Scope()
    env['a'] = 1
    mod = SLIPModule("test", env)
    assert repr(mod) == "<Module 'test' keys=['a']>"
    assert mod['a'] == 1


# --- SLIPHost Tests ---

class ConcreteHost(SLIPHost):
    def __getitem__(self, key): pass
    def __setitem__(self, key, value): pass
    def __delitem__(self, key): pass

@pytest.mark.asyncio
async def test_slip_host_task_management():
    host = ConcreteHost()
    
    async def dummy_coro():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy_coro())
    host._register_task(task)
    assert task in host.active_slip_tasks

    count = host.cancel_tasks()
    assert count == 1
    assert not host.active_slip_tasks
    await asyncio.sleep(0)  # Allow event loop to process cancellation
    assert task.cancelled()

    # Test that done callback removes task
    task2 = asyncio.create_task(dummy_coro())
    host._register_task(task2)
    await task2
    assert task2 not in host.active_slip_tasks


# --- StdLib Tests ---

@pytest.fixture
def mock_evaluator():
    evaluator = Mock()
    evaluator.side_effects = []
    evaluator.run = MagicMock()
    return evaluator

@pytest.fixture
def stdlib(mock_evaluator):
    return StdLib(mock_evaluator)

def test_stdlib_math(stdlib):
    assert stdlib._add(1, 2) == 3
    assert stdlib._mul(3, 4) == 12
    assert stdlib._eq(5, 5) is True
    assert stdlib._gt(10, 5) is True

def test_stdlib_string(stdlib):
    assert stdlib._join(['a', 'b'], '-') == "a-b"
    assert stdlib._replace("hello", "l", "w") == "hewwo"

def test_stdlib_list(stdlib):
    assert stdlib._slice_range([1,2,3,4], 1, 3) == [2,3]
    assert stdlib._len("abc") == 3

def test_stdlib_dict_env(stdlib):
    d = {'a': 1}
    env = Scope()
    env['b'] = 2
    
    assert stdlib._keys(d) == ['a']
    assert stdlib._values(d) == [1]
    assert stdlib._keys(env) == ['b']
    assert stdlib._values(env) == [2]

def test_stdlib_inherit(stdlib):
    parent = Scope()
    child = Scope()
    result = stdlib._inherit(child, parent)
    assert result is child
    assert child.parent is parent
    assert child.meta["parent"] is parent

@pytest.mark.asyncio
async def test_stdlib_async(stdlib):
    # Just test that it's awaitable and doesn't crash
    await stdlib._sleep(0)

def test_stdlib_emit(stdlib):
    stdlib._emit("topic", "message", "parts")
    assert len(stdlib.evaluator.side_effects) == 1
    event = stdlib.evaluator.side_effects[0]
    assert event['topics'] == ["topic"]
    assert event['message'] == "message parts"

def test_stdlib_list_constructor(stdlib, mock_evaluator):
    code = Code([1, 2])
    env = Scope()
    mock_evaluator.run.side_effect = [10, 20] # mock return values for each node
    
    result = stdlib._list(code, scope=env)
    
    assert result == [10, 20]
    assert mock_evaluator.run.call_count == 2
    mock_evaluator.run.assert_any_call(1, env)
    mock_evaluator.run.assert_any_call(2, env)

def test_stdlib_dict_constructor(stdlib, mock_evaluator):
    code = Code([('set', 'a', 1)])
    env = Scope()
    
    result = stdlib._dict(code, scope=env)
    
    assert isinstance(result, SlipObject)
    mock_evaluator.run.assert_called_once()
    # Check that it was called with a *new*, un-linked scope
    call_args = mock_evaluator.run.call_args
    assert call_args[0][0] == code.ast
    assert isinstance(call_args[0][1], Scope)
    assert call_args[0][1].parent is None

def test_stdlib_scope_constructor(stdlib):
    result = stdlib._scope({'a': 1})
    assert isinstance(result, Scope)
    assert result['a'] == 1
    with pytest.raises(ValueError):
        stdlib._scope({'meta': {}})
