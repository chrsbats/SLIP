import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_filter_objects_and_combine_conditions():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: "Karl", class: "Warrior", hp: 120 },
  #{ name: "Jaina", class: "Mage", hp: 90 },
  #{ name: "Karl", class: "Mage", hp: 130 }
]
result: players[.hp > 100 and .name = 'Karl']
len result
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    assert res.value == 2

@pytest.mark.asyncio
async def test_filter_then_project_names():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: "Karl", class: "Warrior", hp: 120 },
  #{ name: "Jaina", class: "Mage", hp: 110 },
  #{ name: "Thrall", class: "Warrior", hp: 95 }
]
names: players[.hp > 100 and .class = 'Warrior'] |map (fn {p} [ p.name ])
names
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    assert res.value == ["Karl"]

@pytest.mark.asyncio
async def test_filter_with_or_conditions():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: "Karl", class: "Warrior", hp: 120 },
  #{ name: "Jaina", class: "Mage", hp: 90 },
  #{ name: "Thrall", class: "Warrior", hp: 130 }
]
names: players[.hp > 100 and (.name = 'Karl' or .name = 'Jaina')] |map (fn {p} [ p.name ])
names
"""
    res = await runner.handle_script(src)
    assert res.status == 'success', res.error_message
    assert res.value == ["Karl"]
