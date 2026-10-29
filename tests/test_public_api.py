import json

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from slip import ScriptRunner, slip_core as core
from slip.slip_core import Generic, Lambda, Scope


@pytest.fixture
def commands(tmp_path):
    (tmp_path / "mechanics.slip").write_text("""
        take: fn {actor, object} [emit 'audit' object; #[actor, object]]
        put: fn {actor, object, relation |where relation = 'in'} ['in']
        put: fn {actor, object, relation |where relation = 'on'} ['on']
        put: fn {actor, object, relation, adverb} [adverb]
        helper: fn {x} [x]
    """)
    (tmp_path / "api.slip").write_text("""
        mechanics: import `file://mechanics.slip`
        take: public mechanics.take
        put: public mechanics.put
    """)
    with ScriptRunner() as runner:
        runner.source_dir = str(tmp_path)
        yield runner.import_public_module("file://api.slip")


def test_public_module_schemas_discovery_and_marker_isolation(commands):
    assert commands.public_names() == ["put", "take"]
    assert commands.public_exports["take"].meta["public"] is True
    assert not commands.exports["mechanics"]["take"].meta.get("public")
    schema = commands.json_schema(host_parameters={"actor"})
    Draft202012Validator.check_schema(schema)
    assert "actor" not in json.dumps(schema)
    put = schema["anyOf"][0]["properties"]["arguments"]["anyOf"]
    assert len(put) == 2
    validator = Draft202012Validator(schema)
    validator.validate({"function": "take", "arguments": {"object": "key"}})
    with pytest.raises(ValidationError):
        validator.validate({"function": "take", "arguments": {
            "object": "key", "extra": 1,
        }})


def test_public_execution_direct_calls_guards_effects_and_errors(
    commands, monkeypatch,
):
    def forbidden(source):
        raise AssertionError("JSON command generated SLIP source")

    monkeypatch.setattr(commands.runner, "handle_script", forbidden)
    result = commands.run_json_command(
        '{"function":"take","arguments":{"object":"key"}}',
        host_arguments={"actor": "person"},
    )
    assert result.status == "ok", result.error_message
    assert result.value == ["person", "key"]
    assert result.side_effects == [{"topics": ["audit"], "message": "key"}]
    results = commands.run_json_commands([
        {"function": "put", "arguments": {"object": "key", "relation": "on"}},
        {"function": "put", "arguments": {
            "object": "key", "relation": "near",
        }},
        {"function": "helper", "arguments": {}},
    ], host_arguments={"actor": "person"})
    assert [result.status for result in results] == ["ok", "err", "err"]
    assert results[0].value == "on"
    assert "No matching method" in results[1].error_message
    assert "invalid public command" in results[2].error_message
    malformed = commands.run_json_command("{")
    assert "invalid command JSON" in malformed.error_message


def test_public_source_conversion_is_literal_only(commands):
    assert commands.json_command_from_source(
        "take 'key'", host_parameters={"actor"},
    ) == {
        "function": "take", "arguments": {"object": "key"},
    }
    with pytest.raises(ValueError, match="literals"):
        commands.json_command_from_source(
            "take object", host_parameters={"actor"},
        )
    with pytest.raises(ValueError, match="one expression"):
        commands.json_command_from_source("take 'one'; take 'two'")
    with pytest.raises(ValueError, match="unknown public command"):
        commands.json_command_from_source("helper 'key'")


@pytest.mark.parametrize("name", [
    "object", "target", "value", "command-scope",
])
def test_command_slip_closures_hydrate_without_parameter_name_collisions(
    tmp_path, name, monkeypatch,
):
    path = tmp_path / "api.slip"
    signature = f"actor: Persona, {name}: Item, text |where {name}.enabled"
    path.write_text(f"""
        Persona: scope #{{}}
        Item: scope #{{}}
        take-method: fn {{{signature}}} [
            emit 'audit' text
            #[actor.name, {name}.name, text]
        ]
        take: command take-method |public
    """)
    registry = {
        "id:actor": {"__slip__": {"type": "scope", "prototype": "Persona"},
                     "name": "Ada"},
        "id:item": {"__slip__": {"type": "scope", "prototype": "Item"},
                    "name": "key", "enabled": True},
    }
    lookups = []

    def load(object_id):
        lookups.append(object_id)
        return registry[object_id]

    with ScriptRunner(host_data=load) as runner:
        module = runner.import_public_module("file://" + str(path))
        function = module.public_exports["take"]
        assert isinstance(function, Generic)
        assert all(isinstance(method, Lambda) for method in function.methods)
        result = module.run_json_command(
            {"function": "take", "arguments": {name: "id:item"}},
            host_arguments={"actor": "id:actor", "text": "take key"},
        )
        assert "Persona" not in runner.root_scope.bindings
        assert "Item" not in runner.root_scope.bindings
        assert result.status == "ok", result.error_message
        assert result.value == ["Ada", "key", "take key"]
        assert result.side_effects == [
            {"topics": ["audit"], "message": "take key"},
        ]
        assert lookups == ["id:actor", "id:item"]

        def forbidden(*args, **kwargs):
            raise AssertionError("command invocation expanded or rebound Code")

        monkeypatch.setattr(core, "expand", forbidden)
        monkeypatch.setattr(core, "convert", forbidden)
        registry["id:item"]["name"] = "coin"
        repeated = module.run_json_command(
            {"function": "take", "arguments": {name: "id:item"}},
            host_arguments={"actor": "id:actor", "text": "take coin"},
        )
        assert repeated.status == "ok", repeated.error_message
        assert repeated.value == ["Ada", "coin", "take coin"]
        assert repeated.side_effects == [
            {"topics": ["audit"], "message": "take coin"},
        ]
        assert lookups == ["id:actor", "id:item"] * 2


def test_command_zero_argument_implementation_and_source_literals(tmp_path):
    path = tmp_path / "api.slip"
    path.write_text("f: fn {} [7] |command |public")
    with ScriptRunner() as runner:
        module = runner.import_public_module("file://" + str(path))
        result = module.run_json_command({"function": "f", "arguments": {}})
        assert result.status == "ok" and result.value == 7


def test_command_preserves_variadic_arguments_and_id_string_overloads(
    tmp_path,
):
    path = tmp_path / "api.slip"
    path.write_text("""
        Persona: scope #{}
        Item: scope #{}
        use-method: fn {actor: Persona, object: Item, rest...} [
            #['item', actor.name, object.name, rest]
        ]
        use-method: fn {actor: Persona, object: `string`, rest...} [
            #['text', actor.name, object, rest]
        ]
        use: command use-method |public
    """)
    registry = {
        "id:a": {"__slip__": {"type": "scope", "prototype": "Persona"},
                 "name": "Ada"},
        "id:k": {"__slip__": {"type": "scope", "prototype": "Item"},
                 "name": "key"},
    }
    with ScriptRunner(host_data=registry.__getitem__) as runner:
        module = runner.import_public_module("file://" + str(path))
        cases = (("id:k", ["item", "Ada", "key", ["now"]]),
                 ("slowly", ["text", "Ada", "slowly", ["now"]]))
        for value, expected in cases:
            result = module.run_json_command(
                {"function": "use", "arguments": {
                    "object": value, "rest": ["now"],
                }},
                host_arguments={"actor": "id:a"},
            )
            assert result.status == "ok", result.error_message
            assert result.value == expected
        assert module.json_command_from_source(
            "use 'id:k' 'now'", host_parameters={"actor"},
        )["arguments"] == {"object": "id:k", "rest": ["now"]}


def test_command_schemas_compose_with_arrays_and_parse_result_envelopes(
    commands,
):
    schema = commands.json_schema(host_parameters={'actor'})
    validator = Draft202012Validator(commands.commands_schema(
        host_parameters={'actor'},
    ))
    calls = [
        {'function': 'take', 'arguments': {'object': 'key'}},
        {'function': 'put', 'arguments': {'object': 'key', 'relation': 'in'}},
        {'function': 'put', 'arguments': {
            'object': 'key', 'relation': 'on', 'adverb': 'carefully',
        }},
    ]
    validator.validate(calls)
    with pytest.raises(ValidationError):
        validator.validate(calls + [{'function': 'private', 'arguments': {}}])
    parser_result = {'oneOf': [
        {'type': 'object', 'required': ['status', 'commands'],
         'properties': {'status': {'const': 'parsed'}, 'commands': {
             'type': 'array', 'minItems': 1, 'items': schema,
         }}, 'additionalProperties': False},
        {'type': 'object', 'required': ['status', 'clarification'],
         'properties': {'status': {'const': 'parse-failed'},
                        'clarification': {'type': 'string', 'minLength': 1}},
         'additionalProperties': False},
    ]}
    validator = Draft202012Validator(parser_result)
    validator.validate({'status': 'parsed', 'commands': calls})
    validator.validate({
        'status': 'parse-failed', 'clarification': 'Which key?',
    })
    with pytest.raises(ValidationError):
        validator.validate({'status': 'parsed', 'commands': [],
                            'clarification': 'Which key?'})


def test_nested_json_payloads_are_passed_with_host_arguments(tmp_path):
    path = tmp_path / 'api.slip'
    path.write_text('''
        inspect: fn {actor, payload: `dict`} [
            #[actor, payload.items[0].name]
        ] |public
    ''')
    with ScriptRunner() as runner:
        module = runner.import_public_module('file://' + str(path))
        result = module.run_json_command(json.dumps({
            'function': 'inspect',
            'arguments': {'payload': {'items': [{'name': 'Brass Key'}]}},
        }), host_arguments={'actor': 'actor-1'})
        assert result.status == 'ok', result.error_message
        assert result.value == ['actor-1', 'Brass Key']


def test_native_prototype_parameters_require_host_binding(tmp_path):
    path = tmp_path / 'api.slip'
    path.write_text('''
        Item: scope #{}
        take: fn {request-id, object: Item} [
            #[request-id, object.name]
        ] |public
    ''')
    with ScriptRunner() as runner:
        module = runner.import_public_module('file://' + str(path))
        with pytest.raises(ValueError, match='no JSON-compatible signatures'):
            module.json_schema()
        schema = module.json_schema(host_parameters={'request-id', 'object'})
        Draft202012Validator(schema).validate({
            'function': 'take', 'arguments': {},
        })
        item = Scope({'name': 'Brass Key'}, parent=module.exports['Item'])
        result = module.run_json_command(
            {'function': 'take', 'arguments': {}},
            host_arguments={'request-id': 'request-1', 'object': item},
        )
        assert result.status == 'ok', result.error_message
        assert result.value == ['request-1', 'Brass Key']
        assert item.parent is module.exports['Item']


def test_handwritten_imported_host_id_wrapper_retains_typed_dispatch(tmp_path):
    (tmp_path / 'mechanics.slip').write_text('''
        Item: scope #{}
        describe: fn {actor, object: Item} [#[actor, object.name]]
        describe: fn {actor, object-id |where \
                      (type-of object-id) = `string`} [
            describe actor (host-object object-id)
        ]
    ''')
    path = tmp_path / 'api.slip'
    path.write_text('''
        mechanics: import `file://mechanics.slip`
        describe: public mechanics.describe
    ''')
    registry = {'item-1': {
        '__slip__': {'type': 'scope', 'prototype': 'Item'},
        'name': 'Brass Key',
    }}
    with ScriptRunner(host_data=registry.__getitem__) as runner:
        module = runner.import_public_module('file://' + str(path))
        for object_id, expected in [('item-1', 'ok'), ('missing', 'err')]:
            result = module.run_json_command({
                'function': 'describe', 'arguments': {'object-id': object_id},
            }, host_arguments={'actor': 'actor-1'})
            assert result.status == expected, result.error_message
            if expected == 'ok':
                assert result.value == ['actor-1', 'Brass Key']
            else:
                assert 'missing' in result.error_message


@pytest.mark.parametrize('run_with', [False, True])
def test_cached_adapters_retain_runner_local_signatures_and_ignore_id_binding(
    tmp_path, run_with, monkeypatch,
):
    monkeypatch.setenv('SLIP_CACHE_DIR', str(tmp_path / 'cache'))
    definitions = '''
        id: scope #{}
        Persona: scope #{}
        look-method: fn {actor: Persona, original-text} [original-text]
    '''
    path = tmp_path / 'api.slip'
    if run_with:
        (tmp_path / 'definitions.slip').write_text(definitions)
        definitions = '''
            code: file://definitions.slip
            run-with code (current-scope)
        '''
    path.write_text(definitions + '\nlook: command look-method |public')
    registry = {'id:actor': {
        '__slip__': {'type': 'scope', 'prototype': 'Persona'},
    }}
    with ScriptRunner(host_data=registry.__getitem__) as first, \
            ScriptRunner(host_data=registry.__getitem__) as second:
        locator = 'file://' + str(path)
        cold = first.import_public_module(locator)
        cached = first.import_public_module(locator)
        other = second.import_public_module(locator)
        signatures = []
        for module in (cold, cached, other):
            signature = module.public_exports['look'].methods[0].sig
            signatures.append(signature)
            assert signature.parameters[1].is_typed is False
            result = module.run_json_command(
                {'function': 'look', 'arguments': {}},
                host_arguments={'actor': 'id:actor', 'original-text': 'look'},
            )
            assert result.status == 'ok', result.error_message
            assert result.value == 'look'
        assert signatures[0] is signatures[1]
        assert signatures[0] is not signatures[2]
        assert signatures[0].param_order == signatures[2].param_order
        assert cold.exports['Persona'] is not other.exports['Persona']
