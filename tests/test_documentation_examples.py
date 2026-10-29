"""Execute the current guides through the shipped synchronous package."""

import ast
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from slip import PublicModule, ScriptRunner
from slip.slip_core import Path as SlipPath, PathLiteral
from slip.slip_syntax import parse


ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / 'README.md', ROOT / '.agents/skills/slip/SKILL.md',
        *sorted((ROOT / 'docs').glob('*.md'))]


@dataclass(frozen=True)
class Example:
    path: Path
    line: int
    source: str
    expectation: str = 'parse'
    setup: str | None = None

    @property
    def test_id(self):
        return f'{self.path.relative_to(ROOT)}:{self.line}'


def extract_examples(language):
    examples = []
    for path in DOCS:
        start, body, expectation, setup = None, [], 'parse', None
        for number, line in enumerate(path.read_text().splitlines(), 1):
            text = line.strip()
            if start is None:
                if (text.startswith('<!-- slip-test: ')
                        and text.endswith(' -->')):
                    instruction = text[len('<!-- slip-test: '):-4]
                    if instruction.startswith('setup='):
                        setup = instruction[6:]
                    else:
                        assert instruction in {
                            'parse-error', 'runtime-error', 'fragment',
                        }, (path, number, instruction)
                        expectation = instruction
                elif text == '```' + language:
                    start, body = number + 1, []
                elif text.startswith('```'):
                    expectation, setup = 'parse', None
            elif text == '```':
                examples.append(Example(path, start, '\n'.join(body),
                                        expectation, setup))
                start, expectation, setup = None, 'parse', None
            else:
                body.append(line)
        assert start is None, f'unclosed fence: {path}:{start}'
    return examples


SLIP = extract_examples('slip')
PYTHON = extract_examples('python')
JSON = extract_examples('json')
BASH = extract_examples('bash')
ALL = SLIP + PYTHON + JSON + BASH


def documented(path, needle, occurrence=0):
    matches = [example for example in ALL
               if example.path == ROOT / path and needle in example.source]
    assert len(matches) > occurrence, f'missing example: {path}: {needle}'
    return matches[occurrence].source


def valid(source):
    try:
        parse(source)
    except SyntaxError:
        return False
    return True


def assertions():
    cases = []
    for example in SLIP:
        lines = example.source.splitlines()
        for index, line in enumerate(lines):
            if not line.lstrip().startswith('-- =>'):
                continue
            expected = line.lstrip()[5:].strip()
            assert expected, example.test_id
            continuation = index + 1
            while not valid(expected):
                assert continuation < len(lines), example.test_id
                following = lines[continuation].lstrip()
                assert following.startswith('--'), example.test_id
                expected += '\n' + following[2:].lstrip()
                continuation += 1
            cases.append((example, '\n'.join(lines[:index]), expected))
    count = sum(line.lstrip().startswith('-- =>') for path in DOCS
                for line in path.read_text().splitlines())
    assert len(cases) == count, 'every active result marker must execute'
    return cases


ASSERTIONS = assertions()


@pytest.fixture
def runner():
    with ScriptRunner(background_io=False) as value:
        yield value


def prepare_assertion(example, tmp_path):
    assert example.setup in {
        None, 'math-module', 'three-file-module', 'item-host',
    }, example.test_id
    if example.setup == 'math-module':
        (tmp_path / 'math.slip').write_text('value: 7')
    elif example.setup == 'three-file-module':
        (tmp_path / 'combat.slip').write_text(documented(
            'docs/02 SLIP Programs.md',
            'apply-damage: fn {state, target-id, amount}',
        ))
        (tmp_path / 'world.slip').write_text(documented(
            'docs/02 SLIP Programs.md', 'apply-damage: core-function',
        ))
    registry = {'id:item-1': {
        '__slip__': {'type': 'scope', 'prototype': 'Item'}, 'id': 'id:item-1',
    }}
    result = ScriptRunner(host_data=registry.__getitem__, background_io=False)
    result.source_dir = str(tmp_path)
    return result


def assert_equal(actual, expected):
    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_equal(left, right)
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key in expected:
            assert_equal(actual[key], expected[key])
    else:
        assert actual == expected


@pytest.mark.parametrize('case', ASSERTIONS,
                         ids=lambda case: case[0].test_id)
def test_documentation_assertion(case, tmp_path):
    example, source, expectation = case
    with prepare_assertion(example, tmp_path) as runner:
        result = runner.handle_script(source)
    assert result.status == 'ok', f'{example.test_id}: {result.error_message}'
    with ScriptRunner(background_io=False) as runner:
        expected = runner.handle_script(expectation)
    assert expected.status == 'ok', expected.error_message
    assert expected.side_effects == []
    assert_equal(result.value, expected.value)


@pytest.mark.parametrize('example', SLIP, ids=lambda value: value.test_id)
def test_documentation_example_parses_and_transforms(example):
    if example.expectation == 'parse-error':
        with pytest.raises(SyntaxError):
            parse(example.source)
    else:
        parse(example.source)


@pytest.mark.parametrize('example', PYTHON, ids=lambda value: value.test_id)
def test_documentation_python_example_parses(example):
    ast.parse(example.source, filename=example.test_id)


def write_command_module(tmp_path):
    (tmp_path / 'command-api.slip').write_text('''
        Persona: scope #{}
        Item: scope #{}
        take-method: fn {actor: Persona, object: Item, original-text} [
            #[actor.name, object.name, original-text]
        ]
        take: command take-method |public
    ''')


@pytest.mark.parametrize(
    'example', [e for e in PYTHON if e.expectation != 'fragment'],
    ids=lambda value: value.test_id,
)
def test_documentation_python_example_executes(example, tmp_path, monkeypatch):
    assert example.setup in {None, 'command-module', 'command-session'}
    namespace = {'__name__': '__main__'}
    if example.setup:
        write_command_module(tmp_path)
        monkeypatch.chdir(tmp_path)
    if example.setup == 'command-session':
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
        runner = ScriptRunner(host_data=registry.__getitem__,
                              background_io=False)
        runner.source_dir = str(tmp_path)
        namespace.update(commands=runner.import_public_module(
            'file://command-api.slip',
        ), session=SimpleNamespace(actor_id='id:persona.1'))
    try:
        exec(compile(example.source, example.test_id, 'exec'), namespace)
        result = namespace.get('result')
        if hasattr(result, 'status'):
            assert result.status == 'ok', result.error_message
    finally:
        for value in namespace.values():
            if isinstance(value, ScriptRunner):
                value.close()
            elif isinstance(value, PublicModule):
                value.runner.close()


@pytest.mark.parametrize('example', JSON, ids=lambda value: value.test_id)
def test_documentation_json_example_parses(example):
    json.loads(example.source)


@pytest.mark.parametrize('example', BASH, ids=lambda value: value.test_id)
def test_documentation_bash_example_parses(example):
    result = subprocess.run(['bash', '-n'], input=example.source, text=True,
                            capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    'example', [e for e in SLIP if e.expectation == 'runtime-error'],
    ids=lambda value: value.test_id,
)
def test_documentation_runtime_error_example_fails(example, runner):
    assert runner.handle_script(example.source).status == 'err'


@pytest.mark.parametrize('path, needle, expected, setup, occurrence', [
    ('docs/01 SLIP Scripting.md', 'name: "Karl"\nhp: 120', 120, '', 0),
    ('docs/01 SLIP Scripting.md', 'result: 10 + (5 * 2)', 20, '', 0),
    ('docs/01 SLIP Scripting.md', 'a: 1; b: 2', 2, '', 0),
    ('docs/01 SLIP Scripting.md', "path: '/tmp/data.json'",
     '/tmp/data.json', '', 0),
    ('docs/01 SLIP Scripting.md', 'display-name: fn',
     'You take brass key.', '', 0),
    ('docs/01 SLIP Scripting.md', 'nums: #[ 10, 20, 30 ]',
     [10, 'Karl'], '', 0),
    ('docs/01 SLIP Scripting.md', 'add 10 20', 30, '', 0),
    ('docs/01 SLIP Scripting.md', 'add-ten 5', 15,
     'add-ten: fn {n} [n + 10]', 0),
    ('docs/01 SLIP Scripting.md', 'status: if [hp > 50]', 'Wounded', '', 0),
    ('docs/01 SLIP Scripting.md', 'while [i > 0]', 0, '', 0),
    ('docs/01 SLIP Scripting.md', 'wounded: players[.hp < 50]',
     ['Jaina'], '', 0),
    ('docs/01 SLIP Scripting.md', 'report: #{',
     {'count': 1, 'names': ['Jaina']}, '', 0),
    ('docs/03 SLIP Advanced.md', 'res: run [\n  x: 1', 3, '', 0),
    ('docs/03 SLIP Advanced.md', 'call add #[1, 2]', 3, '', 0),
    ('docs/03 SLIP Advanced.md', "p: to-path 'a.b'", True, '', 0),
    ('docs/03 SLIP Advanced.md', 'op: `add`', 5, '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'type-of #[1, 2, 3]',
     [PathLiteral(SlipPath(['list'])), True, True], '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'to-str u8#[65, 66, 67]',
     'ABC', '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'from `json`',
     {'name': 'Karl', 'hp': 120}, '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'call add #[1, 2]', 3, '', 0),
    ('docs/Appendix A - StdLib Reference.md', '#[ is-list #[]',
     [True, True, True], '', 0),
    ('docs/Appendix A - StdLib Reference.md', "join #['a', 'b', 'c']",
     'a, b, c', '', 0),
    ('docs/Appendix A - StdLib Reference.md', "split 'a,b,c'",
     ['a', 'b', 'c'], '', 0),
    ('docs/Appendix A - StdLib Reference.md', "replace 'foo bar foo'",
     'baz bar baz', '', 0),
    ('docs/Appendix A - StdLib Reference.md', '#[ range 3',
     [[0, 1, 2], [1, 2, 3], [1, 3]], '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'map (fn {x} [ x + 1 ])',
     [2, 3, 4], '', 0),
    ('docs/Appendix A - StdLib Reference.md', 'u8#[65, 66, 67]',
     b'ABC', '', 1),
    ('docs/Appendix B - SLIP Style Guide.md', 'MAX-HP: 1000', 5, '', 0),
    ('docs/Appendix B - SLIP Style Guide.md', 'cond: true', 'yes', '', 0),
    ('docs/Appendix B - SLIP Style Guide.md', '-- This is a good comment.',
     10, '', 0),
    ('docs/Appendix B - SLIP Style Guide.md', 'result: 10 + 5 * 2', 20, '', 0),
])
def test_documentation_example_executes(
    path, needle, expected, setup, occurrence, runner,
):
    result = runner.handle_script(setup + '\n' + documented(
        path, needle, occurrence,
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == expected


def test_readme_taste_and_for_effects(runner):
    result = runner.handle_script(documented(
        'README.md', 'Character: scope #{}',
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == [25, 100]
    assert [effect['message'] for effect in result.side_effects] == [
        'Goblin takes 5 poison damage.',
        'The stone Golem is immune to poison!',
    ]
    result = runner.handle_script(documented('README.md', 'for {i} 0 5'))
    assert result.status == 'ok', result.error_message
    assert [e['message'] for e in result.side_effects] == [
        f'The number is {i}' for i in range(5)
    ]


def test_part_one_stdout_and_file_workflow(runner, tmp_path):
    result = runner.handle_script(documented(
        'docs/01 SLIP Scripting.md', 'name: "Karl"\nhp: 120',
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == 120
    assert result.side_effects == [{'topics': ['stdout'],
                                   'message': 'Karl has 120 HP'}]
    (tmp_path / 'input.json').write_text(json.dumps({'players': [
        {'name': 'Karl', 'hp': 120}, {'name': 'Jaina', 'hp': 45},
    ]}))
    runner.source_dir = str(tmp_path)
    result = runner.handle_script(documented(
        'docs/01 SLIP Scripting.md', '-- Read JSON.',
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == {'wounded-count': 1, 'names': ['Jaina']}
    assert json.loads((tmp_path / 'out.json').read_text()) == result.value


def test_best_practices_plain_function_and_local_rebinding(runner, tmp_path):
    source = documented('docs/04 SLIP Best Practices.md',
                        'apply-damage: fn {state, target-id, amount}')
    call = ('\nstate: #{hp: #{p1: 100}}; '
            "out: apply-damage state 'p1' 10; #[state.hp.p1, out]")
    result = runner.handle_script(source + call)
    assert result.status == 'ok', result.error_message
    assert result.value == [90, 90]
    (tmp_path / 'combat.slip').write_text(source)
    runner.source_dir = str(tmp_path)
    source = documented('docs/04 SLIP Best Practices.md',
                        'better-combat: scope #{}')
    result = runner.handle_script(source + call.replace(
        'out: apply-damage', 'out: better-combat.apply-damage',
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == [89, 89]


def test_documented_guarded_dispatch_uses_path_literal_kinds(runner):
    result = runner.handle_script('\n'.join([
        'Combat: scope #{hp: #{p1: 120}}',
        documented(
            'docs/02 SLIP Programs.md',
            'apply-damage: fn {this: Combat, target-id, amount, kind} [',
        ),
        documented('docs/02 SLIP Programs.md', 'kind = `physical`'),
        documented('docs/02 SLIP Programs.md',
                   'Combat |apply-damage "p1" 10 `physical`'),
        'Combat.hp.p1',
    ]))
    assert result.status == 'ok', result.error_message
    assert result.value == 90


def test_best_practices_dispatch_example(runner):
    result = runner.handle_script('\n'.join([
        'Combat: scope #{hp: #{p1: 120}}',
        documented('docs/04 SLIP Best Practices.md', 'kind = `fire`'),
        "Combat |apply-damage 'p1' 10 `fire`",
        'Combat.hp.p1',
    ]))
    assert result.status == 'ok', result.error_message
    assert result.value == 100


def test_best_practices_ref_and_cell_example(runner):
    result = runner.handle_script('\n'.join([
        'Combat: scope #{hp: #{p1: 40}}',
        documented('docs/04 SLIP Best Practices.md', 'p1-hp: ref `Combat::hp'),
        '#[p1-hp, p1-wounded?]',
    ]))
    assert result.status == 'ok', result.error_message
    assert result.value == [40, True]


def test_advanced_python_host_example():
    namespace = {}
    exec(documented('docs/03 SLIP Advanced.md',
                    'class CharacterHost(SLIPHost):'), namespace)
    assert namespace['result'].status == 'ok'
    assert namespace['result'].value == 77
    with ScriptRunner(host_object=namespace['host'], background_io=False) as r:
        r.root_scope['obj'] = namespace['host']
        result = r.handle_script(documented(
            'docs/03 SLIP Advanced.md', 'obj.hp: 80',
        ))
        assert result.status == 'ok', result.error_message
        assert result.value == 80
        result = r.handle_script(documented(
            'docs/03 SLIP Advanced.md', 'take-damage 3',
        ))
        assert result.status == 'ok', result.error_message
        assert namespace['host']._data['hp'] == 77


def test_advanced_public_module_example(runner, tmp_path):
    (tmp_path / 'command-api.slip').write_text(documented(
        'docs/03 SLIP Advanced.md', '-- command-api.slip',
    ))
    (tmp_path / 'movement.slip').write_text('''
        take: fn {actor-id, object-id} [object-id]
        put: fn {actor-id, object-id, relation, target-id} [target-id]
        internal-helper: fn {} [none]
    ''')
    (tmp_path / 'combat.slip').write_text(
        'attack: fn {actor-id, target-id} [target-id]',
    )
    runner.source_dir = str(tmp_path)
    commands = runner.import_public_module('file://command-api.slip')
    assert set(commands.public_names()) == {'take', 'put', 'attack'}
    assert 'internal-helper' not in commands.public_names()


def test_advanced_host_data_examples():
    registry = {'id:player-1': {
        '__slip__': {'type': 'scope', 'prototype': 'Character'},
        'name': 'Karl', 'location': 'room-1',
    }}
    with ScriptRunner(host_data=registry.__getitem__,
                      background_io=False) as r:
        for needle, expected in [("raw: host-data 'id:player-1'", 'room-1'),
                                 ('obj: as-slip', None),
                                 ('describe: fn {x: Character}', 'typed')]:
            result = r.handle_script(documented(
                'docs/03 SLIP Advanced.md', needle,
            ))
            assert result.status == 'ok', result.error_message
            if expected is None:
                assert result.value['name'] == 'Karl'
            else:
                assert result.value == expected


def test_advanced_file_backed_code_template(runner, tmp_path):
    (tmp_path / 'mod.slip').write_text(documented(
        'docs/03 SLIP Advanced.md', 'x: (inject module-x)',
    ))
    runner.source_dir = str(tmp_path)
    result = runner.handle_script(documented(
        'docs/03 SLIP Advanced.md', 'module-x: 5',
    ))
    assert result.status == 'ok', result.error_message
    assert result.value == 32
