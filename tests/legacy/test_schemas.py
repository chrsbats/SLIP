"""Synchronous chapter 009 validation and normalization assertions."""

import pytest

from slip.slip_core import Path, PathLiteral
from slip import ScriptRunner


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("UserSchema: schema #{name: `string`, age: `number`}; "
                 "#[is-schema UserSchema, is-a UserSchema Schema, "
                 "is-scope UserSchema]", [True, True, True], id="creation"),
    pytest.param("UserSchema: schema #{name: `string`}; "
                 "raw: #{name: 'Alice'}; raw |validate UserSchema",
                 {'name': 'Alice'}, id="pipe_validation"),
    pytest.param("UserSchema: schema #{name: `string`}; "
                 "raw: #{name: 'Alice'}; validate raw UserSchema",
                 {'name': 'Alice'}, id="prefix_validation"),
    pytest.param("ConfigSchema: schema #{host: `string`, port: default 8080, "
                 "user: optional `string`}; is-schema ConfigSchema", True,
                 id="default_optional_construction"),
    pytest.param("ContactInfoSchema: schema #{email: `string`}; "
                 "UserSchema: create ContactInfoSchema [name: `string`]; "
                 "TeamSchema: schema #{team-name: `string`, "
                 "leader: `UserSchema`, members: `list`}; "
                 "#[is-schema ContactInfoSchema, is-schema UserSchema, "
                 "is-a UserSchema ContactInfoSchema, is-schema TeamSchema]",
                 [True] * 4, id="composition_inheritance"),
    pytest.param("Base: schema #{port: default 80, "
                 "host: default 'localhost'}; "
                 "Child: scope #{port: default 8080} |inherit Base; "
                 "validate #{} Child", {'port': 8080, 'host': 'localhost'},
                 id="child_default_overrides_parent"),
    pytest.param("Address: schema #{zip: `int`, country: default 'GB'}; "
                 "Profile: schema #{name: `string`, "
                 "address: optional Address, "
                 "nickname: optional `string`, active: default true}; "
                 "#[validate #{name: 'Ada', address: #{zip: 123}} Profile, "
                 "validate #{name: 'Grace', active: false} Profile]", [
                     {'name': 'Ada', 'address': {'zip': 123, 'country': 'GB'},
                      'active': True},
                     {'name': 'Grace', 'active': False},
                 ], id="nested_optional_defaults_and_false"),
])
def test_values(source, expected):
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == 'ok', result.error_message
        assert result.value == expected


def test_nested_errors_keep_field_order_and_structured_failure():
    with ScriptRunner() as runner:
        result = runner.handle_script("""
            Address: schema #{zip: `int`}
            Profile: schema #{name: `string`, address: Address, age: `int`}
            do [validate #{name: 7, address: #{zip: 'wrong'}} Profile]
        """)
        assert result.status == 'ok', result.error_message
        assert result.value['status'] == PathLiteral(Path(['err']))
        error = result.value['error']
        assert error['code'] == PathLiteral(Path(['invalid']))
        errors = error['data']
        assert [item['field'] for item in errors] == ['name', 'zip', 'age']
        assert 'expected type' in errors[0]['error']
        assert errors[2]['error'] == 'field is required'
