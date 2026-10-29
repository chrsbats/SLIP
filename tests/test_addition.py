import pytest

from slip import ScriptRunner, slip_core as core
from slip.slip_library import library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize('scope_factory', [core.language_scope, library_scope])
@pytest.mark.parametrize('source', [
    'add left right', 'core-add left right', 'left + right',
])
@pytest.mark.parametrize(('left', 'right', 'expected'), [
    ([1], 2, [1, 2]),
    ([], 'item', ['item']),
    ([], {'id': 'actor'}, [{'id': 'actor'}]),
    ([1], [2, 3], [1, 2, 3]),
    (10, 5, 15),
    ('left', 'right', 'leftright'),
])
def test_addition_spellings_share_operands_without_mutation(
    scope_factory, source, left, right, expected,
):
    scope = scope_factory()
    scope['left'] = list(left) if isinstance(left, list) else left
    scope['right'] = list(right) if isinstance(right, list) else right
    result = core.execute(parse(source), scope)
    assert result == expected
    assert scope['left'] == left and scope['right'] == right
    if isinstance(left, list):
        assert type(result) is list
        assert result is not scope['left'] and result is not scope['right']


@pytest.mark.parametrize('scope_factory', [core.language_scope, library_scope])
def test_addition_aliases_retain_one_native_callable(scope_factory):
    scope = scope_factory()
    assert scope['add'] is scope['core-add'] is scope['+'].target


@pytest.mark.parametrize('source', [
    'add #[1] 2', 'core-add #[1] 2', '#[1] + 2',
])
def test_runner_list_plus_element(source):
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == [1, 2]


@pytest.mark.parametrize('source', [
    'add left right', 'core-add left right', 'left + right',
])
def test_addition_keeps_live_list_and_appended_host_object_live(source):
    raw = {
        'values': [1],
        'item': {'__slip__': {'type': 'scope', 'prototype': 'Item'}, 'hp': 10},
    }
    with ScriptRunner(host_data=lambda object_id: raw,
                      background_io=False) as runner:
        setup = runner.handle_script('''
            obj: host-object 'id:probe'
            left: obj.values
            right: obj.item
        ''')
        assert setup.status == 'ok', setup.error_message
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert type(result.value) is list and result.value[0] == 1
        assert len(result.value) == 2
        assert result.value[1] is runner.scope['right']
        assert raw['values'] == [1] and raw['item']['hp'] == 10
        result.value[1]['hp'] = 20
        assert raw['item']['hp'] == 20
        raw['values'] = [4]
        changed = runner.handle_script('left[0]: 5')
        assert changed.status == 'ok', changed.error_message
        assert raw['values'] == [5] and result.value[0] == 1
