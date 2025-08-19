import pytest
from slip.slip_runtime import StdLib
from slip.slip_interpreter import Evaluator, View
from slip.slip_datatypes import Scope, GetPathLiteral, GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group, Parent, Root, Pwd, Code, SlipFunction, PipedPath

@pytest.fixture
def evaluator():
    """Returns a new Evaluator for each test."""
    return Evaluator()

@pytest.fixture
def stdlib(evaluator):
    """A StdLib instance for the evaluator."""
    return StdLib(evaluator)

@pytest.fixture
def root_scope(evaluator, stdlib):
    """A root scope with some pre-populated data and stdlib functions."""
    scope = Scope()
    scope['a'] = 1
    scope['b'] = {'c': 2}
    scope['items'] = [10, 20, 30, 40]
    scope['true'] = True
    scope['false'] = False

    # Add some stdlib functions
    scope['add'] = stdlib._add
    scope['+'] = PipedPath([Name('add')])
    scope['mul'] = stdlib._mul
    scope['div'] = stdlib._div

    # Comparison functions and operator aliases (mirror root.slip)
    scope['eq'] = stdlib._eq
    scope['neq'] = stdlib._neq
    scope['gt'] = stdlib._gt
    scope['gte'] = stdlib._gte
    scope['lt'] = stdlib._lt
    scope['lte'] = stdlib._lte

    scope['=']  = PipedPath([Name('eq')])
    scope['!='] = PipedPath([Name('neq')])
    scope['>']  = PipedPath([Name('gt')])
    scope['>='] = PipedPath([Name('gte')])
    scope['<']  = PipedPath([Name('lt')])
    scope['<='] = PipedPath([Name('lte')])
    # Provide len for tests that call it inside function bodies
    scope['len'] = stdlib._len
    # Expose call and type-of primitives used by core helpers
    scope['call'] = stdlib._call
    scope['type-of'] = stdlib._type_of

    # Add evaluator's built-ins (macros)
    scope['if'] = stdlib._if
    scope['fn'] = stdlib._fn
    scope['while'] = stdlib._while
    scope['foreach'] = stdlib._foreach

    return scope

@pytest.fixture
def child_scope(root_scope):
    """A child scope linked to the root, with its own data."""
    child = Scope(parent=root_scope)
    child['d'] = 3
    child['i'] = 1
    child['j'] = 3
    child['key'] = 'c'
    root_scope['child'] = child
    return child

# --- PathResolver.get tests ---

@pytest.mark.asyncio
async def test_get_simple_name(evaluator, root_scope):
    path = GetPath([Name('a')])
    assert await evaluator.path_resolver.get(path, root_scope) == 1

@pytest.mark.asyncio
async def test_get_nested_name_on_dict(evaluator, root_scope):
    path = GetPath([Name('b'), Name('c')])
    assert await evaluator.path_resolver.get(path, root_scope) == 2

@pytest.mark.asyncio
async def test_get_from_parent_scope(evaluator, child_scope):
    path = GetPath([Name('a')])
    assert await evaluator.path_resolver.get(path, child_scope) == 1

@pytest.mark.asyncio
async def test_get_with_parent_segment(evaluator, child_scope):
    path = GetPath([Name('child'), Parent, Name('a')])
    assert await evaluator.path_resolver.get(path, child_scope.parent) == 1

@pytest.mark.asyncio
async def test_get_from_root(evaluator, child_scope):
    path = GetPath([Root, Name('a')])
    assert await evaluator.path_resolver.get(path, child_scope) == 1

@pytest.mark.asyncio
async def test_get_pwd(evaluator, child_scope):
    path = GetPath([Pwd, Name('d')])
    assert await evaluator.path_resolver.get(path, child_scope) == 3

@pytest.mark.asyncio
async def test_get_index_literal(evaluator, root_scope):
    path = GetPath([Name('items'), Index([0])])
    assert await evaluator.path_resolver.get(path, root_scope) == 10

@pytest.mark.asyncio
async def test_get_index_variable(evaluator, child_scope):
    path = GetPath([Name('items'), Index([[GetPath([Name('i')])]])])
    assert await evaluator.path_resolver.get(path, child_scope) == 20

@pytest.mark.asyncio
async def test_get_slice_literals(evaluator, root_scope):
    path = GetPath([Name('items'), Slice([1], [3])])
    assert await evaluator.path_resolver.get(path, root_scope) == [20, 30]

@pytest.mark.asyncio
async def test_get_slice_variables(evaluator, child_scope):
    path = GetPath([Name('items'), Slice(
        [[GetPath([Name('i')])]],
        [[GetPath([Name('j')])]]
    )])
    assert await evaluator.path_resolver.get(path, child_scope) == [20, 30]

@pytest.mark.asyncio
async def test_get_dynamic_group(evaluator, child_scope):
    path = GetPath([Name('b'), Group([[GetPath([Name('key')])]])])
    assert await evaluator.path_resolver.get(path, child_scope) == 2

# --- PathResolver.set tests ---

@pytest.mark.asyncio
async def test_set_simple_new(evaluator, root_scope):
    path = SetPath([Name('x')])
    await evaluator.path_resolver.set(path, 99, root_scope)
    assert root_scope['x'] == 99

@pytest.mark.asyncio
async def test_set_simple_existing(evaluator, root_scope):
    path = SetPath([Name('a')])
    await evaluator.path_resolver.set(path, 99, root_scope)
    assert root_scope['a'] == 99

@pytest.mark.asyncio
async def test_set_nested(evaluator, root_scope):
    path = SetPath([Name('b'), Name('y')])
    await evaluator.path_resolver.set(path, 99, root_scope)
    assert root_scope['b']['y'] == 99

@pytest.mark.asyncio
async def test_set_updates_owner_scope(evaluator, child_scope):
    path = SetPath([Name('a')]) # 'a' exists on parent; local by default should shadow locally
    await evaluator.path_resolver.set(path, 99, child_scope)
    assert child_scope['a'] == 99
    # parent remains unchanged (root_scope['a'] was initialized to 1)
    assert child_scope.parent['a'] == 1

@pytest.mark.asyncio
async def test_set_new_on_child(evaluator, child_scope):
    path = SetPath([Name('new_var')])
    await evaluator.path_resolver.set(path, 123, child_scope)
    assert child_scope['new_var'] == 123
    assert 'new_var' not in child_scope.parent.bindings

# --- PathResolver.delete tests ---

@pytest.mark.asyncio
async def test_delete_simple(evaluator, root_scope):
    root_scope['to_del'] = 1
    path = DelPath(GetPath([Name('to_del')]))
    await evaluator.path_resolver.delete(path, root_scope)
    assert 'to_del' not in root_scope

@pytest.mark.asyncio
async def test_delete_nested(evaluator, root_scope):
    path = DelPath(GetPath([Name('b'), Name('c')]))
    await evaluator.path_resolver.delete(path, root_scope)
    assert 'c' not in root_scope['b']

# --- Evaluator tests ---

@pytest.mark.asyncio
async def test_eval_literals(evaluator, root_scope):
    assert await evaluator.eval(1, root_scope) == 1
    assert await evaluator.eval("hello", root_scope) == "hello"
    assert await evaluator.eval(True, root_scope) is True
    assert await evaluator.eval(None, root_scope) is None

@pytest.mark.asyncio
async def test_eval_lookup(evaluator, root_scope):
    ast = GetPath([Name('a')])
    assert await evaluator.eval(ast, root_scope) == 1

@pytest.mark.asyncio
async def test_eval_group(evaluator, root_scope):
    ast = Group([[GetPath([Name('a')])]])
    assert await evaluator.eval(ast, root_scope) == 1

@pytest.mark.asyncio
async def test_eval_code_block(evaluator, root_scope):
    # A code block itself evaluates to a Code object, it is not executed
    ast = Code([])
    result = await evaluator.eval(ast, root_scope)
    assert isinstance(result, Code)

@pytest.mark.asyncio
async def test_eval_assignment(evaluator, root_scope):
    ast = [[SetPath([Name('x')]), 10]]
    await evaluator.eval(ast, root_scope)
    assert root_scope['x'] == 10

@pytest.mark.asyncio
async def test_eval_prefix_call(evaluator, root_scope):
    ast = [[GetPath([Name('add')]), 2, 3]]
    assert await evaluator.eval(ast, root_scope) == 5

@pytest.mark.asyncio
async def test_eval_infix_call(evaluator, root_scope):
    # AST for `10 + 20`
    ast = [[10, GetPath([Name('+')]), 20]]
    assert await evaluator.eval(ast, root_scope) == 30

@pytest.mark.asyncio
async def test_eval_if_true(evaluator, root_scope):
    # AST for `if true ['then'] ['else']`
    ast = [[
        GetPath([Name('if')]),
        Code([[GetPath([Name('true')])]]),
        Code([['then']]),
        Code([['else']])
    ]]
    assert await evaluator.eval(ast, root_scope) == 'then'

@pytest.mark.asyncio
async def test_eval_if_false(evaluator, root_scope):
    # AST for `if false ['then'] ['else']`
    ast = [[
        GetPath([Name('if')]),
        Code([[GetPath([Name('false')])]]),
        Code([['then']]),
        Code([['else']])
    ]]
    assert await evaluator.eval(ast, root_scope) == 'else'

@pytest.mark.asyncio
async def test_eval_if_no_else(evaluator, root_scope):
    # AST for `if false ['then'] []`
    ast = [[
        GetPath([Name('if')]),
        Code([[GetPath([Name('false')])]]),
        Code([['then']]),
        Code([])
    ]]
    assert await evaluator.eval(ast, root_scope) is None

@pytest.mark.asyncio
async def test_eval_del(evaluator, root_scope):
    root_scope['to_del'] = 100
    # AST for `~to_del`
    ast = [[DelPath(GetPath([Name('to_del')]))]]
    await evaluator.eval(ast, root_scope)
    assert 'to_del' not in root_scope

@pytest.mark.asyncio
async def test_eval_fn_def(evaluator, root_scope):
    # AST for `fn [] []`
    ast = [[
        GetPath([Name('fn')]),
        Code([]),
        Code([])
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert isinstance(result, SlipFunction)
    assert result.closure is root_scope

@pytest.mark.asyncio
async def test_eval_fn_call(evaluator, root_scope):
    # AST for: (fn [x] [x + x]) 5
    fn_def_ast = [
        GetPath([Name('fn')]),
        Code([GetPath([Name('x')])]),
        Code([
            [
                GetPath([Name('x')]),
                GetPath([Name('+')]),
                GetPath([Name('x')])
            ]
        ])
    ]
    call_ast = [[Group([fn_def_ast]), 5]]
    assert await evaluator.eval(call_ast, root_scope) == 10

@pytest.mark.asyncio
async def test_eval_closure(evaluator, root_scope):
    # Equivalent to:
    # y: 1
    # make_adder: fn [x] [ fn [z] [x+y+z] ]
    # add5: make_adder 4
    # add5 10
    root_scope['y'] = 1
    
    inner_fn_body = [
        [
            GetPath([Name('x')]), GetPath([Name('+')]), GetPath([Name('y')]),
            GetPath([Name('+')]), GetPath([Name('z')])
        ]
    ]
    inner_fn = [
        GetPath([Name('fn')]),
        Code([[GetPath([Name('z')])]]),
        Code(inner_fn_body)
    ]
    make_adder_body = Code([inner_fn])
    make_adder_def_ast = [
        SetPath([Name('make_adder')]),
        GetPath([Name('fn')]),
        Code([[GetPath([Name('x')])]]),
        make_adder_body
    ]
    set_add5_ast = [
        SetPath([Name('add5')]),
        GetPath([Name('make_adder')]), 4
    ]
    call_add5_ast = [[GetPath([Name('add5')]), 10]]

    # Execute in sequence
    await evaluator.eval([make_adder_def_ast], root_scope)
    await evaluator.eval([set_add5_ast], root_scope)
    result = await evaluator.eval(call_add5_ast, root_scope)
    
    # x=4, y=1, z=10 -> 4 + 1 + 10 = 15
    assert result == 15

@pytest.mark.asyncio
async def test_eval_list_literal_simple(evaluator, root_scope):
    # #[1, a] -> [1, 1] given root_scope['a'] == 1
    from slip.slip_datatypes import List as SlipList
    ast = SlipList([[1], [GetPath([Name('a')])]])
    result = await evaluator.eval(ast, root_scope)
    assert result == [1, 1]

@pytest.mark.asyncio
async def test_logical_and_prefix_short_circuit_false(evaluator, root_scope):
    # logical-and false <rhs> should not evaluate RHS and return false
    ast = [[
        GetPath([Name('logical-and')]),
        GetPath([Name('false')]),
        GetPath([Name('not-exist')])  # would raise if evaluated
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert result is False

@pytest.mark.asyncio
async def test_logical_or_prefix_short_circuit_true(evaluator, root_scope):
    # logical-or true <rhs> should not evaluate RHS and return true
    ast = [[
        GetPath([Name('logical-or')]),
        GetPath([Name('true')]),
        GetPath([Name('not-exist')])  # would raise if evaluated
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert result is True

@pytest.mark.asyncio
async def test_logical_and_infix_short_circuit_and_eval(evaluator, root_scope):
    # Set infix aliases: and -> |logical-and
    root_scope['and'] = PipedPath([Name('logical-and')])
    # false and <rhs> should short-circuit to false
    ast_false = [[GetPath([Name('false')]), GetPath([Name('and')]), GetPath([Name('not-exist')])]]
    assert await evaluator.eval(ast_false, root_scope) is False
    # true and 42 should evaluate RHS and return 42
    ast_true = [[GetPath([Name('true')]), GetPath([Name('and')]), 42]]
    assert await evaluator.eval(ast_true, root_scope) == 42

@pytest.mark.asyncio
async def test_logical_or_infix_short_circuit_and_eval(evaluator, root_scope):
    # Set infix aliases: or -> |logical-or
    root_scope['or'] = PipedPath([Name('logical-or')])
    # true or <rhs> should short-circuit to true
    ast_true = [[GetPath([Name('true')]), GetPath([Name('or')]), GetPath([Name('not-exist')])]]
    assert await evaluator.eval(ast_true, root_scope) is True
    # false or 7 should evaluate RHS and return 7
    ast_false = [[GetPath([Name('false')]), GetPath([Name('or')]), 7]]
    assert await evaluator.eval(ast_false, root_scope) == 7

@pytest.mark.asyncio
async def test_fn_with_sig_and_rest_binding(evaluator, root_scope):
    # Define a function via fn with a Sig (one positional x, rest...)
    from slip.slip_datatypes import Sig as SigType
    sig = SigType(['x'], {}, 'rest', None)
    body = Code([[GetPath([Name('len')]), GetPath([Name('rest')])]])
    fn_def = [[GetPath([Name('fn')]), sig, body]]
    fn_val = await evaluator.eval(fn_def, root_scope)
    # Call the function with 4 args: x=1, rest=[2,3,4] -> len(rest) == 3
    call_ast = [[Group([fn_def[0]]), 1, 2, 3, 4]]
    result = await evaluator.eval(call_ast, root_scope)
    assert result == 3

@pytest.mark.asyncio
async def test_get_filter_query_on_list(evaluator, root_scope):
    # nums[> 20] -> #[100, 42]
    root_scope['nums'] = [15, 7, 100, 42]
    path = GetPath([Name('nums'), FilterQuery('>', [20])])
    result = await evaluator.path_resolver.get(path, root_scope)
    assert result == [100, 42]

@pytest.mark.asyncio
async def test_get_filter_query_on_non_list_returns_view(evaluator, root_scope):
    # Filtering a non-list (e.g., dict) returns a View placeholder for now
    path = GetPath([Name('b'), FilterQuery('>', [10])])
    result = await evaluator.path_resolver.get(path, root_scope)
    assert isinstance(result, View)

@pytest.mark.asyncio
async def test_while_loops_and_returns_last_value(evaluator, root_scope):
    root_scope['i'] = 3
    # while [i] [
    #   i: i + -1
    #   i
    # ]
    ast = [[
        GetPath([Name('while')]),
        Code([[GetPath([Name('i')])]]),
        Code([
            [SetPath([Name('i')]), [GetPath([Name('i')]), GetPath([Name('+')]), -1]],
            [GetPath([Name('i')])]
        ])
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert result == 0
    assert root_scope['i'] == 0

@pytest.mark.asyncio
async def test_foreach_over_list_accumulates(evaluator, root_scope):
    root_scope['sum'] = 0
    # foreach item items [ sum: sum + item ]
    ast = [[
        GetPath([Name('foreach')]),
        GetPath([Name('item')]),
        GetPath([Name('items')]),
        Code([[SetPath([Name('sum')]), [GetPath([Name('sum')]), GetPath([Name('+')]), GetPath([Name('item')])]]])
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert result is None
    assert root_scope['sum'] == sum(root_scope['items'])

@pytest.mark.asyncio
async def test_foreach_over_dict_iterates_values(evaluator, root_scope):
    root_scope['dct'] = {'x': 1, 'y': 3}
    root_scope['acc'] = 0
    # foreach val dct [ acc: acc + val ]
    ast = [[
        GetPath([Name('foreach')]),
        GetPath([Name('val')]),
        GetPath([Name('dct')]),
        Code([[SetPath([Name('acc')]), [GetPath([Name('acc')]), GetPath([Name('+')]), GetPath([Name('val')])]]])
    ]]
    await evaluator.eval(ast, root_scope)
    assert root_scope['acc'] == 4
    # Last bound value should persist in scope
    assert root_scope['val'] == 3

@pytest.mark.asyncio
async def test_generic_dispatch_by_arity(evaluator, root_scope):
    # Define a generic function 'over' with arity-based overloads.
    from slip.slip_datatypes import Sig as SigType
    # Method 1: one argument -> returns it unchanged
    sig1 = SigType(['x'], {}, None, None)
    body1 = Code([[GetPath([Name('x')])]])
    # Method 2: two arguments -> returns x + y
    sig2 = SigType(['x', 'y'], {}, None, None)
    body2 = Code([[GetPath([Name('x')]), GetPath([Name('+')]), GetPath([Name('y')])]])

    # Add both methods to the same name; dispatcher will pick by arity.
    ast_define = [
        [SetPath([Name('over')]), GetPath([Name('fn')]), sig1, body1],
        [SetPath([Name('over')]), GetPath([Name('fn')]), sig2, body2],
    ]
    await evaluator.eval(ast_define, root_scope)

    # Call with 1 arg -> selects arity-1 method
    res1 = await evaluator.eval([[GetPath([Name('over')]), 5]], root_scope)
    assert res1 == 5

    # Call with 2 args -> selects arity-2 method
    res2 = await evaluator.eval([[GetPath([Name('over')]), 5, 7]], root_scope)
    assert res2 == 12

@pytest.mark.asyncio
async def test_generic_dispatch_by_scope_type_and_fallback(evaluator, root_scope):
    # Christen a prototype type: Character
    Character = Scope()
    await evaluator.path_resolver.set(SetPath([Name('Character')]), Character, root_scope)

    # Create an instance inheriting from Character
    player = Scope()
    player.inherit(Character)

    from slip.slip_datatypes import Sig as SigType

    # Define fallback method first (so it is used when no typed candidates match)
    # Signature: one positional parameter 'target'
    fallback_sig = SigType(['target'], {}, None, None)
    fallback_body = Code([['other']])

    # Define typed method second: typed keyword param 'target: Character'
    typed_sig = SigType([], {'target': GetPath([Name('Character')])}, None, None)
    typed_body = Code([['char']])

    ast_define = [
        [SetPath([Name('describe')]), GetPath([Name('fn')]), fallback_sig, fallback_body],
        [SetPath([Name('describe')]), GetPath([Name('fn')]), typed_sig, typed_body],
    ]
    await evaluator.eval(ast_define, root_scope)

    # Passing an instance inheriting from Character should select the typed method
    res_typed = await evaluator.eval([[GetPath([Name('describe')]), player]], root_scope)
    assert res_typed == 'char'

    # Passing a non-scope value should fall back to the untyped method
    res_fallback = await evaluator.eval([[GetPath([Name('describe')]), 123]], root_scope)
    assert res_fallback == 'other'

@pytest.mark.asyncio
async def test_explicit_pipe_simple(evaluator, root_scope):
    # 2 |add 3 -> 5
    ast = [[2, PipedPath([Name('add')]), 3]]
    assert await evaluator.eval(ast, root_scope) == 5

@pytest.mark.asyncio
async def test_explicit_pipe_div_and_chain(evaluator, root_scope):
    # 10 |div 2 -> 5.0
    ast1 = [[10, PipedPath([Name('div')]), 2]]
    assert await evaluator.eval(ast1, root_scope) == 5.0
    # 10 |div 2 |mul 3 -> 15.0
    ast2 = [[10, PipedPath([Name('div')]), 2, PipedPath([Name('mul')]), 3]]
    assert await evaluator.eval(ast2, root_scope) == 15.0

@pytest.mark.asyncio
async def test_explicit_pipe_as_rhs_raises_type_error(evaluator, root_scope):
    # Using a pipe as the RHS argument should error: 1 |add |mul
    ast = [[1, PipedPath([Name('add')]), PipedPath([Name('mul')])]]
    with pytest.raises(TypeError):
        await evaluator.eval(ast, root_scope)

@pytest.mark.asyncio
async def test_set_with_parent_segment_updates_parent_scope(evaluator, child_scope):
    # ../a: should update parent’s 'a'
    path = SetPath([Parent, Name('a')])
    await evaluator.path_resolver.set(path, 77, child_scope)
    assert child_scope.parent['a'] == 77
    assert 'a' not in child_scope.bindings

@pytest.mark.asyncio
async def test_mixin_typed_dispatch(evaluator, root_scope):
    from slip.slip_datatypes import Sig as SigType
    # Define a capability mixin
    Burning = Scope()
    await evaluator.path_resolver.set(SetPath([Name('Burning')]), Burning, root_scope)

    # Instance with the mixin
    entity = Scope()
    entity.add_mixin(Burning)

    # Define generic function 'describe' with fallback and mixin-typed method
    fallback_sig = SigType(['x'], {}, None, None)
    fallback_body = Code([['other']])

    mixin_sig = SigType([], {'x': GetPath([Name('Burning')])}, None, None)
    mixin_body = Code([['on-fire']])

    ast_define = [
        [SetPath([Name('describe')]), GetPath([Name('fn')]), fallback_sig, fallback_body],
        [SetPath([Name('describe')]), GetPath([Name('fn')]), mixin_sig, mixin_body],
    ]
    await evaluator.eval(ast_define, root_scope)

    res = await evaluator.eval([[GetPath([Name('describe')]), entity]], root_scope)
    assert res == 'on-fire'
