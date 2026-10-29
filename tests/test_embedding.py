"""The documented Python boundary, using only the independent interpreter."""

import sys
from collections.abc import MutableMapping

import pytest

from slip import ScriptRunner, SLIPHost, slip_api_method
from slip.slip_core import Path as SlipPath, PathLiteral, Scope
from slip.slip_embedding import ExecutionResult


def test_runner_preloads_definitions_and_reuses_live_values():
    with ScriptRunner() as runner:
        loaded = runner.handle_script("""
            count: 0
            increment: fn {amount} [count: 100; amount + 1]
            sum: fn {n} [total: 0; for {i} 0 n [total: + i]; total]
        """)
        assert isinstance(loaded, ExecutionResult)
        assert loaded.status == "ok", loaded.error_message
        for source, expected in (("increment 10", 11), ("increment 20", 21),
                                 ("sum 5", 10), ("count", 0)):
            result = runner.handle_script(source)
            assert result.status == "ok", result.error_message
            assert result.value == expected
        assert 'slip.slip_runtime' not in sys.modules
        assert 'slip.slip_interpreter' not in sys.modules


def test_results_capture_errors_returns_and_only_this_calls_effects():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            report: fn {value} [print value; value]
            report 7
        """)
        assert result.status == "ok", result.error_message
        assert result.value == result.slip_result == 7
        assert result.error is None and result.error_message is None
        assert result.side_effects == [{"topics": ["stdout"], "message": 7}]
        following = runner.handle_script("report 8")
        assert following.side_effects == [
            {"topics": ["stdout"], "message": 8},
        ]
        failed = runner.handle_script(
            "print 'before'; fail `invalid` #{message: 'bad request'}",
        )
        assert failed.status == "err"
        assert failed.value is None
        assert failed.error["kind"] == PathLiteral(SlipPath(["domain"]))
        assert failed.error_message == "bad request"
        assert failed.side_effects == [
            {"topics": ["stdout"], "message": "before"},
        ]
        runtime = runner.handle_script("missing-name")
        assert runtime.status == "err"
        assert "missing-name" in runtime.error_message
        syntax = runner.handle_script("[")
        assert syntax.status == "err" and syntax.error_message
        returned = runner.handle_script("return 12; missing-name")
        assert returned.status == "ok" and returned.value == 12
        sandbox = runner.handle_script("run [print 'sandbox'; 3]")
        assert sandbox.status == "ok" and sandbox.value == 3
        assert sandbox.side_effects == [
            {"topics": ["stdout"], "message": "sandbox"},
        ]


def test_calls_run_to_completion_and_keep_their_own_effects():
    events = []

    def checkpoint(name):
        events.append(name)
        return name

    with ScriptRunner() as runner:
        runner.root_scope["checkpoint"] = checkpoint
        loaded = runner.handle_script("""
            report: fn {label} [
                print label; checkpoint label; print label; label
            ]
        """)
        assert loaded.status == "ok", loaded.error_message
        for name in ("first", "second"):
            result = runner.handle_script(f"report '{name}'")
            assert result.status == "ok", result.error_message
            assert result.value == name
            assert result.side_effects == [
                {"topics": ["stdout"], "message": name},
                {"topics": ["stdout"], "message": name},
            ]
        assert events == ["first", "second"]


def test_marked_methods_are_original_callables_and_host_data_is_live():
    class CharacterHost(SLIPHost):
        def __init__(self):
            super().__init__()
            self.data = {"hp": 100}
            self.property_reads = 0
            self.closed = False

        def __getitem__(self, key):
            return self.data[key]

        def __setitem__(self, key, value):
            self.data[key] = value

        def __delitem__(self, key):
            del self.data[key]

        @property
        def unrelated(self):
            self.property_reads += 1
            raise AssertionError("Host registration read a property")

        @slip_api_method
        def take_damage(self, amount):
            self.data["hp"] -= amount
            return self.data["hp"]

        @slip_api_method
        def heal(self, amount):
            self.data["hp"] += amount
            return self.data["hp"]

        def private(self):
            raise AssertionError("Not marked")

        def close(self):
            self.closed = True

    host = CharacterHost()
    with ScriptRunner(host_object=host) as runner:
        runner.root_scope["obj"] = host
        exposed = runner.root_scope["take-damage"]
        assert exposed.__func__ is type(host).take_damage
        assert "private" not in runner.root_scope
        result = runner.handle_script("""
            hit: fn {amount} [take-damage amount]
            obj.hp: 80
            #[hit 3, heal 2, obj.hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [77, 79, 79]
        runner.root_scope["take-damage"] = lambda amount: -amount
        host.data["hp"] = 50
        result = runner.handle_script("hit 4")
        assert result.status == "ok", result.error_message
        assert result.value == 46
        deleted = runner.handle_script("~obj.hp")
        assert deleted.status == "ok" and host.data == {}
    assert host.property_reads == 0 and not host.closed


def test_host_gateway_is_exact_live_typed_and_leaves_storage_raw():
    raw = {
        "__slip__": {"type": "scope", "prototype": "Character"},
        "hp": 77,
        "inventory": [{"hp": 10}, {"hp": 90}],
    }
    lookups = []

    def load(object_id):
        lookups.append(object_id)
        return raw

    with ScriptRunner(host_data=load) as runner:
        assert runner.root_scope["host-data"] is load
        result = runner.handle_script("""
            Character: scope #{hp: 100}
            describe: fn {person: Character} ['typed']
            describe: fn {person} ['fallback']
            count-items: fn {items: `list`} [len items]
            p: host-object 'id:player-1'
            #[describe p, p.hp, type-of p.inventory = `list`,
              count-items p.inventory]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == ["typed", 77, True, 2]
        assert lookups == ["id:player-1"]
        raw["hp"] = 80
        result = runner.handle_script("""
            p.inventory[.hp < 50].hp: + 5
            p.hp: p.hp + 1
            #[p.hp, p.inventory.hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [81, [15, 90]]
        assert raw["hp"] == 81
        assert raw["inventory"] == [{"hp": 15}, {"hp": 90}]
        stored = runner.handle_script("host-data 'id:player-1'")
        assert stored.status == "ok" and stored.value is raw
        assert type(raw["inventory"]) is list
        assert raw["__slip__"] == {"type": "scope", "prototype": "Character"}
        assert "__slip__" not in runner.scope["p"]
        deleted = runner.handle_script("~p.inventory[.hp > 50]")
        assert deleted.status == "ok", deleted.error_message
        assert raw["inventory"] == [{"hp": 15}]


def test_rehydration_is_recursive_and_prototypes_are_runner_local():
    source = """
        as-slip #{
            people: #[#{
                '__slip__': #{type: 'scope', prototype: 'Visitor'},
                hp: 10
            }, #{
                '__slip__': #{type: 'scope', prototype: 'Visitor'},
                hp: 20
            }]
        }
    """
    with ScriptRunner() as first, ScriptRunner() as second:
        result = first.handle_script(source)
        assert result.status == "ok", result.error_message
        assert type(result.value) is dict
        assert type(result.value["people"]) is list
        one, two = result.value["people"]
        assert isinstance(one, Scope) and isinstance(two, Scope)
        assert one.parent is two.parent
        other = second.handle_script(source)
        assert other.status == "ok", other.error_message
        assert other.value["people"][0].parent is not one.parent
        failed = first.handle_script("""
            Invalid: 7
            as-slip #{'__slip__': #{type: 'scope', prototype: 'Invalid'}}
        """)
        assert failed.status == "err" and "prototype" in failed.error_message


def test_nested_typed_host_data_stays_live():
    child = {"__slip__": {"type": "scope", "prototype": "Child"}, "hp": 10}
    raw = {"children": [child]}

    def load(object_id):
        assert object_id == "id:parent"
        return raw

    with ScriptRunner(host_data=load) as runner:
        result = runner.handle_script("""
            data: host-object 'id:parent'
            data.children[0].hp: 20
            data.children[0]
        """)
        assert result.status == "ok", result.error_message
        assert isinstance(result.value, Scope) and child["hp"] == 20
        child["hp"] = 30
        assert result.value["hp"] == 30
        raw["children"] = [{
            "__slip__": {"type": "scope", "prototype": "Child"}, "hp": 50,
        }]
        replaced = runner.handle_script("data.children[0].hp")
        assert replaced.status == "ok" and replaced.value == 50


def test_raw_mappings_and_live_membership_do_not_snapshot_or_read():
    class Data(MutableMapping):
        def __init__(self):
            self.values = {"present": None}
            self.reads = []

        def __getitem__(self, key):
            self.reads.append(key)
            return self.values[key]

        def __setitem__(self, key, value):
            self.values[key] = value

        def __delitem__(self, key):
            del self.values[key]

        def __iter__(self):
            return iter(self.values)

        def __len__(self):
            return len(self.values)

        def __contains__(self, key):
            return key in self.values

        def __call__(self):
            raise AssertionError("Implicit snapshot")

    raw = Data()
    with ScriptRunner(host_data=lambda object_id: raw) as runner:
        stored = runner.handle_script("raw: host-data 'id:data'; raw")
        assert stored.status == "ok" and stored.value is raw
        result = runner.handle_script("""
            data: host-object 'id:data'
            #[raw != none, has raw 'present', has data 'present']
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [True, True, True]
        assert raw.reads == []


def test_runner_close_is_synchronous_idempotent_and_prevents_execution():
    runner = ScriptRunner()
    result = runner.handle_script("task [print 'must not run']")
    assert result.status == "err"
    assert "task is unsupported" in result.error_message
    assert result.side_effects == [
        {"topics": ["stderr"], "message": result.error_message},
    ]
    assert runner.close() is None
    assert runner.close() is None
    with pytest.raises(RuntimeError, match="closed"):
        runner.handle_script("1")
