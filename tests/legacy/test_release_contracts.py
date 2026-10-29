"""Public assertions recovered from mixed legacy-engine test modules."""

import operator

import httpx
import pytest

from slip import ScriptRunner
from slip.slip_core import Path, PathLiteral, Pipe, Scope


@pytest.mark.parametrize(('source', 'expected'), [
    ('total: 0; result: foreach {x} #[1, 2, 3] [total: + x]; '
     '#[result, total, x]', [None, 6, 3]),
    ('total: 0; foreach {a, b} #[#[1, 2], #[3, 4]] ['
     'total: total + a + b]; total', 10),
    ('make-code: fn {} [[1]]; first: make-code; second: make-code; '
     'first[0][0]: 2; second[0][0]', 1),
    ('make-code: fn {} [[[1]]]; first: make-code; second: make-code; '
     'first[0][0][0][0]: 2; second[0][0][0][0]', 1),
    ("make-code: fn {} [[add 1 2]]; first: make-code; second: make-code; "
     "first[0][0].keys[0]: 'sub'; run second", 3),
    ('make-code: fn {} [[1]]; code: make-code; code[0][0]: 2; '
     'run-with code (scope #{})', 2),
])
def test_loop_and_code_value_contracts(source, expected):
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert result.side_effects == []


def test_sequence_destructuring_rejects_a_mismatch_before_the_body():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script(
            "do [foreach {a, b} #[#[1]] [emit 'unexpected' a]]",
        )
        assert result.status == 'ok', result.error_message
        assert result.value['status'] == PathLiteral(Path(['err']))
        assert result.value['error']['code'] == PathLiteral(
            Path(['type-error']),
        )
        assert result.value['effects'] == result.side_effects == []


def test_scope_constructor_rejects_the_reserved_metadata_binding():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('scope #{meta: #{user-value: 7}}')
        assert result.status == 'err'
        assert 'meta' in result.error_message
        assert 'reserved' in result.error_message


def test_scope_lookup_and_local_deletion_preserve_the_parent():
    parent = Scope({'a': 1})
    child = Scope({'a': 2}, parent=parent)
    assert child.get('a') == 2 and child.get('missing', 9) == 9
    del child['a']
    assert child['a'] == 1
    with pytest.raises(KeyError):
        del child['a']
    assert parent['a'] == 1
    parent.bindings['a'] = 3
    assert child['a'] == 3


def test_get_body_preserves_identity_and_rejects_a_different_signature():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('f: fn {x: `int`} [x]')
        assert result.status == 'ok', result.error_message
        body = runner.handle_script('get-body f {x: `int`}')
        assert body.status == 'ok', body.error_message
        assert body.value is runner.scope['f'].methods[0].body
        missing = runner.handle_script('do [get-body f {x: `string`}]')
        assert missing.status == 'ok', missing.error_message
        assert missing.value['status'] == PathLiteral(Path(['err']))


def test_cached_public_modules_use_each_runners_current_host_data(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv('SLIP_CACHE_DIR', str(tmp_path / 'cache'))
    path = tmp_path / 'lookup.slip'
    path.write_text('''
        lookup: fn {object-id} [
            object: host-object object-id
            object.value
        ] |public
    ''')
    first_data = {'item': {'value': 'first'}}
    second_data = {'item': {'value': 'second'}}
    with ScriptRunner(host_data=first_data.__getitem__, background_io=False) \
            as first, ScriptRunner(host_data=second_data.__getitem__,
                                   background_io=False) as second:
        locator = 'file://' + str(path)
        one = first.import_public_module(locator)
        two = second.import_public_module(locator)
        command = {'function': 'lookup', 'arguments': {'object-id': 'item'}}
        values = []
        for module in (one, two):
            result = module.run_json_command(command)
            assert result.status == 'ok', result.error_message
            values.append(result.value)
        first_data['item'] = {'value': 'replacement'}
        result = one.run_json_command(command)
        assert result.status == 'ok', result.error_message
        assert values + [result.value] == ['first', 'second', 'replacement']


def test_local_derived_callable_shadows_a_capture_with_one_read():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            target: core-function `core-add`
            probe: fn {} [
                target: cell {} [
                    emit 'read' 'target'
                    core-function `core-sub`
                ]
                target 10 3
            ]
            probe
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 7
        assert result.side_effects == [
            {'topics': ['read'], 'message': 'target'},
        ]


@pytest.mark.parametrize('wrapper', [
    'run-with [{body}] (scope #{{}})',
    'when [true] [{body}]',
    'cond #[#[[true], [{body}]]]',
])
@pytest.mark.parametrize('derived', [False, True])
def test_raw_execution_observes_names_introduced_in_its_own_scope(
    wrapper, derived,
):
    body = '''
        before: target 10 3
        each {target} #[core-function `core-sub`] [none]
        #[before, target 10 3]
    '''
    each = "cell {} [emit 'read' 'each'; core-function `foreach`]" \
        if derived else 'core-function `foreach`'
    with ScriptRunner(background_io=False) as runner:
        for _ in range(2):
            result = runner.handle_script(
                'target: core-function `core-add`; each: ' + each + '; '
                + wrapper.format(body=body),
            )
            assert result.status == 'ok', result.error_message
            assert result.value == [13, 7]
            assert result.side_effects == (
                [{'topics': ['read'], 'message': 'each'}] if derived else []
            )


def test_live_member_operator_is_read_once_per_iteration():
    reads = []

    class Host:
        @property
        def operation(self):
            reads.append(True)
            return Pipe(operator.add)

    with ScriptRunner(background_io=False) as runner:
        runner.root_scope['host'] = Host()
        result = runner.handle_script('''
            total: 0
            foreach {value} #[1, 2, 3] [total: total host.operation value]
            total
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 6 and reads == [True] * 3


def test_destructuring_writes_resource_targets_in_source_order():
    stored, calls = {}, []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == 'PUT':
            stored[request.url.path] = request.content.decode()
            return httpx.Response(200, text='saved')
        return httpx.Response(200, text=stored[request.url.path])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client, background_io=False) as runner:
            result = runner.handle_script('''
                [https://api/a, https://api/b]: #['X', 'Y']
                #[https://api/a, https://api/b]
            ''')
            assert result.status == 'ok', result.error_message
            assert result.value == ['X', 'Y']
            assert calls == [('PUT', '/a'), ('PUT', '/b'),
                             ('GET', '/a'), ('GET', '/b')]
