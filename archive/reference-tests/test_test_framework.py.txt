import pytest

from slip import ScriptRunner


@pytest.mark.asyncio
async def test_example_inline_and_test_single_function_passes():
    result = await ScriptRunner().handle_script("""
add: fn {x, y} [ x + y ] |example {x: 2, y: 3 -> 5}
test add
""")

    assert result.status == "ok", result.error_message
    assert result.value == 1


@pytest.mark.asyncio
async def test_example_failure_is_structured():
    result = await ScriptRunner().handle_script("""
x: 2
y: 3
want: 4
add: fn {x, y} [ x + y ]
add |example {x, y -> want}
test add
""")

    assert result.status == "err"
    assert result.error["code"] == "test-failed"
    failure = result.error["data"][0]
    assert failure == {"index": 0, "expected": 4, "actual": 5}


@pytest.mark.asyncio
async def test_test_all_scans_given_scope_and_succeeds():
    result = await ScriptRunner().handle_script("""
mod: scope #{}
run-with [
    add: fn {x, y} [ x + y ] |example {x: 1, y: 2 -> 3}
    mul: fn {x, y} [ x * y ] |example {x: 2, y: 3 -> 6}
] mod
test-all mod
""")

    assert result.status == "ok", result.error_message
    assert result.value["with-examples"] == 2
    assert result.value["failed"] == 0
    assert result.value["passed"] == 2
    assert result.value["details"] == []


@pytest.mark.asyncio
async def test_test_all_failure_is_structured():
    result = await ScriptRunner().handle_script("""
mod: scope #{}
run-with [
    f: fn {x} [ x + 1 ]
    f |example {x: 1 -> 2}
    f |example {x: 1 -> 3}
] mod
test-all mod
""")

    assert result.status == "err"
    assert result.error["code"] == "test-failed"
    summary = result.error["data"]
    assert summary["with-examples"] == 1
    assert summary["failed"] == 1
    assert summary["details"][0]["name"] == "f"


@pytest.mark.asyncio
async def test_generic_aggregation_counts_all_examples():
    result = await ScriptRunner().handle_script("""
g: fn {x} [ x ] |example {x: 1 -> 1}
g: fn {x, y} [ x + y ]
g |example {x: 2, y: 3 -> 5}
test g
""")

    assert result.status == "ok", result.error_message
    assert result.value == 2


@pytest.mark.asyncio
async def test_test_records_errors_from_example_execution():
    result = await ScriptRunner().handle_script("""
div-fn: fn {x, y} [ x / y ]
div-fn |example {x: 1, y: 0 -> none}
test div-fn
""")

    assert result.status == "err"
    failure = result.error["data"][0]
    assert "division" in failure["err"].lower()


@pytest.mark.asyncio
async def test_chain_multiple_examples_and_count():
    result = await ScriptRunner().handle_script("""
h: fn {x} [ x + 1 ] |example {x: 1 -> 2} |example {x: 2 -> 3}
test h
""")

    assert result.status == "ok", result.error_message
    assert result.value == 2


@pytest.mark.asyncio
async def test_example_with_positional_names_without_keywords():
    result = await ScriptRunner().handle_script("""
a: 10
b: 32
want: 42
sum: fn {x, y} [ x + y ]
sum |example {x, y -> want}
test sum
""")

    assert result.status == "ok", result.error_message
    assert result.value == 1
