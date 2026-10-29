"""Chapter 013–014 transport, utility and result behavior on native values."""

import json

import httpx
import pytest

from slip import ScriptRunner


@pytest.mark.parametrize(('source', 'expected'), [
    ("#[join #['x', 'y', 'z'] ', ', split 'a,b,c' ',', "
     "replace 'foo bar foo' 'foo' 'baz', indent 'a\\nb' '>> ']",
     ['x, y, z', ['a', 'b', 'c'], 'baz bar baz', '>> a\n>> b']),
    ('#[2 ** 3, not true, not false, call add #[1, 2]]', [8, False, True, 3]),
    ('is-scope (current-scope)', True),
    ('eq (join `a` `b`) `a.b`', True),
    ("orig: #{nested: #[1, #{z: 9}]}; shallow: copy orig; deep: clone orig; "
     'orig.nested[1].z: 99; #[shallow.nested[1].z, deep.nested[1].z]',
     [99, 9]),
])
def test_ordinary_utilities(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


@pytest.mark.parametrize('source', [
    '~https://api.test/items', "r: resource `https://api.test/items`; del r",
])
def test_http_delete_returns_native_body(source):
    def respond(request):
        assert request.method == 'DELETE'
        return httpx.Response(200, json={'deleted': True})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(source)
            assert result.status == 'ok', result.error_message
            assert result.value == {'deleted': True}


def test_http_full_envelopes_and_assignment_result():
    def respond(request):
        return httpx.Response(200, headers={'X-Test': '1'}, json={'server': 7})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            deleted = runner.handle_script(
                '~https://api.test/items#(response-mode: `full`)',
            )
            assert deleted.status == 'ok', deleted.error_message
            assert deleted.value['status'] == 200
            assert deleted.value['value'] == {'server': 7}
            assert deleted.value['meta']['headers']['x-test'] == '1'
            assigned = runner.handle_script(
                'https://api.test/items#(response-mode: `full`): '
                "#{name: 'a'}",
            )
            assert assigned.status == 'ok', assigned.error_message
            assert assigned.value == {'name': 'a'}


def test_fluent_resource_verbs_share_configuration_and_order():
    state, calls = {'initial': True}, []

    def respond(request):
        nonlocal state
        calls.append(request.method)
        if request.method in ('PUT', 'POST'):
            assert request.headers['content-type'] == 'application/json'
            value = json.loads(request.content)
            if request.method == 'PUT':
                state = value
            else:
                state.update(value)
        elif request.method == 'DELETE':
            state = {}
        return httpx.Response(200, json=state)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(
                'api: resource `https://api.test/items#('
                "content-type: 'application/json')`\n" + '''
                initial: get api
                put api #{name: 'new-item', value: 42}
                post api #{extra: true}
                final: get api
                del api
                #[initial, final]
            ''')
            assert result.status == 'ok', result.error_message
            assert result.value == [
                {'initial': True},
                {'name': 'new-item', 'value': 42, 'extra': True},
            ]
            assert calls == ['GET', 'PUT', 'POST', 'GET', 'DELETE']
            assert state == {}
