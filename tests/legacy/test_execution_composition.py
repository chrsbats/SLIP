"""Public evaluation/dispatch assertions from the replaced kernel tests."""

import httpx
import pytest

from slip import ScriptRunner
from slip.slip_core import Code, IString


@pytest.mark.parametrize('value', [
    [1, 2], {'a': 1}, Code([[7]]), IString('{{missing}}'),
])
def test_control_results_keep_original_identity(value):
    with ScriptRunner() as runner:
        runner.root_scope['original'] = value
        runner.root_scope['same-object'] = lambda actual: actual is value
        result = runner.handle_script('if [true] [original] |same-object')
        assert result.status == 'ok', result.error_message
        assert result.value is True


@pytest.mark.parametrize('expression', [
    "if [true] [(return 7); emit 'unexpected' 'branch']",
    'if [true] [return 7] |core-add 1', '(return 7) |core-add 1',
    '1 + (return 7)', '1 |core-add (return 7)', 'core-add 1 (return 7)',
    "core-add (return 7) (emit 'unexpected' 'argument')",
    'if (return 7) [0]', 'while (return 7) [0]',
    'foreach {x} (return 7) [0]', 'fn (return 7) [0]',
])
def test_return_exits_all_remaining_call_and_control_positions(expression):
    with ScriptRunner() as runner:
        result = runner.handle_script(
            'f: fn {} [' + expression
            + "; emit 'unexpected' 'continued'; 99]; f",
        )
        assert result.status == 'ok', result.error_message
        assert result.value == 7
        assert result.side_effects == []


def test_rendered_control_result_is_not_interpolated_again():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            text: '{{missing}}'
            if [true] ["{{text}}"] |len
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 11


@pytest.mark.parametrize('depth', range(6))
def test_recursive_walks_visit_each_node_exactly_once(depth):
    node = 0
    for _ in range(depth):
        node = {'child': node}
    with ScriptRunner() as runner:
        runner.root_scope['node'] = node
        result = runner.handle_script('''
            state: scope #{calls: 0}
            walk: fn {value} [
                state.calls: + 1
                if [(type-of value) = `dict`] [
                    size: 1
                    foreach {key} (keys value) [
                        size: size + (walk value[key])
                    ]
                    size
                ] [1]
            ]
            walk node
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == depth + 1
        assert runner.scope['state']['calls'] == depth + 1


@pytest.mark.parametrize('depth', range(6))
def test_pipe_recursion_has_linear_call_count(depth):
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            state: scope #{calls: 0}
            walk: fn {depth} [
                state.calls: + 1
                if [depth = 0] [0] [1 |core-add (walk (depth - 1))]
            ]
        ''' + f'walk {depth}')
        assert result.status == 'ok', result.error_message
        assert result.value == depth
        assert runner.scope['state']['calls'] == depth + 1


@pytest.mark.parametrize(('expression', 'expected', 'reads'), [
    ('0 |core-add {operand}', 7, 1), ('saved: {operand}', 7, 1),
    ('false and {operand}', False, 0), ('true or {operand}', True, 0),
])
@pytest.mark.parametrize('kind', ['cell', 'http', 'file'])
def test_lazy_operands_do_not_compute_cells_or_fetch_resources(
    expression, expected, reads, kind, tmp_path,
):
    requests, file_reads = [], []
    (tmp_path / 'value.json').write_text('7')

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=7)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            runner.source_dir = str(tmp_path)
            original_get = runner.root_scope['get']

            def counted_get(target, options=None, *, scope):
                file_reads.append(target)
                return original_get(target, options, scope=scope)

            if kind == 'file':
                runner.root_scope['get'] = counted_get
            source = "sample: cell {} [emit 'cell' 7; 7]; "
            operand = {'cell': 'sample', 'http': 'https://api/value',
                       'file': 'file://value.json'}[kind]
            result = runner.handle_script(source + expression.format(
                operand=operand,
            ))
            assert result.status == 'ok', result.error_message
            assert result.value == expected
            assert len(requests) == (reads if kind == 'http' else 0)
            assert len(file_reads) == (reads if kind == 'file' else 0)
            assert len(result.side_effects) == (reads if kind == 'cell' else 0)


def test_failure_operands_emit_once_and_guard_errors_are_not_false():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            probe: fn {} [emit 'probe' 7; fail 'boom']
            0 |core-add (probe)
        ''')
        assert result.status == 'err' and 'boom' in result.error_message
        assert result.side_effects == [{'topics': ['probe'], 'message': 7}]
        guarded = runner.handle_script('''
            choose: fn {x} ['fallback']
            choose: fn {x |where missing-name > 0} ['guarded']
            choose 1
        ''')
        assert guarded.status == 'err'
        assert 'missing-name' in guarded.error_message


def test_mixed_parameter_order_survives_recursive_host_id_dispatch(tmp_path):
    (tmp_path / 'agents.slip').write_text('Item: scope #{}')
    data = {'__slip__': {'type': 'scope', 'prototype': 'Item'},
            'name': 'Brass Key'}
    with ScriptRunner(host_data=lambda key: data) as runner:
        runner.source_dir = str(tmp_path)
        result = runner.handle_script('''
            agents: import `file://agents.slip`
            Item: agents.Item
            take: fn {object: agents.Item, actor} [
                #['typed', object.name, actor]
            ]
            take: fn {object-id, actor |where \
                      (type-of object-id) = `string`} [
                take (host-object object-id) actor
            ]
            #[take (host-object 'item-1') 'actor-1', take 'item-1' 'actor-1']
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [['typed', 'Brass Key', 'actor-1']] * 2


def test_compound_filters_keep_explicit_logical_grouping():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            players: #[
                #{name: 'Karl', class: 'Warrior', hp: 120},
                #{name: 'Jaina', class: 'Mage', hp: 90},
                #{name: 'Thrall', class: 'Warrior', hp: 130}
            ]
            #[players[.hp > 100 and (.class = 'Warrior')].name,
              players[.hp > 100 and (.name = 'Karl' or \
                  (.name = 'Jaina'))].name]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [['Karl', 'Thrall'], ['Karl']]
