"""A bare callable is a pipe input; a grouped call supplies its result."""

import pytest

from slip import slip_core as core
from slip.slip_syntax import parse


@pytest.mark.parametrize(('source', 'name'), [
    ('zero |keep', 'zero'), ('one |keep', 'one'), ('two |keep', 'two'),
    ('box.zero |keep', 'zero'), ('zero |box.keep', 'zero'),
    ('keep-pipe |keep', 'keep-pipe'), ('zero |keep |keep', 'zero'),
    ('run [(inject zero) |keep]', 'zero'),
    ('run [(inject one) |keep]', 'one'),
    ('run [(inject two) |keep]', 'two'),
])
def test_bare_callable_pipeline_inputs_retain_identity_at_every_arity(
    source, name,
):
    calls = []

    def zero():
        calls.append(())
        return 7

    def one(value):
        calls.append((value,))
        return value

    def two(left, right):
        calls.append((left, right))
        return left + right

    def keep(value):
        return value

    scope = core.language_scope()
    scope.update({'zero': zero, 'one': one, 'two': two, 'keep': keep,
                  'box': {'zero': zero, 'keep': keep},
                  'keep-pipe': core.Pipe(keep)})
    assert core.execute(parse(source), scope) is scope[name]
    assert calls == []


@pytest.mark.parametrize('source', [
    '(zero) |keep', '(box.zero) |keep', '(zero) keep-pipe',
    'one 7 |keep', '1 + 6 |keep',
])
def test_explicit_calls_and_prefix_arguments_pipe_the_result_once(source):
    calls = []

    def zero():
        calls.append(7)
        return 7

    def one(value):
        calls.append(value)
        return value

    scope = core.language_scope()
    scope.update({'zero': zero, 'one': one, 'box': {'zero': zero},
                  'keep': lambda value: value})
    scope['keep-pipe'] = core.Pipe(scope['keep'])
    assert core.execute(parse(source), scope) == 7
    assert calls == ([] if source == '1 + 6 |keep' else [7])


def test_prepared_pipeline_inputs_capture_functions_and_keep_parameters_live(
    monkeypatch,
):
    calls = []

    def original():
        raise AssertionError('callable pipe input was invoked')

    def replacement(value):
        raise AssertionError('callable pipe input was invoked')

    def keep(value):
        calls.append(value)
        return value

    scope = core.language_scope()
    scope.update({'source': original, 'keep': keep})
    core.execute(parse('''
        captured: fn {} [source |keep]
        relay: fn {function} [function |keep]
    '''), scope)
    scope['source'] = replacement
    saved = scope['relay'].methods[0].stacks

    def forbidden(*args, **kwargs):
        raise AssertionError('warm pipeline rebound source')

    monkeypatch.setattr(core, 'convert', forbidden)
    assert core.invoke(scope['captured'], [], scope) is original
    for function in (original, replacement):
        assert core.invoke(scope['relay'], [function], scope) is function
    assert scope['relay'].methods[0].stacks is saved
    assert calls == [original, original, replacement]


def test_preparing_member_pipeline_inputs_does_not_read_the_host():
    reads = []

    def original():
        raise AssertionError('callable pipe input was invoked')

    def replacement(value):
        raise AssertionError('callable pipe input was invoked')

    class Host:
        def __getitem__(self, name):
            reads.append(name)
            return self.function

    host = Host()
    host.function = original
    scope = core.language_scope()
    scope.update({'box': host, 'keep': lambda value: value})
    core.execute(parse('relay: fn {} [box.function |keep]'), scope)
    assert reads == []
    for function in (original, replacement):
        host.function = function
        assert core.invoke(scope['relay'], [], scope) is function
    assert reads == ['function', 'function']
