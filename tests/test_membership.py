from collections import UserDict

import pytest

from slip import ScriptRunner
from slip.slip_datatypes import Scope
from slip.slip_interpreter import Evaluator
from slip.slip_runtime import StdLib


@pytest.mark.asyncio
@pytest.mark.parametrize('container_type', [UserDict, Scope])
@pytest.mark.parametrize('key, expected', [
    ('present', True), ('missing', False),
])
@pytest.mark.parametrize('template', [
    "has data '{key}'",
    "'{key}' in data",
])
async def test_membership_checks_presence_without_reading_values(
    container_type, key, expected, template
):
    checked = []

    class MembershipOnly(container_type):
        def __contains__(self, key):
            checked.append(key)
            return super().__contains__(key)

        def __getitem__(self, key):
            raise AssertionError('membership must not fetch a value')

    data = MembershipOnly()
    data['present'] = None
    runner = ScriptRunner()
    runner.root_scope['data'] = data

    result = await runner.handle_script(template.format(key=key))

    assert result.status == 'ok', result.error_message
    assert result.value is expected
    assert checked == [key]


@pytest.mark.asyncio
@pytest.mark.parametrize('child_source', [
    'create Parent [local: false; shadowed: none]',
    "host-object 'id:child'",
])
async def test_scope_membership_preserves_lookup_rules(child_source):
    raw = {
        '__slip__': {'type': 'scope', 'prototype': 'Parent'},
        'local': False,
        'shadowed': None,
    }
    runner = ScriptRunner(host_data=lambda _object_id: raw)
    result = await runner.handle_script("""
    Parent: scope #{inherited: none, shadowed: true}
    """ + f"child: {child_source}\n" + """
    #[
        has child 'local',
        has child 'inherited',
        has child 'shadowed',
        has child 'meta',
        has child `local`,
        has child `inherited`,
        has child 'missing',
        has child `missing`,
        has child 1,
        has child '__slip__'
    ]
    """)

    assert result.status == 'ok', result.error_message
    assert result.value == [
        True, True, True, False, True, True, False, False, False, False,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize('child_source', [
    'create Parent [local: false; shadowed: none]',
    "host-object 'id:child'",
])
async def test_in_uses_scope_contains_lookup(child_source):
    raw = {
        '__slip__': {'type': 'scope', 'prototype': 'Parent'},
        'local': False,
        'shadowed': None,
    }
    runner = ScriptRunner(host_data=lambda _object_id: raw)
    result = await runner.handle_script("""
    Parent: scope #{inherited: none, shadowed: true}
    """ + f"child: {child_source}\n" + """
    #[
        'local' in child,
        'inherited' in child,
        'shadowed' in child,
        'meta' in child,
        'missing' in child
    ]
    """)

    assert result.status == 'ok', result.error_message
    assert result.value == [True, True, True, False, False]


@pytest.mark.asyncio
async def test_mapping_membership_uses_actual_key_types():
    runner = ScriptRunner()
    runner.root_scope['data'] = {1: None}

    result = await runner.handle_script(
        "#[has data 1, has data '1', has data 2, 1 in data, '1' in data]"
    )

    assert result.status == 'ok', result.error_message
    assert result.value == [True, False, False, True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize('source, expected', [
    ("'present' in data", True),
    ("'missing' in data", False),
    ("1 in #[0, 1, 2]", True),
    ("4 in #[0, 1, 2]", False),
    ("'ell' in 'hello'", True),
    ("'xyz' in 'hello'", False),
])
async def test_in_uses_python_containment(source, expected):
    runner = ScriptRunner()
    runner.root_scope['data'] = {'present': None}

    result = await runner.handle_script(source)

    assert result.status == 'ok', result.error_message
    assert result.value is expected


@pytest.mark.asyncio
async def test_has_uses_python_containment_too():
    result = await ScriptRunner().handle_script(
        "#[has #[0, 1] 1, has 'hello' 'ell', has #{present: none} 'present']"
    )

    assert result.status == 'ok', result.error_message
    assert result.value == [True, True, True]


@pytest.mark.asyncio
@pytest.mark.parametrize('template', [
    "has data '{key}'",
    "'{key}' in data",
])
async def test_membership_does_not_swallow_storage_errors(template):
    class Unavailable(UserDict):
        def __contains__(self, key):
            raise RuntimeError('storage unavailable')

    runner = ScriptRunner()
    runner.root_scope['data'] = Unavailable({'present': None})

    result = await runner.handle_script(template.format(key='present'))

    assert result.status == 'err'
    assert 'storage unavailable' in result.error_message


@pytest.mark.asyncio
@pytest.mark.parametrize('load_core', [False, True])
async def test_native_membership_prefix_pipe_and_core_binding(load_core):
    runner = ScriptRunner(load_core=load_core)
    in_checks = ", 'present' in data, 'missing' in data" if load_core else ""

    result = await runner.handle_script(f"""
    data: #{{present: none, disabled: false}}
    #[has data 'present', data |has 'disabled', core-has data 'missing'{in_checks}]
    """)

    expected = [True, True, False]
    if load_core:
        expected.extend([True, False])
    assert result.status == 'ok', result.error_message
    assert result.value == expected
    assert runner.root_scope['has'] is runner.root_scope['core-has']
    assert runner.root_scope['contains'] is runner.root_scope['core-contains']
    assert ('in' in runner.root_scope.bindings) is load_core
    assert 'core-in' not in runner.root_scope.bindings
    assert not any('?' in name for name in runner.root_scope.bindings)
    assert not any('has-key' in name for name in runner.root_scope.bindings)


@pytest.mark.asyncio
async def test_bare_evaluator_exposes_native_membership():
    evaluator = Evaluator()
    StdLib(evaluator)
    scope = Scope(parent=evaluator.core_scope)
    runner = ScriptRunner()
    parsed = runner.parser.parse("has #{present: none} 'present'")
    code = runner.transformer.transform(parsed['ast'])

    result = await evaluator.eval(code.nodes, scope)

    assert result is True
    assert evaluator.core_scope['has'] is evaluator.core_scope['core-has']
    assert evaluator.core_scope['contains'] is evaluator.core_scope['core-contains']
    assert not any('?' in name for name in evaluator.core_scope.bindings)


@pytest.mark.asyncio
async def test_core_membership_survives_local_shadowing():
    result = await ScriptRunner().handle_script("""
    has: fn {data, key} [false]
    #[has #{present: none} 'present', core-has #{present: none} 'present']
    """)

    assert result.status == 'ok', result.error_message
    assert result.value == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize('source', [
    "has none 'key'",
    "'key' in none",
    "'key' in 1",
])
async def test_membership_rejects_non_containers_with_python_errors(source):
    result = await ScriptRunner().handle_script(source)

    assert result.status == 'err'
    assert 'not iterable' in result.error_message
