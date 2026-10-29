import pytest

from slip import ScriptRunner
from slip.slip_datatypes import GetPath, Name, PathLiteral, Sig


def test_sig_parameters_are_canonical_with_derived_legacy_views():
    persona = GetPath([Name("Persona")])
    sig = Sig(["original-text"], {"actor": persona})
    sig.param_order = [("actor", persona), ("original-text", None)]

    parameters = sig["parameters"]
    assert [parameter["name"] for parameter in parameters] == [
        "actor",
        "original-text",
    ]
    assert parameters[0]["type"] is persona
    assert "type" not in parameters[1]
    assert parameters[0].name == "actor"
    assert parameters[0].annotation is persona

    positional = sig.positional
    keywords = sig.keywords
    positional.append("unexpected")
    keywords["unexpected"] = persona
    assert sig.positional == ["original-text"]
    assert sig.keywords == {"actor": persona}

    string_type = PathLiteral(GetPath([Name("string")]))
    parameters[0]["type"] = string_type
    parameters[1]["type"] = string_type

    assert sig.keywords == {
        "actor": string_type,
        "original-text": string_type,
    }
    assert sig.positional == []
    assert sig.param_order == [
        ("actor", string_type),
        ("original-text", string_type),
    ]

    del parameters[1]["type"]
    assert sig.positional == ["original-text"]
    assert sig.keywords == {"actor": string_type}
    assert sig.param_order[-1] == ("original-text", None)


def test_sig_distinguishes_untyped_parameter_from_explicit_none_annotation():
    sig = Sig(["untyped"], {"typed": None})

    untyped, typed = sig.parameters
    assert "type" not in untyped
    assert "type" in typed
    assert typed.annotation is None


@pytest.mark.asyncio
async def test_get_sig_is_detached_and_sig_builds_dynamic_function():
    result = await ScriptRunner().handle_script("""
Persona: scope #{}
Item: scope #{}

source: fn {actor: Persona, object: Item, original-text} [
    original-text
]

description: get-sig source
parameters: description.parameters
parameters[0].type: `string`
parameters[1].type: `string`

adapter: fn (sig description) [
    #[actor, object, original-text]
]

#[
    source.methods[0].meta.type.parameters[0].type = Persona,
    adapter 'persona.1' 'item.1' 'take it'
]
""")

    assert result.status == "ok", result.error_message
    assert result.value == [
        True,
        ["persona.1", "item.1", "take it"],
    ]


@pytest.mark.asyncio
async def test_get_sig_rejects_multimethod_generic():
    result = await ScriptRunner().handle_script("""
f: fn {x: `int`} [x]
f: fn {x: `string`} [x]
get-sig f
""")

    assert result.status == "err"
    assert "exactly one method" in result.error_message


@pytest.mark.asyncio
async def test_sig_constructs_signature_from_mapping():
    result = await ScriptRunner().handle_script("""
add: fn (sig #{
    parameters: #[
        #{name: 'left', type: `int`}
        #{name: 'right', type: `int`}
    ]
    rest: none
    return-annotation: `int`
    where: none
}) [
    left + right
]

add 10 20
""")

    assert result.status == "ok", result.error_message
    assert result.value == 30


@pytest.mark.asyncio
async def test_command_is_slip_closure_that_hydrates_prototype_parameters():
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
    result = await runner.handle_script("""
Persona: scope #{}
Item: scope #{}

take-method: fn {actor: Persona, object: Item, original-text} [
    #[actor.name, object.name, original-text]
]

take: take-method |command
    take 'id:persona.1' 'id:item.apple.1' 'take the apple'
""")

    assert result.status == "ok", result.error_message
    assert result.value == ["Ada", "apple", "take the apple"]


@pytest.mark.asyncio
async def test_id_annotation_is_more_specific_than_string():
    result = await ScriptRunner().handle_script("""
kind: fn {value: `string`} ['string']
kind: fn {value: `id`} ['id']

#[kind 'plain', kind 'id:item.apple.1']
""")

    assert result.status == "ok", result.error_message
    assert result.value == ["string", "id"]


@pytest.mark.asyncio
async def test_id_annotation_is_not_shadowed_by_scope_binding():
    result = await ScriptRunner().handle_script("""
id: scope #{}
f: fn {x: `id`} [x]

f 'id:test.1'
""")

    assert result.status == "ok", result.error_message
    assert result.value == "id:test.1"
