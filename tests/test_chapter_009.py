import pytest

from slip import ScriptRunner


async def run_slip(src: str):
    runner = ScriptRunner()
    return await runner.handle_script(src)


def assert_ok(res, expected=None):
    assert res.status == 'success', res.error_message
    if expected is not None:
        assert res.value == expected


def assert_error(res, contains: str | None = None):
    assert res.status == 'error', f"expected error, got success: {res.value!r}"
    if contains is not None:
        assert contains in (res.error_message or ""), f"error did not contain {contains!r}: {res.error_message!r}"


# Chapter 9: Data Modeling and Validation

@pytest.mark.asyncio
async def test_schema_creation_and_is_schema_predicate():
    src = """
    -- Create a basic schema and verify predicates and shape
    UserSchema: schema #{ name: `string`, age: `number` }
    #[ is-schema? UserSchema, is-a? UserSchema Schema, is-scope? UserSchema ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True])


@pytest.mark.asyncio
async def test_validate_helper_is_currently_missing_errors_cleanly():
    # Pipe style usage described in the chapter should error if validate is not implemented
    src = """
    UserSchema: schema #{ name: `string` }
    raw: #{ name: "Alice" }
    raw |validate UserSchema
    """
    res = await run_slip(src)
    assert_ok(res)

    # Prefix call form should also error cleanly
    src2 = """
    UserSchema: schema #{ name: `string` }
    raw: #{ name: "Alice" }
    validate raw UserSchema
    """
    res2 = await run_slip(src2)
    assert_ok(res2)


@pytest.mark.asyncio
async def test_default_and_optional_markers_missing_errors_cleanly():
    # Using (default 8080) and (optional string) in a schema config should error
    src = """
    ConfigSchema: schema #{
        host: `string`,
        port: (default 8080),
        user: (optional `string`)
    }
    """
    res = await run_slip(src)
    # Now that default/optional are implemented, the schema definition should succeed.
    assert_ok(res)


@pytest.mark.asyncio
async def test_schema_composition_and_inheritance_relationships():
    # Composition via nested schemas and inheritance via create (no second inherit)
    src = """
    ContactInfoSchema: schema #{ email: `string` }
    UserSchema: create ContactInfoSchema [
        name: `string`
    ]

    TeamSchema: schema #{
        team-name: `string`,
        leader: `UserSchema`,
        members: `list`
    }

    #[ is-schema? ContactInfoSchema,
       is-schema? UserSchema,
       is-a? UserSchema ContactInfoSchema,
       is-schema? TeamSchema ]
    """
    res = await run_slip(src)
    assert_ok(res, [True, True, True, True])
