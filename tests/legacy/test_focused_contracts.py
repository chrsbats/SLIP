"""Focused public contracts retained while replacing old engine internals."""

import functools
import operator

import pytest

from slip import ScriptRunner, slip_core as core
from slip.slip_core import Path, PathLiteral, Scope, execute
from slip.slip_library import SOURCE, library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize(('source', 'expected'), [
    ("target: core-function `core-add`; probe: fn {} [answer: 0; "
     "foreach {target} #[core-function `core-sub`] [answer: target 10 3]; "
     "answer]; probe", 7),
    ("target: core-function `core-add`; probe: fn {vars} [answer: 0; "
     "foreach vars #[core-function `core-sub`] [answer: target 10 3]; "
     "answer]; probe {target}", 7),
    ('then-block: [7]; if [true] then-block missing', 7),
    ('branch: [1]; if [branch: [7]; true] branch [0]', 7),
    ('s: scope #{present: none}; '
     '#[has s `present`, has s `missing`, s[`present`]]',
     [True, False, None]),
    ("#[to-int '12', to-int 'x', to-float '1.5', to-float 'x']",
     [12, None, 1.5, None]),
    ("k: 'x'; obj: #{'literal {{k}}': 1, \"my {{k}}\": 5}; "
     "#[obj['literal {{k}}'], obj['my x']]", [1, 5]),
    ('#[core-abs -5, core-len #[1, 2], core-not false, core-gte 2 1]',
     [5, 2, True, True]),
    ('Base: scope #{inherited: 1}; child: create Base [local: 2]; '
     "#[keys child, values child, items child, has child 'inherited']",
     [['local'], [2], [['local', 2]], True]),
    ('operation: |abs; apply: fn {f, value} [f value]; apply operation -2', 2),
    ('operation: |abs; map operation #[-3, 4]', [3, 4]),
    ('operation: |abs; call operation #[-5]', 5),
    ("f: fn {} [core-add (return 7) (emit 'unexpected' 1); 99]; f", 7),
    ("choose: fn {x: `int`, rest... |where true} ['rest']; "
     "choose: fn {x: `int`} ['exact']; choose 1", 'exact'),
    ("choose: fn {x |where true} ['untyped']; "
     "choose: fn {x: `int`} ['typed']; choose 1", 'typed'),
    ("A: scope #{}; B: create A; a: create A; b: create B; "
     "choose: fn {x: A, y: B} ['second']; "
     "choose: fn {x: B, y: A} ['first']; choose b b", 'first'),
])
def test_public_contracts(source, expected):
    scope = Scope(parent=library_scope())
    execute(parse(SOURCE), scope.root)
    assert execute(parse(source), scope) == expected
    assert scope.effects == []


@pytest.mark.parametrize('target', ["'z:'", '`z:`'])
@pytest.mark.parametrize('arguments', ['', ' #[]', ' #[1, 2]'])
def test_dynamic_set_requires_exactly_one_value_without_mutation(
    target, arguments,
):
    scope = Scope(parent=library_scope())
    scope['z'] = 9
    with pytest.raises(TypeError, match='one value'):
        execute(parse('call ' + target + arguments), scope)
    assert scope['z'] == 9
    assert execute(parse('call ' + target + ' #[none]'), scope) is None
    assert scope['z'] is None


def test_runtime_errors_have_structured_codes_at_both_boundaries():
    with ScriptRunner() as runner:
        captured = runner.handle_script('do [1 / 0]')
        assert captured.status == 'ok', captured.error_message
        assert captured.value['error']['code'] == PathLiteral(
            Path(['zero-division-error']),
        )
        failed = runner.handle_script("add 1 'x'")
        assert failed.status == 'err'
        assert failed.error['code'] == PathLiteral(Path(['type-error']))


def test_dynamic_binders_reuse_lists_and_keep_captured_fallbacks(monkeypatch):
    scope = Scope(parent=library_scope())
    execute(parse(SOURCE), scope.root)
    execute(parse('''
        target: core-function `core-add`
        probe: fn {vars, data} [
            foreach vars data [if [true] [none]]
            target 10 3
        ]
    '''), scope)
    function = scope['probe']
    saved = function.methods[0].stacks

    def forbidden(*args, **kwargs):
        raise AssertionError('dynamic binder rebuilt prepared code')

    monkeypatch.setattr(core, 'convert', forbidden)
    for signature, data, expected in (
        (core.Sig(['target']), [operator.sub], 7),
        (core.Sig(['other']), [operator.sub], 13),
        (core.Sig(['target']), [], 13),
    ):
        scope['target'] = operator.mul
        assert core.invoke(function, [signature, data], scope) == expected
        assert function.methods[0].stacks is saved
    assert scope['target'] is operator.mul


def test_stable_function_scopes_keep_direct_callable_references():
    scope = core.language_scope()
    execute(parse('stable: fn {x} [core-add x 1]'), scope)
    assert scope['stable'].methods[0].stacks[0][0] is operator.add


def test_equal_native_callables_keep_identity_specific_argument_readers():
    class EqualPartial(functools.partial):
        def __hash__(self):
            return 1

        def __eq__(self, other):
            return isinstance(other, EqualPartial)

    scope = core.language_scope()
    scope['scoped'] = EqualPartial(lambda value, *, scope: value)
    scope['plain'] = EqualPartial(lambda value: value)
    scope['zero'] = EqualPartial(lambda: 3)
    assert execute(parse('#[scoped 1, plain 2, zero]'), scope) == [1, 2, 3]


@pytest.mark.parametrize(('source', 'expected'), [
    ('target: core-function `core-add`; '
     'for {target} 0 1 [target]; target', 0),
    ('op: |core-add; probe: fn {vars} ['
     'foreach vars #[7] [none]; return op]; probe {op}', 7),
    ('target: core-function `core-add`; each: |foreach; probe: fn {} ['
     '{target} each #[core-function `core-sub`] [none]; '
     'target 10 3]; probe', 7),
    ('target: core-function `core-add`; probe: fn {vars} ['
     'foreach vars #[core-function `core-sub`] [none]; '
     'xs: range 20; len xs[0:(target 10 3)]]; probe {target}', 7),
    ('target: core-function `core-add`; probe: fn {vars} ['
     'foreach vars #[core-function `core-sub`] [none]; '
     'xs: range 20; [xs[(target 10 3)], y]: #[99, 1]; xs[7]]; '
     'probe {target}', 99),
    ('target: core-function `core-add`; probe: fn {} ['
     '"{{foreach {target} #[core-function `core-sub`] [none]}}"; '
     'target 10 3]; probe', 7),
    ('probe: fn {vars} [foreach vars #[] [none]; '
     'x: 1; x: + 2; x]; probe {unused}', 3),
    ('probe: fn {vars} [foreach vars #[] [none]; '
     'xs: #[1, 2]; xs[* 1]: + 2; xs]; probe {unused}', [3, 4]),
    ('probe: fn {vars} [foreach vars #[] [none]; '
     'if [true] [1] + 2]; probe {unused}', 3),
])
def test_scoped_binders_preserve_nested_and_aliased_execution(
    source, expected,
):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert result.side_effects == []


def test_shadowed_pipe_argument_retains_native_callable_identity():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            op: |core-add
            probe: fn {vars} [
                foreach vars #[core-function `core-sub`] [none]
                return op
            ]
            probe {op}
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value is operator.sub


def test_path_metadata_uses_the_same_scoped_binder_preparation():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            target: core-function `core-add`
            probe: fn {vars} [
                foreach vars #[core-function `core-sub`] [none]
                data: #{value: 1}
                ~data.value#(emit 'audit' (target 10 3))
            ]
            probe {target}
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 1
        assert result.side_effects == [{'topics': ['audit'], 'message': 7}]
