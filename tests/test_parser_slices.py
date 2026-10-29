"""Lower slice bounds stop at the delimiter, including computed path bases."""

from pathlib import Path

from koine import Parser
import pytest

from slip import ScriptRunner


@pytest.fixture(scope='module')
def parser():
    grammar = Path(__file__).resolve().parents[1] / 'grammar/slip_grammar.yaml'
    return Parser.from_file(str(grammar))


@pytest.mark.parametrize('lower', [
    'start', '(probe 0)', 'bounds[0]', '(bounds).start',
    '(start: 0; start)', '0 + 1',
])
def test_lower_bounds_are_expressions_before_the_slice_delimiter(
    parser, lower,
):
    source = f'xs[{lower}:(probe 2)]'
    result = parser.parse(source)
    assert result['status'] == 'success', result
    path = result['ast']['children'][0]['children'][0]
    query = path['children'][1]['children'][0]
    assert query['tag'] == 'slice-query'
    start, end = query['children']
    assert start['tag'] == 'start-expr' and start['text'] == lower
    assert end['tag'] == 'end-expr' and end['text'] == '(probe 2)'


def test_computed_slice_bounds_execute_once_with_query_assignment():
    with ScriptRunner() as runner:
        result = runner.handle_script('''
            state: scope #{calls: 0}
            probe: fn {value} [state.calls: + 1; return value]
            rows: #[#{n: 1}, #{n: 2}, #{n: 3}]
            rows[(probe 0):(probe 2)].n: (probe #[7, 9])
            #[state.calls, rows.n]
        ''')
        assert result.status == 'ok', result.error_message
        assert result.value == [3, [7, 9, 3]]
