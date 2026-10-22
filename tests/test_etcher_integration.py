import pytest

from etcher import DB, RD, RL

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


@pytest.mark.asyncio
async def test_etcher_host_data_and_host_object_work_with_rd_rl(tmp_path):
    db = DB(str(tmp_path / "state.db"))

    db["location-1"] = {
        "__slip__": {"type": "scope", "prototype": "Location"},
        "name": "Town",
    }
    db["person-1"] = {
        "__slip__": {"type": "scope", "prototype": "Person"},
        "name": "Karl",
        "location": db["location-1"],
        "tags": ["a", "b"],
    }

    runner = ScriptRunner(host_data=lambda object_id: db[object_id])

    res = await runner.handle_script("""
    Person: scope #{}
    Location: scope #{}

    describe: fn {x: Person} [ "person" ]
    describe: fn {x: Location} [ "location" ]
    describe: fn {x} [ "other" ]

    raw: host-data "person-1"
    person: host-object "person-1"
    place: host-object "location-1"

    person.location.name: "Harbor"

    #[
      eq (type-of raw) `dict`,
      eq (type-of raw.tags) `list`,
      raw.tags[0],
      describe person,
      describe person.location,
      place.name
    ]
    """)

    assert_ok(res, [True, True, "a", "person", "location", "Harbor"])


@pytest.mark.asyncio
async def test_foreach_over_empty_etcher_host_list_is_noop(tmp_path):
    db = DB(str(tmp_path / "state.db"))
    db["location-1"] = {
        "__slip__": {"type": "scope", "prototype": "Location"},
        "states": [],
    }

    runner = ScriptRunner(host_data=lambda object_id: db[object_id])

    res = await runner.handle_script("""
    Location: scope #{}
    location: host-object "location-1"
    seen: 0
    foreach {value} location.states [ seen: seen + 1 ]
    seen
    """)

    assert_ok(res, 0)


@pytest.fixture
def snapshot_calls(monkeypatch):
    calls = []

    def track(container_type):
        original = container_type.__call__

        def snapshot(container):
            calls.append(container.uid)
            return original(container)

        monkeypatch.setattr(container_type, '__call__', snapshot)

    track(RD)
    track(RL)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('source, expected', [
    ("sort (keys (host-data 'id:probe'))", ['child', 'count', 'id']),
    ("has (host-data 'id:probe') 'id'", True),
    ("len (host-data 'id:probe')", 3),
    ("len (values (host-data 'id:probe'))", 3),
    ("len (items (host-data 'id:probe'))", 3),
    ("len (host-data 'id:tags')", 2),
    ("type-of (host-data 'id:probe')", '`dict`'),
    ("type-of (host-data 'id:tags')", '`list`'),
    ("count: fn {data: `list`} [len data]; count (host-data 'id:tags')", 2),
    ("map (fn {tag} [tag]) (host-data 'id:tags')", ['a', 'b']),
    ("filter (fn {tag} [tag = 'a']) (host-data 'id:tags')", ['a']),
])
async def test_etcher_data_operations_do_not_snapshot(
    tmp_path, snapshot_calls, source, expected
):
    db = DB(str(tmp_path / 'state.db'))
    db['id:probe'] = {'id': 'id:probe', 'count': 1, 'child': {'hp': 10}}
    db['id:tags'] = ['a', 'b']
    objects = {key: db[key] for key in ('id:probe', 'id:tags')}
    runner = ScriptRunner(host_data=lambda object_id: objects[object_id])

    for _ in range(2):
        result = await runner.handle_script(source)
        assert_ok(result, expected)
    assert snapshot_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('object_id', ['id:probe', 'id:tags'])
async def test_host_function_receives_live_etcher_container(
    tmp_path, snapshot_calls, object_id
):
    db = DB(str(tmp_path / 'state.db'))
    db['id:probe'] = {'count': 1}
    db['id:tags'] = ['a', 'b']
    data = db[object_id]
    received = []

    def mutate(value):
        received.append(value)
        if object_id == 'id:probe':
            value['count'] += 1
        else:
            value.append('c')
        return True

    runner = ScriptRunner(host_data=lambda _object_id: data)
    runner.root_scope['mutate'] = mutate
    result = await runner.handle_script(f"mutate (host-data '{object_id}')")

    assert_ok(result, True)
    assert snapshot_calls == []
    assert received[0] is data
    if object_id == 'id:probe':
        assert db[object_id]['count'] == 2
    else:
        assert len(db[object_id]) == 3
        assert db[object_id][2] == 'c'


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [{'id': 'id:probe'}, ['a', 'b'], {}, []])
@pytest.mark.parametrize('expression, expected', [
    ('node != none', True),
    ('node = none', False),
    ('(node) != none', True),
    ('node = node', True),
    ('node |same', True),
    ('node |eq none', False),
    ('if [node != none] [same node] [false]', True),
])
async def test_etcher_expression_head_remains_data(
    tmp_path, snapshot_calls, value, expression, expected
):
    db = DB(str(tmp_path / 'state.db'))
    try:
        db['id:probe'] = value
        data = db['id:probe']
        runner = ScriptRunner(host_data=lambda _object_id: data)
        runner.root_scope['same'] = lambda item: item is data

        result = await runner.handle_script(
            f"node: host-data 'id:probe'; {expression}"
        )

        assert_ok(result, expected)
        assert runner.root_scope['node'] is data
        assert snapshot_calls == []
    finally:
        db.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [{'count': 1}, ['a', 'b']])
@pytest.mark.parametrize('source', [
    "call (host-data 'id:probe') #[]",
    "node: host-data 'id:probe'; call node #[]",
    "node: host-data 'id:probe'; call `node` #[]",
])
async def test_explicit_call_can_snapshot_etcher_data(
    tmp_path, snapshot_calls, value, source
):
    db = DB(str(tmp_path / 'state.db'))
    db['id:probe'] = value
    data = db['id:probe']
    runner = ScriptRunner(host_data=lambda _object_id: data)

    result = await runner.handle_script(source)

    assert_ok(result, value)
    assert type(result.slip_result) is type(value)
    assert snapshot_calls == [data.uid]
    if isinstance(value, dict):
        data['count'] = 2
        assert result.value['count'] == 1
    else:
        data.append('c')
        assert result.value == ['a', 'b']


@pytest.mark.asyncio
@pytest.mark.parametrize('gateway', ['host-data', 'host-object'])
@pytest.mark.parametrize('marked_scope', [False, True])
async def test_etcher_membership_does_not_read_member_values(
    tmp_path, monkeypatch, snapshot_calls, gateway, marked_scope
):
    db = DB(str(tmp_path / 'state.db'))
    try:
        value = {'present': True, 'falsey': False, 'nothing': None, 'child': {}}
        if marked_scope:
            value['__slip__'] = {'type': 'scope', 'prototype': 'Probe'}
        db['id:probe'] = value
        data = db['id:probe']
        member_reads = []
        original_getitem = RD.__getitem__
        member_keys = {'present', 'falsey', 'nothing', 'child', 'missing'}

        def read(container, key):
            if container.uid == data.uid and key in member_keys:
                member_reads.append(key)
            return original_getitem(container, key)

        monkeypatch.setattr(RD, '__getitem__', read)
        runner = ScriptRunner(host_data=lambda _object_id: data)
        result = await runner.handle_script(f"""
        node: {gateway} 'id:probe'
        #[
            has node 'present',
            has node 'falsey',
            has node 'nothing',
            has node 'child',
            has node 'missing',
            'present' in node,
            'falsey' in node,
            'nothing' in node,
            'child' in node,
            'missing' in node
        ]
        """)

        assert_ok(result, [
            True, True, True, True, False,
            True, True, True, True, False,
        ])
        assert member_reads == []
        assert snapshot_calls == []
    finally:
        db.shutdown()


@pytest.mark.asyncio
async def test_etcher_in_uses_rl_contains_protocol(
    tmp_path, snapshot_calls
):
    db = DB(str(tmp_path / 'state.db'))
    try:
        db['id:tags'] = ['a', 'b']
        data = db['id:tags']
        runner = ScriptRunner(host_data=lambda _object_id: data)

        result = await runner.handle_script("""
        tags: host-data 'id:tags'
        #['a' in tags, 'b' in tags, 'c' in tags]
        """)

        assert_ok(result, [True, True, False])
        assert snapshot_calls == [data.uid] * 3
    finally:
        db.shutdown()
