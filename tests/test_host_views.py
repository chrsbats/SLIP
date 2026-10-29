"""Host boundary contracts clarified by the existing SLIP reference."""

from etcher import DB, RD, RL

from slip import ScriptRunner
from slip.slip_core import Scope


def test_gateway_views_are_fresh_but_share_live_data_and_prototype():
    raw = {"__slip__": {"type": "scope", "prototype": "Person"}, "hp": 10}
    with ScriptRunner(host_data=lambda object_id: raw) as runner:
        result = runner.handle_script("""
            a: host-object 'id:person'
            b: host-object 'id:person'
            #[a, b]
        """)
        assert result.status == "ok", result.error_message
        first, second = result.value
        assert first is not second and first != second
        assert first.parent is second.parent
        first["hp"] = 20
        assert second["hp"] == raw["hp"] == 20


def test_saved_mapping_element_and_slice_views_follow_replacements():
    original_child = {"hp": 10}
    original_items = [{"hp": 1}, {"hp": 2}]
    raw = {"child": original_child, "items": original_items}
    with ScriptRunner(host_data=lambda object_id: raw) as runner:
        result = runner.handle_script("""
            data: host-object 'id:parent'
            child: data.child
            entries: data.items
            entry: entries[0]
            selected: entries[0:1]
        """)
        assert result.status == "ok", result.error_message
        raw["child"] = {"hp": 20}
        raw["items"] = [{"hp": 30}, {"hp": 40}]
        result = runner.handle_script("""
            #[child.hp, entry.hp, entries.hp, selected[0].hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [20, 30, [30, 40], 30]
        result = runner.handle_script("""
            child.hp: + 1
            entry.hp: + 2
            ~entries[1].hp
            #[child.hp, entry.hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == [21, 32]
        assert raw == {"child": {"hp": 21}, "items": [{"hp": 32}, {}]}
        assert original_child == {"hp": 10}
        assert original_items == [{"hp": 1}, {"hp": 2}]


def test_saved_sequence_uses_replacement_for_native_mutations():
    original = [1, 2, 3]
    raw = {"items": original}
    with ScriptRunner(host_data=lambda object_id: raw) as runner:
        result = runner.handle_script(
            "data: host-object 'id:p'; data.items",
        )
        assert result.status == "ok", result.error_message
        sequence = result.value
        raw["items"] = [4, 5]
        sequence.insert(1, 9)
        sequence[1:2] = [7, 8]
        del sequence[0]
        assert sequence[:2] == [7, 8]
        assert raw["items"] == [7, 8, 5]
        assert original == [1, 2, 3]


def test_saved_scope_reads_current_fields_metadata_and_dispatch():
    raw = {"child": {
        "__slip__": {"type": "scope", "prototype": "Person"}, "hp": 10,
    }}
    with ScriptRunner(host_data=lambda object_id: raw) as runner:
        loaded = runner.handle_script("""
            Person: scope #{kind: 'person'}
            Monster: scope #{kind: 'monster'}
            describe: fn {value: Person} ['person']
            describe: fn {value: Monster} ['monster']
            any-scope: fn {value: `scope`} [true]
            data: host-object 'id:parent'
            saved: data.child
        """)
        assert loaded.status == "ok", loaded.error_message
        raw["child"] = {
            "__slip__": {"type": "scope", "prototype": "Monster"}, "hp": 20,
        }
        result = runner.handle_script("""
            saved.hp: + 1
            #[describe saved, saved.kind, saved.meta.parent = Monster,
              type-of saved = `scope`, any-scope saved, saved.hp]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == ["monster", "monster", True, True, True, 21]
        assert raw["child"]["hp"] == 21


def test_as_slip_preserves_plain_graph_sharing_and_cycles():
    child = {"n": 1}
    sequence = [child, child]
    sequence.append(sequence)
    raw = {"child": child, "items": sequence}
    raw["self"] = raw
    with ScriptRunner() as runner:
        runner.root_scope["raw"] = raw
        result = runner.handle_script("as-slip raw")
        assert result.status == "ok", result.error_message
        graph = result.value
        assert type(graph) is dict and type(graph["items"]) is list
        assert graph["self"] is graph
        assert graph["child"] is graph["items"][0] is graph["items"][1]
        assert graph["items"][2] is graph["items"]
        graph["child"]["n"] = 2
        assert child["n"] == 1
        again = runner.handle_script("as-slip raw")
        assert again.status == "ok", again.error_message
        assert again.value is not graph and again.value["child"]["n"] == 1


def test_as_slip_preserves_shared_cyclic_scopes():
    node = {"__slip__": {"type": "scope", "prototype": "Person"}, "hp": 10}
    node["self"] = node
    node["child"] = {"parent": node}
    raw = [node, node]
    with ScriptRunner() as runner:
        runner.root_scope["raw"] = raw
        result = runner.handle_script("as-slip raw")
        assert result.status == "ok", result.error_message
        first, second = result.value
        assert isinstance(first, Scope) and first is second
        assert first["self"] is first and first["child"]["parent"] is first
        assert "__slip__" not in first
        again = runner.handle_script("as-slip raw")
        assert again.status == "ok", again.error_message
        assert again.value[0] is not first
        assert again.value[0].parent is first.parent
        assert node["__slip__"] == {"type": "scope", "prototype": "Person"}


def test_persistent_graph_and_saved_views(tmp_path, monkeypatch):
    def snapshot(container):
        raise AssertionError("Unexpected persistent snapshot")

    monkeypatch.setattr(RD, "__call__", snapshot)
    monkeypatch.setattr(RL, "__call__", snapshot)
    db = DB(str(tmp_path / "host.db"))
    try:
        db["node"] = {
            "__slip__": {"type": "scope", "prototype": "Person"}, "hp": 10,
        }
        node = db["node"]
        node["self"] = node
        db["graph"] = {"first": node, "second": node, "items": [node, node]}
        sequence = db["graph"]["items"]
        sequence.append(sequence)
        db["current"] = {"child": node}
        with ScriptRunner(host_data=lambda key: db[key]) as runner:
            result = runner.handle_script("as-slip (host-data 'graph')")
            assert result.status == "ok", result.error_message
            first = result.value["first"]
            assert first is result.value["second"]
            assert first["self"] is first
            items = result.value["items"]
            assert items[0] is items[1] is first
            assert items[2] is items
            loaded = runner.handle_script("""
                data: host-object 'current'
                data.child
            """)
            assert loaded.status == "ok", loaded.error_message
            saved = loaded.value
            db["current"]["child"] = {
                "__slip__": {"type": "scope", "prototype": "Person"}, "hp": 20,
            }
            assert saved["hp"] == 20
            saved["hp"] = 25
            assert db["current"]["child"]["hp"] == 25
            assert node["hp"] == 10
    finally:
        db.shutdown()
