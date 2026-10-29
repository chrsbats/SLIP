"""Retained public capture/laziness assertions in explicit current syntax."""

import pytest

from slip import ScriptRunner


@pytest.mark.parametrize(('expression', 'expected', 'reads'), [
    ("0 |core-add values[(probe 'answer')]", 7, 1),
    ("saved: values[(probe 'answer')]", 7, 1),
    ("false and values[(probe 'answer')]", False, 0),
    ("true or values[(probe 'answer')]", True, 0),
    ('false and (1 + (probe 7))', False, 0),
    ('true or ((probe 1) |core-add (probe 7))', True, 0),
])
def test_computed_keys_and_grouped_logical_operands_execute_once(
    expression, expected, reads,
):
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            state: scope #{reads: 0}
            probe: fn {value} [
                state.reads: + 1
                emit 'probe' value
                return value
            ]
            values: #{answer: 7}
        ''' + expression)
        assert result.status == 'ok', result.error_message
        assert result.value == expected
        assert runner.scope['state']['reads'] == reads
        assert result.side_effects == (
            [{'topics': ['probe'], 'message': 'answer'}] if reads else []
        )


def test_computed_callable_selection_precedes_its_argument_effects():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            choose-op: fn {} [
                emit 'probe' 'operator'
                core-function `core-add`
            ]
            probe: fn {value} [emit 'probe' value; return value]
            call (choose-op) #[1, (probe 3)]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == 4
        assert result.side_effects == [
            {'topics': ['probe'], 'message': 'operator'},
            {'topics': ['probe'], 'message': 3},
        ]


@pytest.mark.parametrize(('body', 'expected'), [
    ('xs[(selector 1 1)]', 30),
    ('xs[(selector 1 1)]: 99; xs', [10, 20, 99, 40]),
    ('~xs[(selector 1 1)]; xs', [10, 20, 40]),
    ('[xs[(selector 1 1)], other]: #[77, 88]; #[xs, other]',
     [[10, 20, 77, 40], 88]),
])
def test_index_operations_retain_the_captured_selector(body, expected):
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            selector: core-function `core-add`
        ''' + 'probe: fn {xs} [' + body + ''']
            selector: core-function `core-sub`
            probe #[10, 20, 30, 40]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_filter_interpolation_and_guards_keep_captures_after_rebinding():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            target: core-function `core-add`
            accept: core-function `core-gt`
            choose: fn {xs} [xs[.hp > 1]]
            describe: fn {x} ["answer {{target x 1}}"]
            positive: fn {x} [false]
            positive: fn {x |where accept x 0} [true]
            target: core-function `core-sub`
            accept: core-function `core-lt`
            />: |core-lt
            #[choose #[#{hp: 0}, #{hp: 2}],
              describe 10, describe 20, positive 1]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [[{'hp': 2}], 'answer 11', 'answer 21', True]


def test_separately_attached_guard_keeps_its_definition_time_capture():
    with ScriptRunner(background_io=False) as runner:
        result = runner.handle_script('''
            accept: core-function `core-gt`
            positive: fn {x} [false]
            positive: fn {x} [true] |where [accept x 0]
            accept: core-function `core-lt`
            positive 1
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value is True
