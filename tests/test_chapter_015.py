import pytest
from slip import ScriptRunner
from slip.slip_datatypes import Response, PathLiteral, GetPath, Name
from slip.slip_runtime import SlipObject


def assert_ok(res, expected=None):
    assert res.status == "ok", (
        f"expected success, got {res.status}: {res.error_message}"
    )
    if expected is not None:
        assert res.value == expected, f"expected {expected!r}, got {res.value!r}"


@pytest.mark.asyncio
async def test_effects_as_data_and_chronological_order():
    runner = ScriptRunner()
    src = """
emit "ui" "one"
emit #["a", "b"] "two"
42
"""
    res = await runner.handle_script(src)
    assert_ok(res, 42)
    # Side effects are returned as data in order
    assert [e["topics"] for e in res.side_effects] == [["ui"], ["a", "b"]]
    assert [e["message"] for e in res.side_effects] == ["one", "two"]


@pytest.mark.asyncio
async def test_pure_function_emits_effects_and_returns_response_ok_with_new_state():
    runner = ScriptRunner()
    src = """
-- Define a function that describes effects and returns a new state.
calculate-fireball-impact: fn {caster, target, area} [
    base-damage: 50
    final-damage: base-damage - target.fire-resistance

    -- Describe effects as data
    emit "visual" #{ effect: 'explosion', position: target.position }
    emit "sound"  #{ sound: 'fireball_hit.wav', volume: 1.0 }
    emit "combat" #{
        type:   `damage`,
        target: target.id,
        amount: final-damage,
        element: `fire`
    }

    -- Return new state (pure data) as an ok response
    new-target-state: clone target
    new-target-state.hp: target.hp - final-damage
    respond ok new-target-state
]

-- Inputs
caster: #{ name: "Mage" }
target: #{ id: 't1', hp: 100, fire-resistance: 10, position: #{ x: 1, y: 2 } }

-- Call the function; the script's final value is a Response object (not unwrapped).
calculate-fireball-impact caster target none
"""
    res = await runner.handle_script(src)
    assert res.status == "ok", res.error_message

    # Verify we got a normalized response back, and side effects are present and ordered
    resp = res.value
    assert isinstance(resp, dict), (
        f"expected host-normalized response dict, got {type(resp).__name__}"
    )
    assert resp.get("status") == "ok"

    # New target state should be a plain dict with updated hp (100 - (50 - 10) = 60)
    state = resp.get("value")
    assert isinstance(state, dict)
    assert state["hp"] == 60

    # Three effects in order with expected topics; structured messages remain native data.
    assert [e["topics"] for e in res.side_effects] == [
        ["visual"],
        ["sound"],
        ["combat"],
    ]
    assert res.side_effects[0]["message"] == {
        "effect": "explosion",
        "position": {"x": 1, "y": 2},
    }
    assert res.side_effects[1]["message"] == {
        "sound": "fireball_hit.wav",
        "volume": 1.0,
    }
    assert res.side_effects[2]["message"]["amount"] == 40


@pytest.mark.asyncio
async def test_emit_preserves_native_structured_message():
    runner = ScriptRunner()
    src = """
emit #[ 'self', 'others' ] #{
    msg_id: 'move.resolved'
    sentence: 'You move it.'
}
emit 'events' #[1, 2, #{ ok: true }]
none
"""
    res = await runner.handle_script(src)

    assert_ok(res, None)
    assert res.side_effects == [
        {
            "topics": ["self", "others"],
            "message": {
                "msg_id": "move.resolved",
                "sentence": "You move it.",
            },
        },
        {
            "topics": ["events"],
            "message": [1, 2, {"ok": True}],
        },
    ]


@pytest.mark.asyncio
async def test_emit_structured_message_interpolates_function_call():
    registry = {
        "item-1": {
            "__slip__": {"type": "scope", "prototype": "Item"},
            "id": "item-1",
            "name": "brass key",
        }
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    src = """
Item: scope #{}
display-name: fn {obj: Item} [ obj.name ]
obj: host-object 'item-1'

emit #[ 'self', 'others' ] #{
    msg_id: 'take.resolved'
    sentence: "You take {{display-name obj}}."
}
none
"""
    res = await runner.handle_script(src)

    assert_ok(res, None)
    assert res.side_effects == [
        {
            "topics": ["self", "others"],
            "message": {
                "msg_id": "take.resolved",
                "sentence": "You take brass key.",
            },
        }
    ]


@pytest.mark.asyncio
async def test_emit_structured_message_interpolates_lexical_variable():
    runner = ScriptRunner()
    src = """
x: 'Torch'
emit #[ 'self', 'others' ] #{
    msg_id: 'test'
    sentence: "You take {{x}}."
}
none
"""
    res = await runner.handle_script(src)

    assert_ok(res, None)
    assert res.side_effects == [
        {
            "topics": ["self", "others"],
            "message": {
                "msg_id": "test",
                "sentence": "You take Torch.",
            },
        }
    ]


@pytest.mark.asyncio
async def test_emit_structured_message_interpolates_host_object_display_name():
    registry = {
        "item-1": {
            "__slip__": {"type": "scope", "prototype": "Item"},
            "id": "item-1",
            "name": "Torch",
        }
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    src = """
Item: scope #{}
display-name: fn {obj} [
    if [(has-key? obj "name") and obj.name != ''] [ return obj.name ]
    if [(has-key? obj "description") and obj.description != ''] [ return obj.description ]
    return obj.id
]
obj: host-object "item-1"
emit #[ 'self', 'others' ] #{
    msg_id: 'test'
    sentence: "You take {{display-name obj}}."
}
none
"""
    res = await runner.handle_script(src)

    assert_ok(res, None)
    assert res.side_effects == [
        {
            "topics": ["self", "others"],
            "message": {
                "msg_id": "test",
                "sentence": "You take Torch.",
            },
        }
    ]


@pytest.mark.asyncio
async def test_emit_can_serialize_payload_with_format_argument():
    runner = ScriptRunner()
    src = """
emit "stdout" `json` #{ hp: 120, mana: 30 }
none
"""
    res = await runner.handle_script(src)
    assert_ok(res, None)
    assert [e["topics"] for e in res.side_effects] == [["stdout"]]
    assert [e["message"] for e in res.side_effects] == [
        '{\n  "hp": 120,\n  "mana": 30\n}'
    ]
