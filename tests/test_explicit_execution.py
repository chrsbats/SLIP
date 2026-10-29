"""Position selects calls; arguments retain values and deletion is exact."""

import operator

import pytest

from slip import slip_core as core
from slip.slip_syntax import parse


@pytest.mark.parametrize('source', ['take time', 'take box.time'])
def test_zero_argument_functions_are_passed_without_invocation(source):
    calls = []

    def time():
        calls.append('time')
        return 7

    def take(value):
        return value

    scope = core.language_scope()
    scope['time'], scope['take'], scope['box'] = time, take, {'time': time}
    assert core.execute(parse(source), scope) is time
    assert calls == []


@pytest.mark.parametrize('source', ['time', '(time)', 'take (time)'])
def test_expression_heads_and_explicit_groups_invoke_once(source):
    calls = []

    def time():
        calls.append('time')
        return 7

    scope = core.language_scope()
    scope['time'], scope['take'] = time, lambda value: value
    assert core.execute(parse(source), scope) == 7
    assert calls == ['time']


@pytest.mark.parametrize('source', [
    'make', '(make)', '((make))', 'keep (make)', '(make) |keep', '#[(make)]',
    'saved: (make)', 'saved: ((make))',
])
def test_completed_groups_keep_callable_results_without_another_call(source):
    calls = []

    def result():
        calls.append('result')
        return 7

    def make():
        calls.append('make')
        return result

    scope = core.language_scope()
    scope['make'], scope['keep'] = make, lambda value: value
    value = core.execute(parse(source), scope)
    if isinstance(value, list):
        assert len(value) == 1
        value = value[0]
    assert value is result
    assert calls == ['make']


def test_call_explicitly_invokes_a_groups_callable_result():
    scope = core.language_scope()
    core.execute(parse('make: fn {} [fn {} [7]]'), scope)
    assert core.is_function(core.execute(parse('(make)'), scope))
    assert core.execute(parse('call (make)'), scope) == 7


@pytest.mark.parametrize('source', ['add', '(add)', 'fn', 'call'])
def test_missing_arguments_at_call_heads_are_errors(source):
    with pytest.raises(TypeError, match='Expected at least'):
        core.execute(parse(source), core.language_scope())


def test_lazy_argument_providers_also_require_their_declared_inputs():
    def lazy(value, *, stack, scope):
        raise AssertionError('missing argument reached the function body')

    scope = core.language_scope()
    scope['lazy'] = lazy
    with pytest.raises(TypeError, match='Expected at least 1 arguments'):
        core.execute(parse('lazy'), scope)


def test_function_values_can_be_returned_explicitly_at_every_arity():
    scope = core.language_scope()
    core.execute(parse('keep: fn {value} [return value]'), scope)
    scope['zero'] = lambda: 7
    assert core.execute(parse('keep zero'), scope) is scope['zero']
    assert core.execute(parse('keep add'), scope) is operator.add


def test_ungrouped_function_argument_is_not_a_nested_call():
    calls = []

    def subtract(left, right):
        calls.append((left, right))
        return left - right

    scope = core.language_scope()
    scope['sub'] = subtract
    assert core.execute(parse('add 1 (sub 1 2)'), scope) == 0
    assert calls == [(1, 2)]
    calls.clear()
    with pytest.raises(TypeError):
        core.execute(parse('add 1 sub 1 2'), scope)
    assert calls == []


@pytest.mark.parametrize('target', ['zero', "'zero'", '`zero`'])
def test_call_without_an_argument_list_invokes_its_target(target):
    calls = []

    def zero():
        calls.append('zero')
        return 42

    scope = core.language_scope()
    scope['zero'] = zero
    assert core.execute(parse('call ' + target), scope) == 42
    assert calls == ['zero']


def test_call_does_not_construct_a_missing_path_or_pass_through_data():
    scope = core.language_scope()
    with pytest.raises(KeyError, match='missing'):
        core.execute(parse("call 'missing'"), scope)
    with pytest.raises(TypeError):
        core.execute(parse('call 42'), scope)


def test_injection_uses_the_same_function_value_argument_rule():
    scope = core.language_scope()
    scope['zero'] = lambda: 7
    scope['take'] = lambda value: value
    assert core.execute(parse('run [(inject add) 1 2]'), scope) == 3
    assert core.execute(parse('run [(inject zero)]'), scope) == 7
    passed = core.execute(parse('run [take (inject zero)]'), scope)
    assert passed is scope['zero']
    assert core.execute(parse('run [(inject (add 1 2))]'), scope) == 3
    with pytest.raises(TypeError, match='inject takes one value'):
        core.execute(parse('run [(inject add 1 2)]'), scope)


@pytest.mark.parametrize('name', ['Root', 'root'])
def test_delete_retains_empty_ancestor_identity_regardless_of_name(name):
    scope = core.language_scope()
    child = core.Scope({'leaf': 7})
    parent = core.Scope({'child': child})
    scope[name] = parent
    assert core.execute(parse('~' + name + '.child.leaf'), scope) == 7
    assert scope[name] is parent
    assert parent['child'] is child
    assert child.bindings == {}


def test_delete_metadata_executes_once_without_pruning_ancestors():
    calls = []
    scope = core.language_scope()
    scope['note'] = lambda: calls.append('note')
    child = core.Scope({'leaf': 7})
    scope['Root'] = core.Scope({'child': child})
    assert core.execute(parse('~Root.child.leaf#(note: note)'), scope) == 7
    assert scope['Root']['child'] is child
    assert calls == ['note']


def test_query_delete_metadata_executes_once_for_all_original_targets():
    calls = []
    scope = core.language_scope()
    scope['note'] = lambda: calls.append('note')
    rows = [{'leaf': 1}, {'leaf': 2}]
    scope['rows'] = rows
    assert core.execute(parse('~rows.leaf#(note: note)'), scope) == 1
    assert rows == [{}, {}]
    assert calls == ['note']
