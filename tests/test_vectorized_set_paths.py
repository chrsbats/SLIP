import pytest
from slip.slip_runtime import ScriptRunner

@pytest.mark.asyncio
async def test_vectorized_assign_field_then_filter():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: 'A', hp: 40 },
  #{ name: 'B', hp: 80 },
  #{ name: 'C', hp: 30 }
]
players.hp[< 50]: 75
players.hp
""".strip()
    res = await runner.handle_script(src)
    assert res.status == "success"
    assert res.value == [75, 80, 75]

@pytest.mark.asyncio
async def test_vectorized_update_field_then_filter():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: 'A', hp: 40 },
  #{ name: 'B', hp: 80 },
  #{ name: 'C', hp: 30 }
]
players.hp[< 50]: * 1.1
players.hp
""".strip()
    res = await runner.handle_script(src)
    assert res.status == "success"
    # 40 and 30 updated with * 1.1; 80 unchanged
    assert res.value == [44.0, 80, 33.0]

@pytest.mark.asyncio
async def test_vectorized_update_filter_then_field():
    runner = ScriptRunner()
    src = """
players: #[
  #{ name: 'A', hp: 40 },
  #{ name: 'B', hp: 80 },
  #{ name: 'C', hp: 30 }
]
players[.hp < 50].hp: * 1.1
players.hp
""".strip()
    res = await runner.handle_script(src)
    assert res.status == "success"
    assert res.value == [44.0, 80, 33.0]
