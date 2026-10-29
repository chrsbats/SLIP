"""Prototype configuration and function utilities from the language docs."""

import pytest

from slip.slip_core import Scope, execute, invoke
from slip.slip_library import SOURCE, get_sig, library_scope, sig
from slip.slip_syntax import parse


def test_configuration_separates_language_and_object_lookups():
    scope = Scope(parent=library_scope())
    execute(parse("""
        Character: scope #{hp: 100}
        Player: scope #{} |inherit Character
        p: create Player [hp: hp + 20; roll: random-int 7 7; print hp]
    """), scope)
    player = scope["p"]
    assert player["hp"] == 120
    assert player["roll"] == 7
    assert player.parent is scope["Player"]
    assert scope["Character"]["hp"] == 100
    assert set(player) == {"hp", "roll"}
    assert "random-int" not in player and "+" not in player
    assert scope.effects == [{"topics": ["stdout"], "message": 120}]


def test_configured_methods_keep_live_fields_and_shadow_prototypes():
    scope = Scope(parent=library_scope())
    execute(parse("""
        Prototype: scope #{}
        Prototype.read: fn {offset} [offset]
        p: create Prototype [hp: 10; read: fn {offset} [hp + offset]]
        p.hp: 20
    """), scope)
    assert invoke(scope["p"]["read"], [2], scope) == 22
    assert invoke(scope["Prototype"]["read"], [2], scope) == 2
    assert len(scope["Prototype"]["read"].methods) == 1


def test_detached_signatures_copy_records_but_keep_prototype_identity():
    scope = Scope(parent=library_scope())
    execute(parse("""
        Character: scope #{}
        describe: fn {person: Character} ['typed']
        adapter: fn (sig (get-sig describe)) ['adapted']
        p: create Character
    """), scope)
    description = get_sig(scope["describe"])
    copied = sig(description)
    original = scope["describe"].methods[0].sig
    assert description.parameters[0] is not original.parameters[0]
    assert copied.parameters[0] is not description.parameters[0]
    assert copied.parameters[0].annotation is scope["Character"]
    copied.parameters[0].name = "other"
    assert original.parameters[0].name == "person"
    assert invoke(scope["adapter"], [scope["p"]], scope) == "adapted"
    with pytest.raises(TypeError, match="No matching method"):
        invoke(scope["adapter"], [{}], scope)


def test_partial_is_reusable_and_retains_bound_value_identity():
    scope = Scope(parent=library_scope())
    execute(parse(SOURCE), scope.root)
    seen = []
    state = {"total": 0}

    def collect(target, amount):
        seen.append(target)
        target["total"] += amount
        return target["total"]

    scope["state"], scope["collect"] = state, collect
    assert execute(parse("""
        accumulate: partial collect state
        #[accumulate 2, accumulate 3]
    """), scope) == [2, 5]
    assert seen[0] is state and seen[1] is state
    assert invoke(scope["accumulate"], [4], scope) == 9


def test_composition_calls_from_right_to_left_in_the_calling_scope():
    scope = Scope(parent=library_scope())
    execute(parse(SOURCE), scope.root)
    assert execute(parse("""
        double: fn {value} [value * 2]
        increment: partial core-add 1
        pipeline: compose double increment
        #[pipeline 3, pipeline 5]
    """), scope) == [8, 12]
