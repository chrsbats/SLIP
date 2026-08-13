import ast
import asyncio
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from slip import ScriptRunner


ROOT = Path(__file__).parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / ".agents/skills/slip/SKILL.md",
    *sorted((ROOT / "docs").glob("*.md")),
]


@dataclass(frozen=True)
class SlipExample:
    path: Path
    line: int
    source: str
    expectation: str = "parse"
    setup: str | None = None

    @property
    def test_id(self):
        return f"{self.path.relative_to(ROOT)}:{self.line}"


def extract_code_examples(language):
    examples = []
    for path in DOCS:
        lines = path.read_text(encoding="utf-8").splitlines()
        start = None
        body = []
        expectation = "parse"
        setup = None
        for line_number, line in enumerate(lines, 1):
            if start is None:
                if line.strip() == "<!-- slip-test: parse-error -->":
                    expectation = "parse-error"
                    continue
                if line.strip() == "<!-- slip-test: runtime-error -->":
                    expectation = "runtime-error"
                    continue
                if line.strip() == "<!-- slip-test: fragment -->":
                    expectation = "fragment"
                    continue
                setup_prefix = "<!-- slip-test: setup="
                if (
                    line.strip().startswith(setup_prefix)
                    and line.strip().endswith(" -->")
                ):
                    setup = line.strip()[len(setup_prefix):-4]
                    continue
                if line.strip().startswith("```"):
                    if line.strip() == f"```{language}":
                        start = line_number + 1
                        body = []
                    else:
                        expectation = "parse"
                        setup = None
                continue
            if line.strip() == "```":
                examples.append(SlipExample(
                    path,
                    start,
                    "\n".join(body),
                    expectation,
                    setup,
                ))
                start = None
                body = []
                expectation = "parse"
                setup = None
            else:
                body.append(line)
        assert start is None, (
            f"unclosed SLIP fence in {path} at line {start - 1}"
        )
    return examples


EXAMPLES = extract_code_examples("slip")
PYTHON_EXAMPLES = extract_code_examples("python")
JSON_EXAMPLES = extract_code_examples("json")
BASH_EXAMPLES = extract_code_examples("bash")
ALL_EXAMPLES = EXAMPLES + PYTHON_EXAMPLES + JSON_EXAMPLES + BASH_EXAMPLES
PYTHON_EXECUTABLE_EXAMPLES = [
    example for example in PYTHON_EXAMPLES if example.expectation != "fragment"
]
PYTHON_EXPECTATIONS = {"parse", "fragment"}
UNKNOWN_PYTHON_EXPECTATIONS = {
    example.expectation
    for example in PYTHON_EXAMPLES
    if example.expectation not in PYTHON_EXPECTATIONS
}
if UNKNOWN_PYTHON_EXPECTATIONS:
    raise AssertionError(
        f"unknown Python documentation expectations: "
        f"{UNKNOWN_PYTHON_EXPECTATIONS}"
    )
PYTHON_SETUPS = {None, "command-module", "command-session"}
UNKNOWN_PYTHON_SETUPS = {
    example.setup
    for example in PYTHON_EXAMPLES
    if example.setup not in PYTHON_SETUPS
}
if UNKNOWN_PYTHON_SETUPS:
    raise AssertionError(
        f"unknown Python documentation setups: {UNKNOWN_PYTHON_SETUPS}"
    )


@dataclass(frozen=True)
class AssertionCase:
    example: SlipExample
    line: int
    source: str
    expected_source: str

    @property
    def test_id(self):
        return f"{self.example.path.relative_to(ROOT)}:{self.line}"


def _valid_slip(source):
    runner = ScriptRunner()
    parsed = runner.parser.parse(source)
    if (
        isinstance(parsed, dict)
        and parsed.get("status") in {"err", "error"}
    ):
        return False
    try:
        ast_value = parsed.get("ast") if isinstance(parsed, dict) else parsed
        runner.transformer.transform(ast_value)
    except Exception:
        return False
    return True


def extract_assertion_cases():
    cases = []
    for example in EXAMPLES:
        lines = example.source.splitlines()
        for index, line in enumerate(lines):
            comment = line.lstrip()
            if not comment.startswith("--"):
                continue
            comment = comment[2:].lstrip()
            if not comment.startswith("=>"):
                continue

            expected_parts = [comment[2:].strip()]
            if not expected_parts[0]:
                raise AssertionError(
                    f"empty documentation assertion at "
                    f"{example.path}:{example.line + index}"
                )

            continuation = index + 1
            while not _valid_slip("\n".join(expected_parts)):
                if continuation >= len(lines):
                    raise AssertionError(
                        f"incomplete documentation assertion at "
                        f"{example.path}:{example.line + index}"
                    )
                next_line = lines[continuation].lstrip()
                if not next_line.startswith("--"):
                    raise AssertionError(
                        f"incomplete documentation assertion at "
                        f"{example.path}:{example.line + index}"
                    )
                expected_parts.append(next_line[2:].lstrip())
                continuation += 1

            source = "\n".join(lines[:index])
            if not source.strip():
                raise AssertionError(
                    f"documentation assertion has no expression at "
                    f"{example.path}:{example.line + index}"
                )
            cases.append(AssertionCase(
                example,
                example.line + index,
                source,
                "\n".join(expected_parts),
            ))
    return cases


ASSERTION_CASES = extract_assertion_cases()
ASSERTION_SETUPS = {None, "math-module", "three-file-module", "item-host"}
UNKNOWN_ASSERTION_SETUPS = {
    case.example.setup
    for case in ASSERTION_CASES
    if case.example.setup not in ASSERTION_SETUPS
}
if UNKNOWN_ASSERTION_SETUPS:
    raise AssertionError(
        f"unknown documentation assertion setups: {UNKNOWN_ASSERTION_SETUPS}"
    )

ACTIVE_ASSERTION_COUNT = sum(
    1
    for path in DOCS
    for line in path.read_text(encoding="utf-8").splitlines()
    if line.lstrip().startswith("-- =>")
)
if len(ASSERTION_CASES) != ACTIVE_ASSERTION_COUNT:
    raise AssertionError(
        f"found {ACTIVE_ASSERTION_COUNT} active documentation assertions "
        f"but generated {len(ASSERTION_CASES)} semantic cases"
    )


def documented_example(relative_path, needle, occurrence=0):
    matches = [
        example
        for example in ALL_EXAMPLES
        if example.path == ROOT / relative_path and needle in example.source
    ]
    assert len(matches) > occurrence, (
        f"missing documented example {relative_path}: {needle!r}"
    )
    return matches[occurrence]


def assertion_runner(case, tmp_path):
    if case.example.setup == "math-module":
        (tmp_path / "math.slip").write_text("value: 7\n", encoding="utf-8")
        runner = ScriptRunner()
        runner.source_dir = str(tmp_path)
        return runner

    if case.example.setup == "three-file-module":
        combat = documented_example(
            "docs/02 SLIP Programs.md",
            "apply-damage: fn {state, target-id, amount}",
        )
        world = documented_example(
            "docs/02 SLIP Programs.md",
            "apply-damage: combat.apply-damage",
        )
        (tmp_path / "combat.slip").write_text(
            combat.source,
            encoding="utf-8",
        )
        (tmp_path / "world.slip").write_text(
            world.source,
            encoding="utf-8",
        )
        runner = ScriptRunner()
        runner.source_dir = str(tmp_path)
        return runner

    if case.example.setup == "item-host":
        registry = {
            "id:item-1": {
                "__slip__": {"type": "scope", "prototype": "Item"},
                "id": "id:item-1",
            },
        }
        return ScriptRunner(host_data=lambda object_id: registry[object_id])

    return ScriptRunner()


def assert_slip_equal(actual, expected):
    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected):
            assert_slip_equal(actual_item, expected_item)
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_slip_equal(actual[key], expected[key])
        return
    assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ASSERTION_CASES,
    ids=lambda case: case.test_id,
)
async def test_documentation_assertion(case, tmp_path):
    result = await assertion_runner(case, tmp_path).handle_script(case.source)
    assert result.status == "ok", f"{case.test_id}: {result.error_message}"

    expected = await ScriptRunner().handle_script(case.expected_source)
    assert expected.status == "ok", (
        f"{case.test_id} has an invalid expectation: {expected.error_message}"
    )
    assert expected.side_effects == [], (
        f"{case.test_id} expectation must be side-effect free"
    )
    try:
        assert_slip_equal(result.value, expected.value)
    except AssertionError as error:
        raise AssertionError(
            f"{case.test_id}: expected {expected.value!r}, "
            f"got {result.value!r}"
        ) from error


@pytest.mark.parametrize(
    "example",
    EXAMPLES,
    ids=lambda example: example.test_id,
)
def test_documentation_example_parses_and_transforms(example):
    runner = ScriptRunner()
    parsed = runner.parser.parse(example.source)
    failed = (
        isinstance(parsed, dict)
        and parsed.get("status") in {"err", "error"}
    )
    if example.expectation == "parse-error":
        assert failed, f"{example.test_id}: expected a parse error"
        return
    if failed:
        pytest.fail(f"{example.test_id}: {parsed}")
    ast = parsed.get("ast") if isinstance(parsed, dict) else parsed
    runner.transformer.transform(ast)


@pytest.mark.parametrize(
    "example",
    PYTHON_EXAMPLES,
    ids=lambda example: example.test_id,
)
def test_documentation_python_example_parses(example):
    ast.parse(example.source, filename=example.test_id)


def _write_python_command_module(tmp_path):
    (tmp_path / "command-api.slip").write_text(
        """Persona: scope #{}
Item: scope #{}

take-method: fn {actor: Persona, object: Item, original-text} [
    #[actor.name, object.name, original-text]
]

take: take-method |command |public
""",
        encoding="utf-8",
    )


def python_example_namespace(example, tmp_path, monkeypatch):
    namespace = {"__name__": "__main__"}
    if example.setup == "command-module":
        _write_python_command_module(tmp_path)
        monkeypatch.chdir(tmp_path)
    elif example.setup == "command-session":
        _write_python_command_module(tmp_path)
        registry = {
            "id:persona.1": {
                "__slip__": {"type": "scope", "prototype": "Persona"},
                "name": "Ada",
            },
            "id:item.apple.1": {
                "__slip__": {"type": "scope", "prototype": "Item"},
                "name": "apple",
            },
        }
        runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
        runner.source_dir = str(tmp_path)
        commands = asyncio.run(
            runner.import_public_module("file://command-api.slip")
        )
        namespace.update({
            "commands": commands,
            "session": SimpleNamespace(actor_id="id:persona.1"),
        })
    return namespace


@pytest.mark.parametrize(
    "example",
    PYTHON_EXECUTABLE_EXAMPLES,
    ids=lambda example: example.test_id,
)
def test_documentation_python_example_executes(example, tmp_path, monkeypatch):
    namespace = python_example_namespace(example, tmp_path, monkeypatch)
    compiled = compile(
        example.source,
        example.test_id,
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    result = eval(compiled, namespace)
    if inspect.isawaitable(result):
        asyncio.run(result)

    documented_result = namespace.get("result")
    if hasattr(documented_result, "status"):
        assert documented_result.status == "ok", (
            documented_result.error_message
        )


@pytest.mark.parametrize(
    "example",
    JSON_EXAMPLES,
    ids=lambda example: example.test_id,
)
def test_documentation_json_example_parses(example):
    json.loads(example.source)


@pytest.mark.parametrize(
    "example",
    BASH_EXAMPLES,
    ids=lambda example: example.test_id,
)
def test_documentation_bash_example_parses(example):
    completed = subprocess.run(
        ["bash", "-n"],
        input=example.source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, f"{example.test_id}: {completed.stderr}"


RUNTIME_ERROR_EXAMPLES = [
    example for example in EXAMPLES if example.expectation == "runtime-error"
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "example",
    RUNTIME_ERROR_EXAMPLES,
    ids=lambda example: example.test_id,
)
async def test_documentation_runtime_error_example_fails(example):
    result = await ScriptRunner().handle_script(example.source)
    assert result.status == "err", f"{example.test_id}: expected runtime error"


@dataclass(frozen=True)
class ExecutionCase:
    path: str
    needle: str
    expected: object
    setup: str = ""
    occurrence: int = 0

    @property
    def test_id(self):
        return f"{self.path}:{self.needle[:24]}"


EXECUTION_CASES = [
    ExecutionCase("docs/01 SLIP Scripting.md", 'name: "Karl"\nhp: 120', 120),
    ExecutionCase("docs/01 SLIP Scripting.md", "result: 10 + (5 * 2)", 20),
    ExecutionCase("docs/01 SLIP Scripting.md", "a: 1; b: 2", 2),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "path: '/tmp/data.json'",
        "/tmp/data.json",
    ),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "display-name: fn",
        "You take brass key.",
    ),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "nums: #[ 10, 20, 30 ]",
        [10, "Karl"],
    ),
    ExecutionCase("docs/01 SLIP Scripting.md", "add 10 20", 30),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "add-ten 5",
        15,
        setup="add-ten: fn {n} [ n + 10 ]",
    ),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "status: if [hp > 50]",
        "Wounded",
    ),
    ExecutionCase("docs/01 SLIP Scripting.md", "while [i > 0]", 0),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "wounded: players[.hp < 50]",
        ["Jaina"],
    ),
    ExecutionCase(
        "docs/01 SLIP Scripting.md",
        "report: #{",
        {"count": 1, "names": ["Jaina"]},
    ),
    ExecutionCase("docs/03 SLIP Advanced.md", "res: run [\n  x: 1", 3),
    ExecutionCase("docs/03 SLIP Advanced.md", "call add #[1, 2]", 3),
    ExecutionCase("docs/03 SLIP Advanced.md", "p: call 'a.b'", True),
    ExecutionCase("docs/03 SLIP Advanced.md", "op: `add`", 5),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "type-of #[1, 2, 3]",
        ["`list`", True, True],
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "to-str u8#[65, 66, 67]",
        "ABC",
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "from `json`",
        {"name": "Karl", "hp": 120},
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "call add #[1, 2]",
        3,
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "#[ is-list? #[]",
        [True, True, True],
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "join #['a', 'b', 'c']",
        "a, b, c",
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "split 'a,b,c'",
        ["a", "b", "c"],
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "replace 'foo bar foo'",
        "baz bar baz",
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "#[ range 3",
        [[0, 1, 2], [1, 2, 3], [1, 3]],
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "map (fn {x} [ x + 1 ])",
        [2, 3, 4],
        occurrence=0,
    ),
    ExecutionCase(
        "docs/Appendix A - StdLib Reference.md",
        "u8#[65, 66, 67]",
        b"ABC",
        occurrence=1,
    ),
    ExecutionCase(
        "docs/Appendix B - SLIP Style Guide.md",
        "MAX-HP: 1000",
        5,
    ),
    ExecutionCase(
        "docs/Appendix B - SLIP Style Guide.md",
        "cond: true",
        "yes",
    ),
    ExecutionCase(
        "docs/Appendix B - SLIP Style Guide.md",
        "-- This is a good comment.",
        10,
    ),
    ExecutionCase(
        "docs/Appendix B - SLIP Style Guide.md",
        "result: 10 + 5 * 2",
        20,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    EXECUTION_CASES,
    ids=lambda case: case.test_id,
)
async def test_documentation_example_executes(case):
    example = documented_example(case.path, case.needle, case.occurrence)
    source = (
        f"{case.setup}\n{example.source}"
        if case.setup
        else example.source
    )
    result = await ScriptRunner().handle_script(source)
    assert result.status == "ok", f"{example.test_id}: {result.error_message}"
    assert result.value == case.expected, example.test_id


@pytest.mark.asyncio
async def test_documented_validated_resolver_transaction():
    combat = documented_example(
        "docs/02 SLIP Programs.md",
        "Combat: resolver #{",
    )
    transaction = documented_example(
        "docs/02 SLIP Programs.md",
        'message: "damage must be positive"',
    )
    call = documented_example(
        "docs/02 SLIP Programs.md",
        'out: do [ Combat |apply-damage "p1" 10 ]',
    )
    result = await ScriptRunner().handle_script(
        "\n".join([
            combat.source,
            transaction.source,
            call.source,
            "out.value",
        ])
    )

    assert result.status == "ok", result.error_message
    assert result.value == 110


@pytest.mark.asyncio
async def test_documented_guarded_dispatch_uses_path_literal_kinds():
    combat = documented_example(
        "docs/02 SLIP Programs.md",
        "Combat: resolver #{",
    )
    fallback = documented_example(
        "docs/02 SLIP Programs.md",
        "apply-damage: fn {this: Combat, target-id, amount, kind} [",
    )
    guarded = documented_example(
        "docs/02 SLIP Programs.md",
        "kind = `physical`",
    )
    calls = documented_example(
        "docs/02 SLIP Programs.md",
        "Combat |apply-damage \"p1\" 10 `physical`",
    )
    result = await ScriptRunner().handle_script(
        "\n".join([
            combat.source,
            fallback.source,
            guarded.source,
            calls.source,
            'Combat.hp["p1"]',
        ])
    )

    assert result.status == "ok", result.error_message
    assert result.value == 90


@pytest.mark.asyncio
async def test_readme_taste_is_a_complete_runnable_example():
    example = documented_example(
        "README.md",
        "Character: scope #{}",
    )
    result = await ScriptRunner().handle_script(example.source)

    assert result.status == "ok", result.error_message
    assert result.value == [25, 100]
    assert [effect["message"] for effect in result.side_effects] == [
        "Goblin takes 5 poison damage.",
        "The stone Golem is immune to poison!",
    ]


@pytest.mark.asyncio
async def test_part_one_first_script_documents_stdout_effect():
    example = documented_example(
        "docs/01 SLIP Scripting.md",
        'name: "Karl"\nhp: 120',
    )
    result = await ScriptRunner().handle_script(example.source)

    assert result.status == "ok", result.error_message
    assert result.value == 120
    assert result.side_effects == [{
        "topics": ["stdout"],
        "message": "Karl has 120 HP",
    }]


@pytest.mark.asyncio
async def test_part_one_complete_json_file_workflow(tmp_path):
    example = documented_example(
        "docs/01 SLIP Scripting.md",
        "-- Read JSON.",
    )
    input_data = {
        "players": [
            {"name": "Karl", "hp": 120},
            {"name": "Jaina", "hp": 45},
        ]
    }
    (tmp_path / "input.json").write_text(
        json.dumps(input_data),
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    result = await runner.handle_script(example.source)

    assert result.status == "ok", result.error_message
    assert result.value == {"wounded-count": 1, "names": ["Jaina"]}
    written = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert written == result.value


@pytest.mark.asyncio
async def test_readme_for_example_emits_each_iteration():
    example = documented_example(
        "README.md",
        "for {i} 0 5",
    )
    result = await ScriptRunner().handle_script(example.source)

    assert result.status == "ok", result.error_message
    assert [effect["message"] for effect in result.side_effects] == [
        "The number is 0",
        "The number is 1",
        "The number is 2",
        "The number is 3",
        "The number is 4",
    ]


@pytest.mark.asyncio
async def test_best_practices_plain_function_example():
    example = documented_example(
        "docs/04 SLIP Best Practices.md",
        "apply-damage: fn {state, target-id, amount}",
    )
    result = await ScriptRunner().handle_script("\n".join([
        example.source,
        'state: #{ hp: #{ "p1": 100 } }',
        'out: apply-damage state "p1" 10',
        '#[state.hp["p1"], out]',
    ]))

    assert result.status == "ok", result.error_message
    assert result.value == [90, 90]


@pytest.mark.asyncio
async def test_best_practices_local_rebinding_example(tmp_path):
    example = documented_example(
        "docs/04 SLIP Best Practices.md",
        "better-combat: scope #{}",
    )
    (tmp_path / "combat.slip").write_text(
        """apply-damage: fn {state, target-id, amount} [
  state.hp[target-id]: state.hp[target-id] - amount
  state.hp[target-id]
]""",
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)
    result = await runner.handle_script("\n".join([
        example.source,
        'state: #{ hp: #{ "p1": 100 } }',
        'out: better-combat.apply-damage state "p1" 10',
        '#[state.hp["p1"], out]',
    ]))

    assert result.status == "ok", result.error_message
    assert result.value == [89, 89]


@pytest.mark.asyncio
async def test_best_practices_dispatch_example():
    example = documented_example(
        "docs/04 SLIP Best Practices.md",
        "kind = `fire`",
    )
    result = await ScriptRunner().handle_script("\n".join([
        'Combat: resolver #{ hp: #{ "p1": 120 } }',
        example.source,
        'Combat |apply-damage "p1" 10 `fire`',
        'Combat.hp["p1"]',
    ]))

    assert result.status == "ok", result.error_message
    assert result.value == 100


@pytest.mark.asyncio
async def test_best_practices_ref_and_cell_example():
    example = documented_example(
        "docs/04 SLIP Best Practices.md",
        "p1-hp: ref `Combat::hp",
    )
    result = await ScriptRunner().handle_script("\n".join([
        'Combat: resolver #{ hp: #{ "p1": 40 } }',
        example.source,
        '#[p1-hp, p1-wounded?]',
    ]))

    assert result.status == "ok", result.error_message
    assert result.value == [40, True]


@pytest.mark.asyncio
async def test_advanced_python_host_object_example():
    python_example = documented_example(
        "docs/03 SLIP Advanced.md",
        "class CharacterHost(SLIPHost):",
    )
    namespace = {}
    exec(python_example.source, namespace)
    runner = namespace["runner"]

    path_example = documented_example(
        "docs/03 SLIP Advanced.md",
        "obj.hp: 80",
    )
    result = await runner.handle_script(path_example.source)
    assert result.status == "ok", result.error_message
    assert result.value == 80

    method_example = documented_example(
        "docs/03 SLIP Advanced.md",
        "take-damage 3",
    )
    result = await runner.handle_script(method_example.source)
    assert result.status == "ok", result.error_message
    assert namespace["host"]._data["hp"] == 77


@pytest.mark.asyncio
async def test_advanced_public_module_example(tmp_path):
    command_api = documented_example(
        "docs/03 SLIP Advanced.md",
        "-- command-api.slip",
    )
    (tmp_path / "command-api.slip").write_text(
        command_api.source,
        encoding="utf-8",
    )
    (tmp_path / "movement.slip").write_text(
        """take: fn {actor-id, object-id} [ object-id ]
put: fn {actor-id, object-id, relation, target-id} [ target-id ]
internal-helper: fn {} [ none ]""",
        encoding="utf-8",
    )
    (tmp_path / "combat.slip").write_text(
        "attack: fn {actor-id, target-id} [ target-id ]",
        encoding="utf-8",
    )
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    commands = await runner.import_public_module("file://command-api.slip")

    assert set(commands.public_names()) == {"take", "put", "attack"}
    assert "internal-helper" not in commands.public_names()


@pytest.mark.asyncio
async def test_advanced_host_data_examples():
    registry = {
        "id:player-1": {
            "__slip__": {"type": "scope", "prototype": "Character"},
            "name": "Karl",
            "location": "room-1",
        },
        "id:goblin-1": {
            "__slip__": {"type": "scope", "prototype": "Character"},
            "name": "Goblin",
        },
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])

    raw_example = documented_example(
        "docs/03 SLIP Advanced.md",
        "raw: host-data 'id:player-1'",
    )
    result = await runner.handle_script(raw_example.source)
    assert result.status == "ok", result.error_message
    assert result.value == "room-1"

    as_slip_example = documented_example(
        "docs/03 SLIP Advanced.md",
        "obj: as-slip (host-data 'id:player-1')",
    )
    result = await runner.handle_script(as_slip_example.source)
    assert result.status == "ok", result.error_message
    assert result.value["name"] == "Karl"

    dispatch_example = documented_example(
        "docs/03 SLIP Advanced.md",
        'describe: fn {x: Character}',
    )
    result = await runner.handle_script(dispatch_example.source)
    assert result.status == "ok", result.error_message
    assert result.value == "typed"


@pytest.mark.asyncio
async def test_advanced_file_backed_code_template(tmp_path):
    template = documented_example(
        "docs/03 SLIP Advanced.md",
        "x: (inject module-x)",
    )
    caller = documented_example(
        "docs/03 SLIP Advanced.md",
        "module-x: 5",
    )
    (tmp_path / "mod.slip").write_text(template.source, encoding="utf-8")
    runner = ScriptRunner()
    runner.source_dir = str(tmp_path)

    result = await runner.handle_script(caller.source)

    assert result.status == "ok", result.error_message
    assert result.value == 32
