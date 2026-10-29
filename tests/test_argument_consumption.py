"""Calls use their own signature; grouping explicitly bounds nested values."""

import operator

import pytest

from slip import slip_core as core
from slip.slip_library import SOURCE, library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize('target', [operator.not_, operator.add])
def test_required_pipe_argument_does_not_depend_on_its_targets_arity(target):
    scope = core.language_scope()
    calls = []

    def identity(value):
        calls.append(value)
        return value

    scope['identity'], scope['target'] = identity, target
    value = core.execute(parse('identity |target'), scope)
    assert isinstance(value, core.Pipe)
    assert value.target is target
    assert calls == [value]


def test_required_argument_reader_never_looks_up_the_pipe_targets_signature(
    monkeypatch,
):
    def forbidden(*args):
        raise AssertionError('argument reading inspected the next function')

    monkeypatch.setattr(core, 'signature', forbidden)
    value = core.Pipe(operator.not_)
    stack = [value]
    scope = core.language_scope()
    assert core.pop_arguments(1, 1, stack, scope, []) == [value]
    assert stack == []


@pytest.mark.parametrize(('source', 'expected'), [
    ('f: fn {a, b, c, d} [#[a, b, c, d]]; f 1 2 3 4', [1, 2, 3, 4]),
    ('f: fn {a, b, c, d} [#[a, b, c, d]]; 1 |f 2 3 4', [1, 2, 3, 4]),
    ('f: fn {a, b, c, d} [#[a, b, c, d]]; g: fn {x} [x + 1]; '
     'f 1 2 (g 2) 4', [1, 2, 3, 4]),
    ('f: fn {a, b, c, d} [#[a, b, c, d]]; g: fn {x} [x + 1]; '
     '1 |f 2 (g 2) 4', [1, 2, 3, 4]),
    ('collect: fn {values...} [values]; collect 1 2 3', [1, 2, 3]),
    ('collect: fn {values...} [values]; 1 |collect 2 3', [1, 2, 3]),
    ('collect: fn {values...} [values]; collect 1 2 3 |reverse', [3, 2, 1]),
    ('collect: fn {values...} [values]; #[collect 1 2, collect 3 4]',
     [[1, 2], [3, 4]]),
    ('collect: fn {values...} [values]; '
     'first: collect 1 2; second: collect 3 4; #[first, second]',
     [[1, 2], [3, 4]]),
    ('collect: fn {values...} [values]\n'
     'first: collect 1 2\nsecond: collect 3 4\n#[first, second]',
     [[1, 2], [3, 4]]),
    ('collect: fn {values...} [values]; '
     'join #[(collect 1 2), (collect 3 4)] ":"', '[1, 2]:[3, 4]'),
    ('choose: fn {a, b} [a + b]; '
     'choose: fn {a, b, c, d} [a + b + c + d]; '
     '#[choose 1 2, choose 1 2 3 4, 1 |choose 2, 1 |choose 2 3 4]',
     [3, 10, 3, 10]),
    ('f: fn {a, b, c, d} [a + b + c + d]; '
     'example f {a: 1, b: 2, c: 3, d: 4 -> 10} |test', 1),
])
def test_declared_counts_and_group_boundaries(source, expected):
    scope = core.Scope(parent=library_scope())
    core.execute(parse(SOURCE), scope.root)
    assert core.execute(parse(source), scope) == expected


@pytest.mark.parametrize(('source', 'expected'), [
    ('optional 1', [1, 10, 20]),
    ('optional 1 2', [1, 2, 20]),
    ('optional 1 2 3', [1, 2, 3]),
    ('1 |optional 2 3', [1, 2, 3]),
    ('optional 1 |reverse', [20, 10, 1]),
    ('#[optional 1, optional 2 3]', [[1, 10, 20], [2, 3, 20]]),
])
def test_optional_arguments_use_declared_defaults(source, expected):
    def optional(first, second=10, third=20):
        return [first, second, third]

    scope = library_scope()
    scope['optional'] = optional
    assert core.execute(parse(source), scope) == expected


def test_grouped_arguments_read_once_in_order_and_keep_the_saved_value():
    calls = []

    def value(number):
        calls.append(number)
        return number

    def four(a, b, c, d):
        return [a, b, c, d]

    scope = core.language_scope()
    scope['value'], scope['four'] = value, four
    assert core.execute(parse(
        '(value 1) |four (value 2) (value 3) (value 4)',
    ), scope) == [1, 2, 3, 4]
    assert calls == [1, 2, 3, 4]


def test_missing_required_values_fail_before_calling_the_function():
    calls = []

    def four(a, b, c, d):
        calls.append([a, b, c, d])

    scope = core.language_scope()
    scope['four'] = four
    with pytest.raises(TypeError, match='Expected at least 4 arguments'):
        core.execute(parse('four 1 2 3'), scope)
    assert calls == []
