import json

import pytest
import pytest_asyncio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from slip import ScriptRunner
from slip.slip_datatypes import Scope


HOST_PARAMETERS = {"actor-id"}
HOST_ARGUMENTS = {"actor-id": "actor.player.1"}


@pytest.fixture
def command_module_files(tmp_path):
    movement = tmp_path / "movement.slip"
    movement.write_text(
        "take: fn {actor-id, object-id} [\n"
        "    emit 'audit' #{ verb: 'take', object-id: object-id }\n"
        "    #[actor-id, object-id]\n"
        "]\n"
        "\n"
        "put: fn {actor-id, object-id, relation, target-id "
        "|where relation = 'in'} [\n"
        "    #['in', actor-id, object-id, target-id]\n"
        "]\n"
        "\n"
        "put: fn {actor-id, object-id, relation, target-id "
        "|where relation = 'on'} [\n"
        "    #['on', actor-id, object-id, target-id]\n"
        "]\n"
        "\n"
        "put: fn {actor-id, object-id, relation, target-id, adverb} [\n"
        "    #[adverb, actor-id, object-id, relation, target-id]\n"
        "]\n"
        "\n"
        "inspect: fn {actor-id, payload: `dict`} [\n"
        "    #[actor-id, payload.items[0].name]\n"
        "]\n"
        "\n"
        "helper: fn {x} [ x ]\n",
        encoding="utf-8",
    )
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        f"movement: import `file://{movement.as_posix()}`\n"
        "\n"
        "take: movement.take |public\n"
        "put: movement.put |public\n"
        "inspect: movement.inspect |public\n",
        encoding="utf-8",
    )
    return movement, command_api


@pytest_asyncio.fixture
async def public_module(command_module_files):
    _movement, command_api = command_module_files
    runner = ScriptRunner()
    return await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )


def function_branch(schema, name):
    return next(
        branch
        for branch in schema["anyOf"]
        if branch["properties"]["function"]["const"] == name
    )


@pytest.mark.asyncio
async def test_public_schema_is_nested_and_deduplicates_guarded_forms(
    public_module,
):
    module = public_module
    default_schema = module.json_schema()
    schema = module.json_schema(host_parameters=HOST_PARAMETERS)

    Draft202012Validator.check_schema(schema)
    assert module.public_names() == ["inspect", "put", "take"]

    default_take = function_branch(default_schema, "take")
    assert default_take["properties"]["arguments"]["required"] == [
        "actor-id",
        "object-id",
    ]

    take = function_branch(schema, "take")
    assert take["required"] == ["function", "arguments"]
    assert take["properties"]["arguments"] == {
        "type": "object",
        "required": ["object-id"],
        "properties": {"object-id": {"type": "string"}},
        "additionalProperties": False,
    }

    put = function_branch(schema, "put")
    forms = put["properties"]["arguments"]["anyOf"]
    assert len(forms) == 2
    assert sorted(form["required"] for form in forms) == sorted([
        ["object-id", "relation", "target-id"],
        ["object-id", "relation", "target-id", "adverb"],
    ])

    schema_text = json.dumps(schema)
    assert "actor-id" not in schema_text
    assert "where" not in schema_text
    assert "'in'" not in schema_text
    assert "'on'" not in schema_text


@pytest.mark.asyncio
async def test_public_call_and_commands_schemas_validate_anyof(public_module):
    module = public_module
    call_validator = Draft202012Validator(
        module.json_schema(host_parameters=HOST_PARAMETERS)
    )
    commands_validator = Draft202012Validator(
        module.commands_schema(host_parameters=HOST_PARAMETERS)
    )

    take = {
        "function": "take",
        "arguments": {"object-id": "object.key.1"},
    }
    put = {
        "function": "put",
        "arguments": {
            "object-id": "object.key.1",
            "relation": "in",
            "target-id": "container.box.1",
        },
    }
    put_with_adverb = {
        "function": "put",
        "arguments": {
            **put["arguments"],
            "adverb": "carefully",
        },
    }

    call_validator.validate(take)
    call_validator.validate(put)
    call_validator.validate(put_with_adverb)
    commands_validator.validate([take, put, put_with_adverb])

    with pytest.raises(ValidationError):
        call_validator.validate({
            "function": "take",
            "arguments": {
                "object-id": "object.key.1",
                "target-id": "container.box.1",
            },
        })


def test_public_call_source_normalizes_literals_without_execution(
    public_module,
):
    module = public_module

    assert module.json_command_from_source(
        "take 'object.key.1'", host_parameters=HOST_PARAMETERS
    ) == {
        "function": "take",
        "arguments": {"object-id": "object.key.1"},
    }
    assert module.json_command_from_source(
        "put 'object.key.1' 'in' 'container.box.1'",
        host_parameters=HOST_PARAMETERS,
    ) == {
        "function": "put",
        "arguments": {
            "object-id": "object.key.1",
            "relation": "in",
            "target-id": "container.box.1",
        },
    }

    with pytest.raises(ValueError, match="literals"):
        module.json_command_from_source(
            "take object-id", host_parameters=HOST_PARAMETERS
        )
    with pytest.raises(ValueError, match="one expression"):
        module.json_command_from_source(
            "take 'object.key.1'\ntake 'object.key.2'",
            host_parameters=HOST_PARAMETERS,
        )
    with pytest.raises(ValueError, match="unknown public command"):
        module.json_command_from_source(
            "helper 'object.key.1'", host_parameters=HOST_PARAMETERS
        )


@pytest.mark.asyncio
async def test_public_schema_composes_inside_parse_result_oneof(public_module):
    module = public_module
    parse_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "oneOf": [
            {
                "type": "object",
                "required": ["status", "commands"],
                "properties": {
                    "status": {"const": "parsed"},
                    "commands": {
                        "type": "array",
                        "minItems": 1,
                        "items": module.json_schema(
                            host_parameters=HOST_PARAMETERS
                        ),
                    },
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["status", "clarification"],
                "properties": {
                    "status": {"const": "parse-failed"},
                    "clarification": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        ],
    }
    validator = Draft202012Validator(parse_schema)

    validator.validate({
        "status": "parsed",
        "commands": [{
            "function": "take",
            "arguments": {"object-id": "object.key.1"},
        }],
    })
    validator.validate({
        "status": "parse-failed",
        "clarification": "Which key do you mean?",
    })

    with pytest.raises(ValidationError):
        validator.validate({
            "status": "parsed",
            "commands": [],
            "clarification": "Which key?",
        })


@pytest.mark.asyncio
async def test_run_json_command_validates_converts_and_injects_actor(
    public_module,
):
    module = public_module
    command = json.dumps({
        "function": "inspect",
        "arguments": {
            "payload": {
                "items": [{"name": "Brass Key"}],
            },
        },
    })

    result = await module.run_json_command(
        command,
        host_arguments=HOST_ARGUMENTS,
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["actor.player.1", "Brass Key"]


@pytest.mark.asyncio
async def test_run_json_command_uses_normal_where_dispatch(public_module):
    module = public_module
    base = {
        "function": "put",
        "arguments": {
            "object-id": "object.key.1",
            "target-id": "container.box.1",
        },
    }

    in_result = await module.run_json_command(
        {**base, "arguments": {**base["arguments"], "relation": "in"}},
        host_arguments=HOST_ARGUMENTS,
    )
    on_result = await module.run_json_command(
        {**base, "arguments": {**base["arguments"], "relation": "on"}},
        host_arguments=HOST_ARGUMENTS,
    )
    invalid_result = await module.run_json_command(
        {**base, "arguments": {**base["arguments"], "relation": "near"}},
        host_arguments=HOST_ARGUMENTS,
    )

    assert in_result.status == "ok", in_result.error_message
    assert in_result.value[0] == "in"
    assert on_result.status == "ok", on_result.error_message
    assert on_result.value[0] == "on"
    assert invalid_result.status == "err"
    assert "No matching method" in (invalid_result.error_message or "")


@pytest.mark.asyncio
async def test_run_json_command_preserves_effects(public_module):
    module = public_module
    result = await module.run_json_command(
        {
            "function": "take",
            "arguments": {"object-id": "object.key.1"},
        },
        host_arguments=HOST_ARGUMENTS,
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["actor.player.1", "object.key.1"]
    assert result.side_effects == [{
        "topics": ["audit"],
        "message": {"verb": "take", "object-id": "object.key.1"},
    }]


@pytest.mark.asyncio
async def test_run_json_command_rejects_malformed_or_nonpublic_calls(
    public_module,
):
    module = public_module

    malformed = await module.run_json_command(
        "{",
        host_arguments=HOST_ARGUMENTS,
    )
    unknown = await module.run_json_command(
        {
            "function": "helper",
            "arguments": {"x": "value"},
        },
        host_arguments=HOST_ARGUMENTS,
    )
    extra = await module.run_json_command(
        {
            "function": "take",
            "arguments": {
                "object-id": "object.key.1",
                "target-id": "container.box.1",
            },
        },
        host_arguments=HOST_ARGUMENTS,
    )

    assert malformed.status == "err"
    assert "invalid command JSON" in (malformed.error_message or "")
    assert unknown.status == "err"
    assert "invalid public command" in (unknown.error_message or "")
    assert extra.status == "err"
    assert "invalid public command" in (extra.error_message or "")


@pytest.mark.asyncio
async def test_run_json_commands_preserves_order(public_module):
    module = public_module
    results = await module.run_json_commands(
        [
            {
                "function": "take",
                "arguments": {"object-id": "object.key.1"},
            },
            {
                "function": "put",
                "arguments": {
                    "object-id": "object.key.1",
                    "relation": "on",
                    "target-id": "object.table.1",
                },
            },
        ],
        host_arguments=HOST_ARGUMENTS,
    )

    assert [result.status for result in results] == ["ok", "ok"]
    assert results[0].value == ["actor.player.1", "object.key.1"]
    assert results[1].value[0] == "on"


@pytest.mark.asyncio
async def test_public_marker_does_not_mutate_imported_function(
    public_module,
):
    module = public_module
    movement = module.exports["movement"]

    assert module.public_exports["take"].meta["public"] is True
    assert movement["take"].meta.get("public") is not True


@pytest.mark.asyncio
async def test_non_json_signature_requires_host_binding(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "Item: scope #{}\n"
        "take: fn {request-id, obj: Item} [\n"
        "    #[request-id, obj.name]\n"
        "] |public\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="no JSON-compatible signatures: take",
    ):
        module = await ScriptRunner().import_public_module(
            f"file://{command_api.as_posix()}"
        )
        module.json_schema()

    item = Scope(parent=module.exports["Item"])
    item["name"] = "Brass Key"
    schema = module.json_schema(host_parameters={"request-id", "obj"})
    result = await module.run_json_command(
        {"function": "take", "arguments": {}},
        host_arguments={"request-id": "request-1", "obj": item},
    )

    Draft202012Validator(schema).validate({
        "function": "take",
        "arguments": {},
    })
    assert result.status == "ok", result.error_message
    assert result.value == ["request-1", "Brass Key"]


@pytest.mark.asyncio
async def test_run_json_command_can_resolve_host_ids_from_imported_module(
    tmp_path,
):
    movement = tmp_path / "movement.slip"
    movement.write_text(
        "Item: scope #{}\n"
        "describe: fn {actor-id, obj: Item} [ #[actor-id, obj.name] ]\n"
        "describe: fn {actor-id, object-id "
        "|where (type-of object-id) = `string`} [\n"
        "    describe actor-id (host-object object-id)\n"
        "]\n",
        encoding="utf-8",
    )
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        f"movement: import `file://{movement.as_posix()}`\n"
        "describe: movement.describe |public\n",
        encoding="utf-8",
    )
    registry = {
        "item-1": {
            "__slip__": {"type": "scope", "prototype": "Item"},
            "name": "Brass Key",
        }
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    module = await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )

    result = await module.run_json_command(
        {
            "function": "describe",
            "arguments": {"object-id": "item-1"},
        },
        host_arguments=HOST_ARGUMENTS,
    )
    missing = await module.run_json_command(
        {
            "function": "describe",
            "arguments": {"object-id": "missing"},
        },
        host_arguments=HOST_ARGUMENTS,
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["actor.player.1", "Brass Key"]
    assert missing.status == "err"
    assert "missing" in (missing.error_message or "")


@pytest.mark.asyncio
async def test_command_projects_and_hydrates_prototype_parameters(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "Persona: scope #{}\n"
        "Item: scope #{}\n"
        "take-method: fn {actor: Persona, object: Item, original-text "
        "|where object.enabled} [\n"
        "    #[actor.name, object.name, original-text]\n"
        "]\n"
        "take: take-method |command |public\n",
        encoding="utf-8",
    )
    registry = {
        "id:persona.1": {
            "__slip__": {"type": "scope", "prototype": "Persona"},
            "name": "Ada",
        },
        "id:item.apple.1": {
            "__slip__": {"type": "scope", "prototype": "Item"},
            "name": "apple",
            "enabled": True,
        },
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    module = await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )

    schema = module.json_schema(
        host_parameters={"actor", "original-text"},
    )
    take = function_branch(schema, "take")
    assert take["properties"]["arguments"] == {
        "type": "object",
        "required": ["object"],
        "properties": {
            "object": {"type": "string", "pattern": "^id:.+"},
        },
        "additionalProperties": False,
    }

    result = await module.run_json_command(
        {
            "function": "take",
            "arguments": {"object": "id:item.apple.1"},
        },
        host_arguments={
            "actor": "id:persona.1",
            "original-text": "take the apple",
        },
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["Ada", "apple", "take the apple"]


@pytest.mark.asyncio
async def test_command_preserves_callable_when_method_parameter_is_target(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "Persona: scope #{}\n"
        "Item: scope #{}\n"
        "inspect-method: fn {actor: Persona, target: Item, original-text} [\n"
        "    #[actor.name, target.name, original-text]\n"
        "]\n"
        "inspect: inspect-method |command |public\n",
        encoding="utf-8",
    )
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
    module = await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )

    result = await module.run_json_command(
        {
            "function": "inspect",
            "arguments": {"target": "id:item.apple.1"},
        },
        host_arguments={
            "actor": "id:persona.1",
            "original-text": "inspect the apple",
        },
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["Ada", "apple", "inspect the apple"]


@pytest.mark.asyncio
async def test_command_preserves_method_parameter_named_value(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "Persona: scope #{}\n"
        "write-method: fn {actor: Persona, value, original-text} [\n"
        "    #[actor.name, value, original-text]\n"
        "]\n"
        "write: write-method |command |public\n",
        encoding="utf-8",
    )
    registry = {
        "id:persona.1": {
            "__slip__": {"type": "scope", "prototype": "Persona"},
            "name": "Ada",
        },
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    module = await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )

    result = await module.run_json_command(
        {
            "function": "write",
            "arguments": {"value": "beware"},
        },
        host_arguments={
            "actor": "id:persona.1",
            "original-text": "write beware",
        },
    )

    assert result.status == "ok", result.error_message
    assert result.value == ["Ada", "beware", "write beware"]


@pytest.mark.asyncio
async def test_command_overloads_distinguish_tagged_ids_from_strings(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "Persona: scope #{}\n"
        "Item: scope #{}\n"
        "use-method: fn {actor: Persona, object: Item, original-text} [\n"
        "    #['item', actor.name, object.name, original-text]\n"
        "]\n"
        "use-method: fn {actor: Persona, object: `string`, original-text} [\n"
        "    #['text', actor.name, object, original-text]\n"
        "]\n"
        "use: use-method |command |public\n",
        encoding="utf-8",
    )
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
    module = await runner.import_public_module(
        f"file://{command_api.as_posix()}"
    )
    host_arguments = {
        "actor": "id:persona.1",
        "original-text": "use the object",
    }

    schema = module.json_schema(
        host_parameters={"actor", "original-text"},
    )
    use = function_branch(schema, "use")
    forms = use["properties"]["arguments"]["anyOf"]
    object_schemas = [form["properties"]["object"] for form in forms]
    assert {json.dumps(item, sort_keys=True) for item in object_schemas} == {
        json.dumps({"type": "string"}, sort_keys=True),
        json.dumps({"type": "string", "pattern": "^id:.+"}, sort_keys=True),
    }

    item_result = await module.run_json_command(
        {
            "function": "use",
            "arguments": {"object": "id:item.apple.1"},
        },
        host_arguments=host_arguments,
    )
    text_result = await module.run_json_command(
        {
            "function": "use",
            "arguments": {"object": "carefully"},
        },
        host_arguments=host_arguments,
    )

    assert module.json_command_from_source(
        "use 'id:item.apple.1'",
        host_parameters={"actor", "original-text"},
    ) == {
        "function": "use",
        "arguments": {"object": "id:item.apple.1"},
    }
    assert module.json_command_from_source(
        "use 'carefully'",
        host_parameters={"actor", "original-text"},
    ) == {
        "function": "use",
        "arguments": {"object": "carefully"},
    }

    assert item_result.status == "ok", item_result.error_message
    assert item_result.value == ["item", "Ada", "apple", "use the object"]
    assert text_result.status == "ok", text_result.error_message
    assert text_result.value == ["text", "Ada", "carefully", "use the object"]


@pytest.mark.asyncio
async def test_cached_public_command_id_adapter_ignores_id_scope_binding(tmp_path):
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "id: scope #{}\n"
        "Persona: scope #{}\n"
        "look-method: fn {actor: Persona, original-text} [original-text]\n"
        "look: look-method |command |public\n",
        encoding="utf-8",
    )
    registry = {
        "id:persona.1": {
            "__slip__": {"type": "scope", "prototype": "Persona"},
        },
    }
    runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    locator = f"file://{command_api.as_posix()}"
    cold_module = await runner.import_public_module(locator)
    cached_module = await runner.import_public_module(locator)
    command = {"function": "look", "arguments": {}}
    host_arguments = {
        "actor": "id:persona.1",
        "original-text": "look",
    }

    cold_result = await cold_module.run_json_command(
        command,
        host_arguments=host_arguments,
    )
    cached_result = await cached_module.run_json_command(
        command,
        host_arguments=host_arguments,
    )

    assert type(host_arguments["actor"]) is str
    assert cold_result.status == "ok", cold_result.error_message
    assert cached_result.status == "ok", cached_result.error_message
    assert cold_result.value == "look"
    assert cached_result.value == "look"


@pytest.mark.asyncio
async def test_cross_runner_cached_run_with_module_rebuilds_command_adapters(tmp_path):
    (tmp_path / "domain.slip").write_text(
        "id: scope #{}\n"
        "Persona: scope #{}\n"
        "look-method: fn {actor: Persona, original-text} [original-text]\n",
        encoding="utf-8",
    )
    command_api = tmp_path / "command-api.slip"
    command_api.write_text(
        "domain-code: file://./domain.slip\n"
        "run-with domain-code current-scope\n"
        "look: look-method |command |public\n",
        encoding="utf-8",
    )
    registry = {
        "id:persona.1": {
            "__slip__": {"type": "scope", "prototype": "Persona"},
        },
    }
    locator = f"file://{command_api.as_posix()}"
    command = {"function": "look", "arguments": {}}
    host_arguments = {
        "actor": "id:persona.1",
        "original-text": "look",
    }

    first_runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    first_module = await first_runner.import_public_module(locator)
    first_result = await first_module.run_json_command(
        command,
        host_arguments=host_arguments,
    )

    second_runner = ScriptRunner(host_data=lambda object_id: registry[object_id])
    second_module = await second_runner.import_public_module(locator)
    second_result = await second_module.run_json_command(
        command,
        host_arguments=host_arguments,
    )

    first_sig = first_module._shapes[0].func.methods[0].meta["type"]
    second_sig = second_module._shapes[0].func.methods[0].meta["type"]
    assert first_sig is not second_sig
    assert first_sig.param_order == second_sig.param_order
    assert first_sig.parameters[1].is_typed is False
    assert second_sig.parameters[1].is_typed is False
    assert first_result.status == "ok", first_result.error_message
    assert second_result.status == "ok", second_result.error_message
    assert first_result.value == "look"
    assert second_result.value == "look"
