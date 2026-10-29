import pytest

from slip import ScriptRunner


@pytest.mark.asyncio
async def test_do_returns_direct_success_outcome():
    result = await ScriptRunner().handle_script("""
probe: do [ 10 + 20 ]
#[probe.status, probe.value, probe.error, probe.effects]
""")

    assert result.status == "ok", result.error_message
    assert result.value == ["`ok`", 30, None, []]


@pytest.mark.asyncio
async def test_do_captures_structured_failure():
    result = await ScriptRunner().handle_script("""
probe: do [
    fail `not-found` #{item-id: "item-1"}
]

#[
    probe.status,
    probe.value,
    probe.error.kind,
    probe.error.code,
    probe.error.data.item-id
]
""")

    assert result.status == "ok", result.error_message
    assert result.value == ["`err`", None, "`domain`", "`not-found`", "item-1"]


@pytest.mark.asyncio
async def test_do_captures_runtime_error_with_details():
    result = await ScriptRunner().handle_script("""
probe: do [ 1 / 0 ]
#[probe.status, probe.error.kind, probe.error.code, probe.error.message]
""")

    assert result.status == "ok", result.error_message
    assert result.value[:3] == ["`err`", "`runtime`", "`zero-division-error`"]
    assert "division by zero" in result.value[3]


@pytest.mark.asyncio
async def test_do_captures_only_inner_effects():
    result = await ScriptRunner().handle_script("""
print "before"
probe: do [
    print "inside"
    7
]
print "after"
#[probe.value, probe.effects[0].message]
""")

    assert result.status == "ok", result.error_message
    assert result.value == [7, "inside"]
    assert [effect["message"] for effect in result.side_effects] == [
        "before",
        "inside",
        "after",
    ]


@pytest.mark.asyncio
async def test_return_passes_through_do():
    result = await ScriptRunner().handle_script("""
f: fn {} [
    do [ return 7 ]
    99
]

f
""")

    assert result.status == "ok", result.error_message
    assert result.value == 7


@pytest.mark.asyncio
async def test_unhandled_failure_becomes_execution_error():
    result = await ScriptRunner().handle_script("""
fail `invalid` #{field: "name"}
""")

    assert result.status == "err"
    assert result.value is None
    assert result.error == {
        "kind": "domain",
        "code": "invalid",
        "message": "invalid",
        "data": {"field": "name"},
    }
