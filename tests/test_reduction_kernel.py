import asyncio

import pytest

from slip import ScriptRunner
from slip.slip_datatypes import Code, IString, ReturnSignal, Scope
from slip.slip_interpreter import Evaluator


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    [1, 2], {"a": 1}, Code([[7]]), IString("{{missing}}"),
])
async def test_control_result_keeps_value_identity(value):
    runner = ScriptRunner()
    runner.root_scope["original"] = value
    runner.root_scope["same-object"] = lambda actual: actual is value

    result = await runner.handle_script("if [true] [original] |same-object")

    assert result.status == "ok", result.error_message
    assert result.value is True


@pytest.mark.asyncio
async def test_rendered_control_result_is_not_interpolated_again():
    result = await ScriptRunner().handle_script("""
text: '{{missing}}'
if [true] ["{{text}}"] |len
""")

    assert result.status == "ok", result.error_message
    assert result.value == 11


@pytest.mark.asyncio
async def test_coroutine_stored_as_data_is_not_implicitly_awaited():
    calls = []

    async def stored_value():
        calls.append("awaited")
        return 7

    value = stored_value()
    try:
        runner = ScriptRunner()
        runner.root_scope["stored"] = value

        result = await runner.handle_script("stored")

        assert result.status == "ok", result.error_message
        assert result.slip_result is value
        assert calls == []
        assert await value == 7
    finally:
        value.close()


@pytest.mark.asyncio
async def test_native_awaitable_result_and_task_handle():
    calls = []

    class AwaitableNumber(int):
        def __await__(self):
            async def compute():
                calls.append("awaited")
                return int(self) + 1
            return compute().__await__()

    evaluator = Evaluator()
    scope = Scope()
    assert await evaluator.call(lambda: AwaitableNumber(6), [], scope) == 7
    assert calls == ["awaited"]

    async def compute():
        return 9

    handle = await evaluator.call(
        lambda: asyncio.create_task(compute()), [], scope,
    )
    assert isinstance(handle, asyncio.Task)
    assert await handle == 9


@pytest.mark.asyncio
async def test_public_call_preserves_return_argument_list():
    signal = ReturnSignal(7)
    arguments = [signal]

    result = await Evaluator().call(lambda value: value, arguments, Scope())

    assert result == 7
    assert arguments == [signal]
    assert arguments[0] is signal


@pytest.mark.asyncio
async def test_return_in_group_and_control_block_stops_remaining_statements():
    result = await ScriptRunner().handle_script("""
f: fn {} [
    if [true] [(return 7); emit 'unexpected' 'branch']
    emit 'unexpected' 'function'
    99
]
f
""")

    assert result.status == "ok", result.error_message
    assert result.value == 7
    assert result.side_effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", [
    "if [true] [return 7] |core-add 1",
    "(return 7) |core-add 1",
    "1 + (return 7)",
    "1 |core-add (return 7)",
    "core-add 1 (return 7)",
    "core-add (return 7) (emit 'unexpected' 'argument')",
])
async def test_return_stops_the_remaining_reduction(expression):
    runner = ScriptRunner()
    result = await runner.handle_script(f"""
f: fn {{}} [
    {expression}
    emit 'unexpected' 'continued'
    99
]
f
""")

    assert result.status == "ok", result.error_message
    assert result.value == 7
    assert result.side_effects == []
