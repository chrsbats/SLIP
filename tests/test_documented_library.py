import pytest

from slip.slip_core import Scope, execute
from slip.slip_library import SOURCE, library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize(("source", "expected"), [
    ("seen: #[]; for {i} 0 3 [seen: add seen i]; seen", [0, 1, 2]),
    ("seen: #[]; for {i} 3 0 [seen: add seen i]; seen", [3, 2, 1]),
    ("f: fn {} [seen: #[]; for {i} 0 3 [seen: add seen i]; seen]; f",
     [0, 1, 2]),
    ("total: 0; foreach {x} #[1, 2, 3] [total: + x]; total", 6),
    ("seen: #[]; foreach {k, v} #{a: 1, b: 2} [seen: add seen v]; seen",
     [1, 2]),
    ("when [true] [10 + 20]", 30),
    ("#[1, 2, 3] |map (fn {x} [x + 1])", [2, 3, 4]),
    ("filter (fn {x} [x > 1]) #[1, 2, 3]", [2, 3]),
    ("reduce add 0 #[1, 2, 3]", 6),
    ("#[range 3, range 1 4, range 1 5 2]", [[0, 1, 2], [1, 2, 3], [1, 3]]),
    ("data: #{name: none}; #[has data 'name', 'name' in data]", [True, True]),
    ("p: create; p |with [hp: 150]; p.hp", 150),
    ("Character: scope #{hp: 100}; Player: scope #{} |inherit Character; "
     "p: create Player; #[p.hp, is-a p Character]", [100, True]),
    ("Character: scope #{hp: 100}; Player: scope #{} |inherit Character; "
     "heal: fn {p: Player, amount} [p.hp: p.hp + (amount * 2)]; "
     "p: create Player; p |heal 10", 120),
    ("s: scope #{}; out: run-with [a: 10; a * 2] s; #[out, s.a]", [20, 10]),
    ("s: scope #{}; here: current-scope; "
     "out: run-with [current-scope] s; out = here", True),
    ("#[type-of 'x', type-of \"x\"] = #[`string`, `i-string`]", True),
    ("f: fn {x} [x]; description: get-sig f; "
     "description.parameters[0].type: `string`; "
     "g: fn (sig description) [x]; g 'hi'", "hi"),
    ("list [1; 1 + 1; 3]", [1, 2, 3]),
    ("dict [a: 10; b: 5 + 1]", {"a": 10, "b": 6}),
    ("seed-random 42; first: random; seed-random 42; first = (random)", True),
    ("join #['a', 'b', 'c'] ', '", "a, b, c"),
    ("split 'a,b,c' ','", ["a", "b", "c"]),
])
def test_documented_library(source, expected):
    scope = Scope(parent=library_scope())
    execute(parse(SOURCE), scope.root)
    assert execute(parse(source), scope) == expected


@pytest.mark.parametrize("source", [
    "task [emit 'audit' 'must not run'; 7]", "sleep 0", "sleep 1000000",
])
def test_task_and_sleep_are_explicitly_deferred(source):
    scope = Scope(parent=library_scope())
    with pytest.raises(NotImplementedError, match="unsupported.*synchronous"):
        execute(parse(source), scope)
    assert scope.effects == []


def test_random_streams_are_runner_local():
    first = Scope(parent=library_scope())
    second = Scope(parent=library_scope())
    execute(parse("seed-random 42"), first)
    expected = execute(parse("random"), first)
    execute(parse("seed-random 42"), first)
    execute(parse("seed-random 99; random; random"), second)
    assert execute(parse("random"), first) == expected
