"""Whole expressions taken from the language guides, without legacy imports."""

import pytest

from slip.slip_core import execute, language_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize(("source", "expected"), [
    ("10 + 5 * 2", 30),
    ("10 + (5 * 2)", 20),
    ("10 |add 5 |mul 2", 30),
    ("-- A comment\n{-- A {-- nested --} comment --}\n10 + 20", 30),
    ("add-ten: fn {n} [n + 10]; add-ten 5", 15),
    ("f: fn {x} [x + 1]; /+: |core-sub; g: fn {x} [x + 1]; "
     "#[f 10, g 10]", [11, 9]),
    ("make-adder: fn {n} [fn {x} [x + n]]; "
     "add-10: make-adder 10; add-10 7", 17),
    ("keep: fn {value} [return value]; target: keep core-add; "
     "op: |target; target: keep core-sub; 10 op 3", 13),
    ("player: #{name: 'Karl', hp: 120}; player.hp", 120),
    ("name: 'Karl'; msg: \"Hello {{name}}\"; msg", "Hello Karl"),
    ("name: 'Karl'; \"\n    Hello {{name}}!\n    Welcome back.\n\"",
     "Hello Karl!\nWelcome back."),
    ("hp: 40; if [hp > 50] ['Healthy'] ['Wounded']", "Wounded"),
    ("i: 3; while [i > 0] [i: i - 1]; i", 0),
    ("players: #[#{hp: 120}, #{hp: 45}]; players.hp", [120, 45]),
    ("players: #[#{hp: 120}, #{hp: 45}]; "
     "players.hp[< 50]: * 2; players.hp", [120, 90]),
    ("players: #[#{hp: 120}, #{hp: 45}]; "
     "players[.hp < 50].hp: * 2; players.hp", [120, 90]),
    ("limit: 50; players: #[#{hp: 120}, #{hp: 45}]; "
     "players[.hp < limit].hp", [45]),
    ("nums: #[10, 20, 30]; nums[1]", 20),
    ("nums: #[10, 20, 30]; nums[1:]", [20, 30]),
    ("return-seven: fn {} [do [return 7]; 99]; return-seven", 7),
    ("describe: fn {x: `int`} ['int']; "
     "describe: fn {x} ['other']; describe 3", "int"),
    ("choose: fn {x} ['fallback']; "
     "choose: fn {x |where x > 10} ['large']; "
     "#[choose 5, choose 20]", ["fallback", "large"]),
])
def test_documented_script(source, expected):
    assert execute(parse(source), language_scope()) == expected
