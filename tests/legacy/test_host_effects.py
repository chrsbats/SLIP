"""Nondeferred chapter 011–012 and 015 host, loop and effect contracts."""

import pytest

from slip import SLIPHost, ScriptRunner, slip_api_method


class Host(SLIPHost):
    def __init__(self):
        self.data = {'hp': 10}

    def __getitem__(self, key):
        if key.startswith('_'):
            raise KeyError('private')
        return self.data[key]

    def __setitem__(self, key, value):
        if key.startswith('_'):
            raise KeyError('private')
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]

    @slip_api_method
    def take_damage(self, amount):
        self.data['hp'] -= amount

    def internal_calculation(self):
        return 42


@pytest.mark.parametrize(('source', 'expected'), [
    ('i: 3; last: none; while [i > 0] [last: i; i: - 1]; last', 1),
    ('sum: 0; foreach {x} #[1, 2, 3, 4] [sum: + x]; sum', 10),
    ('obj.hp: 80; obj.hp', 80),
    ('take-damage 3; obj.hp', 7),
    ("obj: host-object 'main'; obj.hp: 5; obj.hp", 5),
])
def test_loop_and_host_contracts(source, expected):
    host = Host()
    with ScriptRunner(host_object=host, host_data=lambda key: host) as runner:
        runner.root_scope['obj'] = host
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_deletion_and_undecorated_methods_fail_without_exposure():
    host = Host()
    with ScriptRunner(host_object=host) as runner:
        runner.root_scope['obj'] = host
        deleted = runner.handle_script('obj.tmp: 1; ~obj.tmp; obj.tmp')
        assert deleted.status == 'err' and 'tmp' in deleted.error_message
        assert 'tmp' not in host.data
        hidden = runner.handle_script('internal-calculation 0')
        assert hidden.status == 'err'
        assert 'internal-calculation' in hidden.error_message


def test_raw_storage_lazy_views_assignment_and_existing_handles():
    registry = {'item': {
        '__slip__': {'type': 'scope', 'prototype': 'Item'},
        'id': 'item', 'hp': 7, 'location': {'name': 'Town'},
        'next': {'old': True},
    }}
    calls = []

    def load(key):
        calls.append(key)
        return registry[key]

    with ScriptRunner(host_data=load) as runner:
        result = runner.handle_script('''
            Item: scope #{}
            raw: host-data 'item'
            obj: host-object 'item'
            again: host-object obj
            obj.next: #{}
            #[type-of raw = `dict`, type-of obj = `scope`, obj.hp,
              type-of obj.location = `dict`, keys obj.next, again.id]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [True, True, 7, True, [], 'item']
        assert calls == ['item', 'item']
        assert type(registry['item']['next']) is dict
        assert registry['item']['next'] == {}


def test_host_views_do_not_eagerly_walk_cycles_or_unread_nested_graphs():
    class UnreadMapping(dict):
        def items(self):
            raise AssertionError('host gateway eagerly walked nested data')

    location = {'__slip__': {'type': 'scope', 'prototype': 'Location'},
                'name': 'Town'}
    domain = {'__slip__': {'type': 'scope', 'prototype': 'Domain'},
              'locations': [location], 'unread': UnreadMapping(secret=1)}
    location['domain'] = domain
    with ScriptRunner(host_data=lambda key: location) as runner:
        result = runner.handle_script('''
            Location: scope #{}
            Domain: scope #{}
            describe: fn {value: Domain} ['domain']
            describe: fn {value: Location} ['location']
            describe: fn {value} ['other']
            loc: host-object 'location'
            #[describe loc.domain, describe loc.domain.locations[0],
              loc.domain.locations[0].name]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == ['domain', 'location', 'Town']


def test_separately_loaded_views_share_live_storage_and_prototype():
    location = {'__slip__': {'type': 'scope', 'prototype': 'Location'},
                'name': 'Town'}
    person = {'__slip__': {'type': 'scope', 'prototype': 'Person'},
              'location': location}
    registry = {'person': person, 'location': location}
    with ScriptRunner(host_data=registry.__getitem__) as runner:
        result = runner.handle_script('''
            Person: scope #{}
            Location: scope #{}
            describe: fn {value: Person} ['person']
            describe: fn {value: Location} ['location']
            p: host-object 'person'
            one: p.location
            two: host-object 'location'
            one.name: 'Harbor'
            #[describe p, describe one, two.name]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == ['person', 'location', 'Harbor']


@pytest.mark.parametrize('source', [
    "x: 'Torch'; emit #['self', 'others'] #{sentence: \"You take {{x}}.\"}",
    "display-name: fn {obj} [obj.name]; "
    "obj: #{name: 'Torch'}; "
    "emit #['self', 'others'] #{sentence: \"You take {{display-name obj}}.\"}",
    "Item: scope #{}; display-name: fn {obj: Item} [obj.name]; "
    "obj: host-object 'item'; "
    "emit #['self', 'others'] #{sentence: \"You take {{display-name obj}}.\"}",
])
def test_structured_effects_interpolate_in_the_calling_environment(source):
    item = {'__slip__': {'type': 'scope', 'prototype': 'Item'},
            'name': 'Torch'}
    with ScriptRunner(host_data=lambda key: item) as runner:
        result = runner.handle_script(source + '; none')
        assert result.status == 'ok', result.error_message
        assert result.value is None
        assert result.side_effects == [{
            'topics': ['self', 'others'],
            'message': {'sentence': 'You take Torch.'},
        }]


def test_fireball_returns_detached_state_and_ordered_native_effects():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            impact: fn {caster, target, area} [
                damage: 50 - target.fire-resistance
                emit 'visual' #{effect: 'explosion', position: target.position}
                emit 'sound' #{sound: 'fireball_hit.wav', volume: 1.0}
                emit 'combat' #{type: `damage`, target: target.id,
                                amount: damage, element: `fire`}
                next: clone target
                next.hp: target.hp - damage
                next
            ]
            target: #{id: 't1', hp: 100, fire-resistance: 10,
                      position: #{x: 1, y: 2}}
            impact #{name: 'Mage'} target none
        ''')
        assert result.status == 'ok', result.error_message
        assert type(result.value) is dict and result.value['hp'] == 60
        assert runner.scope['target']['hp'] == 100
        assert [effect['topics'] for effect in result.side_effects] == [
            ['visual'], ['sound'], ['combat'],
        ]
        assert result.side_effects[0]['message'] == {
            'effect': 'explosion', 'position': {'x': 1, 'y': 2},
        }
        assert result.side_effects[1]['message'] == {
            'sound': 'fireball_hit.wav', 'volume': 1.0,
        }
        assert result.side_effects[2]['message']['amount'] == 40


def test_top_level_return_effect_order_and_structured_messages():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            emit 'ui' 'one'
            emit #['a', 'b'] 'two'
            emit 'events' #[1, 2, #{ok: true}]
            return 42
            emit 'unexpected' 'must not execute'
        ''')
        assert result.status == 'ok' and result.value == 42
        assert result.side_effects == [
            {'topics': ['ui'], 'message': 'one'},
            {'topics': ['a', 'b'], 'message': 'two'},
            {'topics': ['events'], 'message': [1, 2, {'ok': True}]},
        ]
