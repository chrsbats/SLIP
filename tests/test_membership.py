from collections import UserDict

import pytest

from slip import ScriptRunner
from slip.slip_core import Scope, execute
from slip.slip_library import library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize('container_type', [UserDict, Scope])
@pytest.mark.parametrize(('key', 'expected'), [
    ('present', True), ('missing', False),
])
@pytest.mark.parametrize('template', ["has data '{key}'", "'{key}' in data"])
def test_membership_checks_presence_without_reading_values(
    container_type, key, expected, template, runner,
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
    runner.root_scope['data'] = data
    result = runner.handle_script(template.format(key=key))
    assert result.status == 'ok', result.error_message
    assert result.value is expected
    assert checked == [key]


@pytest.mark.parametrize('child_source', [
    'create Parent [local: false; shadowed: none]', "host-object 'id:child'",
])
def test_scope_membership_preserves_lookup_rules(child_source):
    raw = {'__slip__': {'type': 'scope', 'prototype': 'Parent'},
           'local': False, 'shadowed': None}
    with ScriptRunner(host_data=lambda key: raw) as runner:
        result = runner.handle_script("""
            Parent: scope #{inherited: none, shadowed: true}
        """ + 'child: ' + child_source + """
            #[has child 'local', has child 'inherited', has child 'shadowed',
              has child 'meta', has child `local`, has child `inherited`,
              has child 'missing', has child `missing`, has child 1,
              has child '__slip__']
        """)
        assert result.status == 'ok', result.error_message
        assert result.value == [True, True, True, False, True, True,
                                False, False, False, False]


@pytest.mark.parametrize('child_source', [
    'create Parent [local: false; shadowed: none]', "host-object 'id:child'",
])
def test_in_uses_scope_contains_lookup(child_source):
    raw = {'__slip__': {'type': 'scope', 'prototype': 'Parent'},
           'local': False, 'shadowed': None}
    with ScriptRunner(host_data=lambda key: raw) as runner:
        result = runner.handle_script("""
            Parent: scope #{inherited: none, shadowed: true}
        """ + 'child: ' + child_source + """
            #['local' in child, 'inherited' in child, 'shadowed' in child,
              'meta' in child, 'missing' in child]
        """)
        assert result.status == 'ok', result.error_message
        assert result.value == [True, True, True, False, False]


def test_mapping_membership_uses_actual_key_types(runner):
    runner.root_scope['data'] = {1: None}
    result = runner.handle_script(
        "#[has data 1, has data '1', has data 2, 1 in data, '1' in data]",
    )
    assert result.status == 'ok', result.error_message
    assert result.value == [True, False, False, True, False]


@pytest.mark.parametrize(('source', 'expected'), [
    ("'present' in data", True), ("'missing' in data", False),
    ('1 in #[0, 1, 2]', True), ('4 in #[0, 1, 2]', False),
    ("'ell' in 'hello'", True), ("'xyz' in 'hello'", False),
])
def test_in_uses_python_containment(source, expected, runner):
    runner.root_scope['data'] = {'present': None}
    result = runner.handle_script(source)
    assert result.status == 'ok', result.error_message
    assert result.value is expected


def test_has_uses_python_containment_too(runner):
    result = runner.handle_script(
        "#[has #[0, 1] 1, has 'hello' 'ell', has #{present: none} 'present']",
    )
    assert result.status == 'ok', result.error_message
    assert result.value == [True, True, True]


@pytest.mark.parametrize('template', ["has data '{key}'", "'{key}' in data"])
def test_membership_does_not_swallow_storage_errors(template, runner):
    class Unavailable(UserDict):
        def __contains__(self, key):
            raise RuntimeError('storage unavailable')

    runner.root_scope['data'] = Unavailable({'present': None})
    result = runner.handle_script(template.format(key='present'))
    assert result.status == 'err'
    assert 'storage unavailable' in result.error_message


@pytest.mark.parametrize('bootstrap', ['native', 'runner'])
def test_native_membership_prefix_pipe_and_core_binding(bootstrap, runner):
    source = """
        data: #{present: none, disabled: false}
        #[has data 'present', data |has 'disabled', core-has data 'missing',
          'present' in data, 'missing' in data]
    """
    if bootstrap == 'runner':
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        value, scope = result.value, runner.root_scope
    else:
        scope = library_scope()
        value = execute(parse(source), Scope(parent=scope))
    assert value == [True, True, False, True, False]
    assert scope['has'] is scope['core-has']
    assert scope['contains'] is scope['core-contains']
    assert 'in' in scope.bindings and 'core-in' not in scope.bindings
    assert not any('?' in name or 'has-key' in name for name in scope.bindings)


def test_bare_native_core_exposes_membership():
    scope = Scope(parent=library_scope())
    assert execute(parse("has #{present: none} 'present'"), scope) is True
    assert scope['has'] is scope['core-has']
    assert scope['contains'] is scope['core-contains']
    assert not any('?' in name for name in scope.root.bindings)


def test_core_membership_survives_local_shadowing(runner):
    result = runner.handle_script("""
        has: fn {data, key} [false]
        #[has #{present: none} 'present', core-has #{present: none} 'present']
    """)
    assert result.status == 'ok', result.error_message
    assert result.value == [False, True]


@pytest.mark.parametrize('source', ["has none 'key'", "'key' in none",
                                    "'key' in 1"])
def test_membership_rejects_non_containers_with_python_errors(source, runner):
    result = runner.handle_script(source)
    assert result.status == 'err'
    assert 'not iterable' in result.error_message
