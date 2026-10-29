import pytest

from slip.slip_core import Scope, execute
from slip.slip_library import library_scope
from slip.slip_syntax import parse


@pytest.mark.parametrize(("source", "expected"), [
    ("my-var: 10; run [result: (add (inject my-var) 5); result]", 15),
    ("op: `add`; v1: 2; v2: 3; "
     "code: [call (inject op) #[(inject v1), (inject v2)]]; run code", 5),
    ("args: #[2, 3]; run [add (splice args)]", 5),
    ("module-x: 5; args: #[3, 4]; extra-stmts: [y: 10; z: y * 2]; "
     "code: [x: (inject module-x); (splice extra-stmts); "
     "result: add (splice args); x + result + z]; run code", 32),
    ("call add #[1, 2]", 3),
    ("p: to-path 'a.b'; p = `a.b`", True),
    ("call 'x:' #[10]; x", 10),
    ("x: 10; call '~x' #[]; result: do [x]; result.status = err", True),
    ("to-path 'player.hp' = `player.hp`", True),
    ("x: 10; result: do [run [x]]; result.status = err", True),
])
def test_documented_metaprogramming(source, expected):
    scope = Scope(parent=library_scope())
    assert execute(parse(source), scope) == expected
