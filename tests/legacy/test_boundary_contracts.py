"""Remaining public host, failure and lazy-function boundary regressions."""

import pytest

from slip import ScriptRunner
from slip.slip_core import Path, PathLiteral


@pytest.mark.parametrize('source', [
    "s: scope #{}; #[has s 'meta', 'meta' in s, is-dict s.meta]",
    "s: host-object 'item'; #[has s 'meta', 'meta' in s, is-dict s.meta]",
])
def test_reserved_metadata_is_readable_but_not_a_binding(source):
    data = {'__slip__': {'type': 'scope'}, 'hp': 10}
    with ScriptRunner(host_data=lambda key: data) as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == [False, False, True]


@pytest.mark.parametrize('code', ["'invalid'", '`invalid`'])
@pytest.mark.parametrize('captured', [False, True])
def test_domain_failure_tokens_messages_and_data(code, captured):
    source = 'fail ' + code + " #{field: 'name'}"
    with ScriptRunner() as runner:
        result = runner.handle_script('do [' + source + ']' if captured
                                      else source)
        if captured:
            assert result.status == 'ok', result.error_message
            assert result.value['status'] == PathLiteral(Path(['err']))
            error = result.value['error']
        else:
            assert result.status == 'err'
            error = result.error
        assert error['kind'] == PathLiteral(Path(['domain']))
        assert error['code'] == PathLiteral(Path(['invalid']))
        assert error['message'] == 'invalid'
        assert error['data'] == {'field': 'name'}
        assert result.side_effects == []


def test_generated_prototype_can_complete_a_forward_annotation():
    data = {'__slip__': {'type': 'scope', 'prototype': 'MissingType'},
            'hp': 10}
    with ScriptRunner(host_data=lambda key: data) as runner:
        result = runner.handle_script('''
            describe: fn {x: MissingType} ['typed']
            describe: fn {x} ['fallback']
            obj: as-slip (host-data 'item')
            #[describe obj, obj.hp, is-a obj MissingType]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == ['typed', 10, True]


@pytest.mark.parametrize(('expression', 'expected', 'reads'), [
    ('0 |core-add operand.value', 7, 1),
    ('saved: operand.value', 7, 1),
    ('false and operand.value', False, 0),
    ('true or operand.value', True, 0),
    ('saved: fn {} [operand.value]; none', None, 0),
])
def test_host_properties_are_live_and_read_only_when_consumed(
    expression, expected, reads,
):
    class Operand:
        def __init__(self):
            self.reads = 0

        @property
        def value(self):
            self.reads += 1
            return 7

    operand = Operand()
    with ScriptRunner() as runner:
        runner.root_scope['operand'] = operand
        result = runner.handle_script(expression)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert operand.reads == reads


@pytest.mark.parametrize(('expression', 'expected'), [
    ("logical-and false (emit 'unexpected' 1)", False),
    ("logical-or true (emit 'unexpected' 1)", True),
    ("operation false (emit 'unexpected' 1)", False),
    ("apply operation false", False),
    ("true and 7", 7),
    ("false or 7", 7),
    ("call logical-and #[true, 7]", 7),
    ("call logical-or #[false, 7]", 7),
])
def test_lazy_logical_helpers_and_stored_aliases(expression, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            operation: |logical-and
            apply: fn {operation, value} [
                operation value (emit 'unexpected' 1)
            ]
        ''' + expression)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert result.side_effects == []
        assert runner.root_scope['contains'] is \
            runner.root_scope['core-contains']


@pytest.mark.parametrize('expression', ['true and op', 'false or op'])
def test_selected_logical_operands_consume_shadowed_alias_data(expression):
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            op: |core-add
            probe: fn {} [
                foreach {op} #[true] [none]
        ''' + expression + ']\nprobe')
        assert result.status == 'ok', result.error_message
        assert result.value is True
