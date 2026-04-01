import pytest

from etcher import DB

from slip import ScriptRunner


def assert_ok(res, expected=None):
    assert res.status == "ok", res.error_message
    if expected is not None:
        assert res.value == expected


@pytest.mark.asyncio
async def test_etcher_host_data_and_host_object_work_with_rd_rl(tmp_path):
    db = DB(str(tmp_path / "state.db"))

    db["location-1"] = {
        "__slip__": {"type": "scope", "prototype": "Location"},
        "name": "Town",
    }
    db["person-1"] = {
        "__slip__": {"type": "scope", "prototype": "Person"},
        "name": "Karl",
        "location": db["location-1"],
        "tags": ["a", "b"],
    }

    runner = ScriptRunner(host_data=lambda object_id: db[object_id])

    res = await runner.handle_script("""
    Person: scope #{}
    Location: scope #{}

    describe: fn {x: Person} [ "person" ]
    describe: fn {x: Location} [ "location" ]
    describe: fn {x} [ "other" ]

    raw: host-data "person-1"
    person: host-object "person-1"
    place: host-object "location-1"

    person.location.name: "Harbor"

    #[
      eq (type-of raw) `dict`,
      eq (type-of raw.tags) `list`,
      raw.tags[0],
      describe person,
      describe person.location,
      place.name
    ]
    """)

    assert_ok(res, [True, True, "a", "person", "location", "Harbor"])
