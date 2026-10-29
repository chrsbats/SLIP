"""Live containers and explicit snapshots from Etcher integration tests."""

import pytest
from etcher import DB, RD, RL

from slip.slip_core import Path, PathLiteral
from slip import ScriptRunner


@pytest.fixture
def store(tmp_path):
    db = DB(str(tmp_path / 'state.db'))
    try:
        yield db
    finally:
        db.shutdown()


@pytest.fixture
def snapshots(monkeypatch):
    calls = []
    for cls in (RD, RL):
        original = cls.__call__

        def snapshot(value, original=original):
            calls.append(value.uid)
            return original(value)

        monkeypatch.setattr(cls, '__call__', snapshot)
    return calls


@pytest.mark.parametrize(('source', 'expected'), [
    ("sort (keys (host-data 'probe'))", ['child', 'count', 'id']),
    ("has (host-data 'probe') 'id'", True),
    ("len (host-data 'probe')", 3),
    ("len (values (host-data 'probe'))", 3),
    ("len (items (host-data 'probe'))", 3),
    ("len (host-data 'tags')", 2),
    ("type-of (host-data 'probe')", PathLiteral(Path(['dict']))),
    ("type-of (host-data 'tags')", PathLiteral(Path(['list']))),
    ("count: fn {data: `list`} [len data]; count (host-data 'tags')", 2),
    ("map (fn {tag} [tag]) (host-data 'tags')", ['a', 'b']),
    ("filter (fn {tag} [tag = 'a']) (host-data 'tags')", ['a']),
])
def test_operations_do_not_snapshot(store, snapshots, source, expected):
    store['probe'] = {'id': 'probe', 'count': 1, 'child': {'hp': 10}}
    store['tags'] = ['a', 'b']
    with ScriptRunner(host_data=store.__getitem__) as runner:
        for _ in range(2):
            result = runner.handle_script(source)
            assert result.status == 'ok', result.error_message
            assert result.value == expected
        assert snapshots == []


@pytest.mark.parametrize('value', [{'id': 'probe'}, ['a', 'b'], {}, []])
@pytest.mark.parametrize(('expression', 'expected'), [
    ('node != none', True), ('node = none', False),
    ('(node) != none', True), ('node = node', True),
    ('node |same', True), ('node |eq none', False),
    ('if [node != none] [same node] [false]', True),
])
def test_expression_heads_remain_data(
    store, snapshots, value, expression, expected,
):
    store['probe'] = value
    data = store['probe']
    with ScriptRunner(host_data=lambda key: data) as runner:
        runner.root_scope['same'] = lambda item: item is data
        result = runner.handle_script("node: host-data 'probe'; " + expression)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert runner.scope['node'] is data
        assert snapshots == []


@pytest.mark.parametrize('value', [{'count': 1}, ['a', 'b']])
@pytest.mark.parametrize('source', [
    "call (host-data 'probe') #[]", "node: host-data 'probe'; call node #[]",
    "node: host-data 'probe'; call `node` #[]",
])
def test_explicit_calls_create_detached_snapshots(
    store, snapshots, value, source,
):
    store['probe'] = value
    data = store['probe']
    with ScriptRunner(host_data=lambda key: data) as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == value and type(result.value) is type(value)
        assert snapshots == [data.uid]
        if isinstance(value, dict):
            data['count'] = 2
            assert result.value['count'] == 1
        else:
            data.append('c')
            assert result.value == ['a', 'b']


@pytest.mark.parametrize('gateway', ['host-data', 'host-object'])
@pytest.mark.parametrize('marked', [False, True])
def test_membership_does_not_read_values(
    store, snapshots, monkeypatch, gateway, marked,
):
    value = {'present': True, 'falsey': False, 'nothing': None, 'child': {}}
    if marked:
        value['__slip__'] = {'type': 'scope', 'prototype': 'Probe'}
    store['probe'] = value
    data = store['probe']
    reads = []
    original = RD.__getitem__

    def read(container, key):
        if container.uid == data.uid and key in value and key != '__slip__':
            reads.append(key)
        return original(container, key)

    monkeypatch.setattr(RD, '__getitem__', read)
    with ScriptRunner(host_data=lambda key: data) as runner:
        result = runner.handle_script(f'''
            node: {gateway} 'probe'
            #[has node 'present', has node 'falsey', has node 'nothing',
              has node 'child', has node 'missing', 'present' in node,
              'falsey' in node, 'nothing' in node, 'child' in node,
              'missing' in node]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [True, True, True, True, False] * 2
        assert reads == snapshots == []


def test_empty_persistent_list_iteration_is_a_noop(store, snapshots):
    store['location'] = {
        '__slip__': {'type': 'scope', 'prototype': 'Location'}, 'states': [],
    }
    with ScriptRunner(host_data=store.__getitem__) as runner:
        result = runner.handle_script('''
            location: host-object 'location'
            seen: 0
            foreach {value} location.states [seen: seen + 1]
            seen
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 0 and snapshots == []


def test_persistent_sequence_contains_uses_its_native_protocol(
    store, snapshots,
):
    store['tags'] = ['a', 'b']
    data = store['tags']
    with ScriptRunner(host_data=lambda key: data) as runner:
        result = runner.handle_script(
            "tags: host-data 'tags'; #['a' in tags, 'b' in tags, 'c' in tags]",
        )
        assert result.status == 'ok', result.error_message
        assert result.value == [True, True, False]
        assert snapshots == [data.uid] * 3


@pytest.mark.parametrize('key', ['probe', 'tags'])
def test_host_methods_receive_the_original_live_container(
    store, snapshots, key,
):
    store['probe'], store['tags'] = {'count': 1}, ['a', 'b']
    data = store[key]
    received = []

    def mutate(value):
        received.append(value)
        if key == 'probe':
            value['count'] += 1
        else:
            value.append('c')
        return True

    with ScriptRunner(host_data=lambda name: data) as runner:
        runner.root_scope['mutate'] = mutate
        result = runner.handle_script("mutate (host-data '" + key + "')")
        assert result.status == 'ok' and result.value is True
        assert received == [data] and received[0] is data
        assert snapshots == []
        if key == 'probe':
            assert store[key]['count'] == 2
        else:
            assert len(store[key]) == 3 and store[key][2] == 'c'


def test_nested_persistent_host_objects_share_storage_and_dispatch(
    store, snapshots,
):
    store['location'] = {
        '__slip__': {'type': 'scope', 'prototype': 'Location'}, 'name': 'Town',
    }
    store['person'] = {
        '__slip__': {'type': 'scope', 'prototype': 'Person'},
        'location': store['location'], 'tags': ['a', 'b'],
    }
    with ScriptRunner(host_data=store.__getitem__) as runner:
        result = runner.handle_script('''
            Person: scope #{}
            Location: scope #{}
            describe: fn {x: Person} ['person']
            describe: fn {x: Location} ['location']
            raw: host-data 'person'
            person: host-object 'person'
            place: host-object 'location'
            person.location.name: 'Harbor'
            #[type-of raw = `dict`, type-of raw.tags = `list`, raw.tags[0],
              describe person, describe person.location, place.name]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [
            True, True, 'a', 'person', 'location', 'Harbor',
        ]
        assert snapshots == []
