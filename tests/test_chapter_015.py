import pytest
from slip import ScriptRunner
from slip.slip_datatypes import Response, GetPathLiteral, Name
from slip.slip_runtime import SlipObject


def assert_ok(res, expected=None):
    assert res.status == 'success', f"expected success, got {res.status}: {res.error_message}"
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
    assert res.status == 'success', res.error_message

    # Verify we got a Response(ok, <state>) back, and side effects are present and ordered
    resp = res.value
    assert isinstance(resp, Response), f"expected Response, got {type(resp).__name__}"
    assert resp.status == GetPathLiteral([Name("ok")])

    # New target state should be a SlipObject with updated hp (100 - (50 - 10) = 60)
    state = resp.value
    assert isinstance(state, SlipObject)
    assert state["hp"] == 60

    # Three effects in order with expected topics; messages are strings (pretty-printed for dicts)
    assert [e["topics"] for e in res.side_effects] == [["visual"], ["sound"], ["combat"]]
    assert all(isinstance(e["message"], str) for e in res.side_effects)
    # Combat effect message should mention the damage amount 40
    assert any("40" in (e["message"] or "") and e["topics"] == ["combat"] for e in res.side_effects)
