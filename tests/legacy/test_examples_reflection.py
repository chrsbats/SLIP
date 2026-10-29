"""Ordinary example/test and signature reflection contract ports."""

import pytest

from slip.slip_core import Parameter, Path, PathLiteral, Sig
from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param('add: fn {x, y} [x + y] |example {x: 2, y: 3 -> 5}; test add',
                 1, id="inline_example"),
    pytest.param('g: fn {x} [x] |example {x: 1 -> 1}; '
                 'g: fn {x, y} [x + y]; example g {x: 2, y: 3 -> 5}; test g',
                 2, id="generic_aggregation"),
    pytest.param('h: fn {x} [x + 1] |example {x: 1 -> 2} '
                 '|example {x: 2 -> 3}; test h', 2, id="multiple_examples"),
    pytest.param('x: 10; y: 32; want: 42; sum: fn {x, y} [x + y]; '
                 'example sum {x, y -> want}; test sum', 1,
                 id="positional_names_with_bindings"),
    pytest.param('''
        Persona: scope #{}
        Item: scope #{}
        source: fn {actor: Persona, object: Item, original-text} [
            original-text
        ]
        description: get-sig source
        parameters: description.parameters
        parameters[0].type: `string`
        parameters[1].type: `string`
        adapter: fn (sig description) [#[actor, object, original-text]]
        #[source.methods[0].meta.type.parameters[0].type = Persona,
          adapter 'persona.1' 'item.1' 'take it']
    ''', [True, ['persona.1', 'item.1', 'take it']], id="detached_signature"),
    pytest.param('''
        add: fn (sig #{
            parameters: #[#{name: 'left', type: `int`},
                          #{name: 'right', type: `int`}]
            rest: none
            return-annotation: `int`
            where: none
        }) [left + right]
        add 10 20
    ''', 30, id="signature_mapping"),
    pytest.param("kind: fn {value: `string`} ['string']; "
                 "kind: fn {value: `id`} ['id']; "
                 "#[kind 'plain', kind 'id:item.apple.1']", ['string', 'id'],
                 id="id_specificity"),
    pytest.param("id: scope #{}; f: fn {x: `id`} [x]; f 'id:test.1'",
                 'id:test.1',
                 id="builtin_id_annotation"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_example_failure_is_structured():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            x: 2; y: 3; want: 4
            add: fn {x, y} [x + y]
            example add {x, y -> want}
            test add
        ''')
        assert result.status == 'err'
        assert result.error['code'] == PathLiteral(Path(['test-failed']))
        assert result.error['data'][0] == {
            'index': 0, 'expected': 4, 'actual': 5,
        }


def test_test_all_success_summary():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            mod: scope #{}
            run-with [
                add: fn {x, y} [x + y] |example {x: 1, y: 2 -> 3}
                mul: fn {x, y} [x * y] |example {x: 2, y: 3 -> 6}
            ] mod
            test-all mod
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value['with-examples'] == 2
        assert result.value['failed'] == 0
        assert result.value['passed'] == 2
        assert result.value['details'] == []


def test_test_all_failure_summary():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            mod: scope #{}
            run-with [
                f: fn {x} [x + 1]
                example f {x: 1 -> 2}
                example f {x: 1 -> 3}
            ] mod
            test-all mod
        ''')
        assert result.status == 'err'
        assert result.error['code'] == PathLiteral(Path(['test-failed']))
        summary = result.error['data']
        assert summary['with-examples'] == 1
        assert summary['failed'] == 1
        assert summary['details'][0]['name'] == 'f'


def test_example_execution_errors_are_reported():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            div-fn: fn {x, y} [x / y]
            example div-fn {x: 1, y: 0 -> none}
            test div-fn
        ''')
        assert result.status == 'err'
        assert 'division' in result.error['data'][0]['err'].lower()


def test_signature_parameters_are_canonical_and_views_are_derived():
    persona = Path(['Persona'])
    signature = Sig([Parameter('actor', persona), Parameter('original-text')])
    parameters = signature['parameters']
    assert [p['name'] for p in parameters] == ['actor', 'original-text']
    assert parameters[0]['type'] is persona
    assert 'type' not in parameters[1]
    assert parameters[0].name == 'actor'
    assert parameters[0].annotation is persona
    positional, keywords = signature.positional, signature.keywords
    positional.append('unexpected')
    keywords['unexpected'] = persona
    assert signature.positional == ['original-text']
    assert signature.keywords == {'actor': persona}
    string_type = PathLiteral(Path(['string']))
    parameters[0]['type'] = parameters[1]['type'] = string_type
    assert signature.keywords == {
        'actor': string_type, 'original-text': string_type,
    }
    assert signature.positional == []
    assert signature.param_order == [
        ('actor', string_type), ('original-text', string_type),
    ]
    del parameters[1]['type']
    assert signature.positional == ['original-text']
    assert signature.keywords == {'actor': string_type}
    assert signature.param_order[-1] == ('original-text', None)


def test_signature_distinguishes_untyped_and_explicit_none():
    signature = Sig([Parameter('untyped'), Parameter('typed', None, True)])
    untyped, typed = signature.parameters
    assert 'type' not in untyped
    assert 'type' in typed
    assert typed.annotation is None


def test_multimethod_get_sig_is_rejected():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            f: fn {x: `int`} [x]
            f: fn {x: `string`} [x]
            get-sig f
        ''')
        assert result.status == 'err'
        assert 'exactly one method' in result.error_message


def test_command_is_a_closure_hydrating_prototype_parameters():
    registry = {
        'id:persona.1': {
            '__slip__': {'type': 'scope', 'prototype': 'Persona'},
            'name': 'Ada',
        },
        'id:item.apple.1': {
            '__slip__': {'type': 'scope', 'prototype': 'Item'},
            'name': 'apple',
        },
    }
    with ScriptRunner(host_data=registry.__getitem__) as runner:
        result = runner.handle_script('''
            Persona: scope #{}
            Item: scope #{}
            take-method: fn {actor: Persona, object: Item, original-text} [
                #[actor.name, object.name, original-text]
            ]
            take: command take-method
            take 'id:persona.1' 'id:item.apple.1' 'take the apple'
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == ['Ada', 'apple', 'take the apple']


def test_examples_keep_signature_identity_and_float_samples():
    with ScriptRunner() as runner:
        defined = runner.handle_script('scale: fn {x} [x * 2]')
        assert defined.status == 'ok', defined.error_message
        function = runner.scope['scale']
        method = function.methods[0]
        signature, stacks = method.sig, method.stacks
        attached = runner.handle_script('example scale {x: 2.0 -> 4.0}')
        assert attached.status == 'ok', attached.error_message
        assert attached.value is function
        assert function.methods == [method]
        assert method.sig is signature and method.stacks is stacks
        assert not signature.parameters[0].is_typed
        sample = function.meta['examples'][0]
        assert sample.parameters[0].annotation == 2.0
        assert sample.return_annotation == 4.0
        assert type(sample.parameters[0].annotation) is float
        assert type(sample.return_annotation) is float
        checked = runner.handle_script('test scale')
        assert checked.status == 'ok' and checked.value == 1
        assert runner.scope['scale'] is function
        assert function.methods == [method]


@pytest.mark.parametrize('description', [
    '{x: missing -> none}', '{x: 1 -> missing}',
])
def test_preparation_errors_are_structured_and_testing_continues(description):
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            f: fn {x} [emit 'sample' x; x]
            example f ''' + description + '''
            example f {x: 2 -> 2}
            test f
        ''')
        assert result.status == 'err'
        assert result.error['code'] == PathLiteral(Path(['test-failed']))
        assert result.error['data'][0]['index'] == 0
        assert 'missing' in result.error['data'][0]['err']
        assert result.side_effects == [{'topics': ['sample'], 'message': 2}]


def test_inline_examples_retain_float_samples_without_inferred_methods():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            scale: fn {x} [x * 2] |example {x: 2.0 -> 4.0}
            test scale
        ''')
        assert result.status == 'ok' and result.value == 1
        function = runner.scope['scale']
        assert len(function.methods) == 1
        method = function.methods[0]
        assert not method.sig.parameters[0].is_typed
        sample = method.meta['examples'][0]
        assert sample.parameters[0].annotation == 2.0
        assert sample.return_annotation == 4.0
        assert type(sample.parameters[0].annotation) is float
        assert type(sample.return_annotation) is float
