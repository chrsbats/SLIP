import pytest
from slip.slip_runtime import StdLib
from slip.slip_interpreter import Evaluator, View
from slip.slip_datatypes import Scope, GetPath, SetPath, DelPath, Name, Index, Slice, FilterQuery, Group, Parent, Root, Pwd, Code, SlipFunction, PipedPath, Sig
from slip.slip_datatypes import PathLiteral, IString
from slip.slip_datatypes import PathNotFound

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
        Sig(['item'], {}, None, None),
        GetPath([Name('items')]),
        Code([[SetPath([Name('sum')]), [GetPath([Name('sum')]), GetPath([Name('+')]), GetPath([Name('item')])]]])
    ]]
    result = await evaluator.eval(ast, root_scope)
    assert result is None
    assert root_scope['sum'] == sum(root_scope['items'])

@pytest.mark.asyncio
async def test_foreach_over_dict_iterates_keys(evaluator, root_scope):
    root_scope['dct'] = {'x': 1, 'y': 3}
    root_scope['acc'] = 0
    # foreach k dct [ acc: acc + dct[k] ]
    ast = [[
        GetPath([Name('foreach')]),
        Sig(['k'], {}, None, None),
        GetPath([Name('dct')]),
        Code([[SetPath([Name('acc')]), [GetPath([Name('acc')]), GetPath([Name('+')]), GetPath([Name('dct'), Index([[GetPath([Name('k')])]])])]]])
    ]]
    await evaluator.eval(ast, root_scope)
    assert root_scope['acc'] == 4
    # Last bound key should persist in scope
    assert root_scope['k'] == 'y'

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

@pytest.mark.asyncio
async def test_vectorized_assign_name_then_filter(evaluator, root_scope):
    # players.hp[< 50]: 50
    root_scope['players'] = [
        {'hp': 45, 'name': 'A'},
        {'hp': 55, 'name': 'B'},
        {'hp': 10, 'name': 'C'},
    ]
    set_path = SetPath([Name('players'), Name('hp'), FilterQuery('<', [50])])
    ast = [[set_path, 50]]
    res = await evaluator.eval(ast, root_scope)
    assert res == [50, 50]
    assert [p['hp'] for p in root_scope['players']] == [50, 55, 50]

@pytest.mark.asyncio
async def test_vectorized_update_filter_then_name_with_predicate_ast(evaluator, root_scope):
    # players[.hp < 50].hp: + 10
    root_scope['players'] = [
        {'hp': 40, 'name': 'a'},
        {'hp': 60, 'name': 'b'},
        {'hp': 20, 'name': 'c'},
    ]
    pred = [GetPath([Name('.hp')]), GetPath([Name('<')]), 50]
    fq = FilterQuery(None, None, pred)
    set_path = SetPath([Name('players'), fq, Name('hp')])
    ast = [[set_path, GetPath([Name('+')]), 10]]
    res = await evaluator.eval(ast, root_scope)
    assert res == [50, 30]  # returns list of new values written
    assert [p['hp'] for p in root_scope['players']] == [50, 60, 30]

@pytest.mark.asyncio
async def test_alias_write_redirects_to_existing_path(evaluator, root_scope):
    # alias: 5 should write to target when alias resolves to GetPath('target')
    root_scope['target'] = 1
    root_scope['alias'] = GetPath([Name('target')])
    ast = [[SetPath([Name('alias')]), 5]]
    res = await evaluator.eval(ast, root_scope)
    assert res == 5
    assert root_scope['target'] == 5
    # alias binding remains (was not overwritten by value)
    assert isinstance(root_scope['alias'], GetPath)

@pytest.mark.asyncio
async def test_scope_christening_sets_type_id_and_registry(evaluator, root_scope):
    from slip.slip_interpreter import TYPE_REGISTRY
    proto = Scope()
    ast = [[SetPath([Name('Character')]), proto]]
    await evaluator.eval(ast, root_scope)
    # meta fields set
    assert 'type_id' in proto.meta and isinstance(proto.meta['type_id'], int)
    assert proto.meta.get('name') == 'Character'
    # registry updated
    assert TYPE_REGISTRY.get('Character') == proto.meta['type_id']

@pytest.mark.asyncio
async def test_dict_literal_istring_sugar_inside_dict_literal(evaluator, root_scope):
    # ('dict', [ [SetPath([Name('msg')]), GetPath([Name('i')]), IString("Hi")] ])
    dict_expr = [
        [SetPath([Name('msg')]), GetPath([Name('i')]), IString("Hello")]
    ]
    result = await evaluator.eval(('dict', dict_expr), root_scope)
    # Returns a SlipDict mapping; value is the raw IString
    assert result['msg'] == IString("Hello")

@pytest.mark.asyncio
async def test_delete_prune_preserves_top_level_lowercase_binding(evaluator, root_scope):
    # temp: scope {}; temp.x: 1; ~temp.x -> 'temp' binding should remain (lowercase)
    temp = Scope()
    await evaluator.path_resolver.set(SetPath([Name('temp')]), temp, root_scope)
    await evaluator.path_resolver.set(SetPath([Name('temp'), Name('x')]), 1, root_scope)
    await evaluator.eval([[DelPath(GetPath([Name('temp'), Name('x')]))]], root_scope)
    assert 'temp' in root_scope  # preserved
    assert isinstance(root_scope['temp'], Scope)
    assert 'x' not in root_scope['temp'].bindings  # deleted leaf

@pytest.mark.asyncio
async def test_operator_as_path_literal_for_infix(evaluator, root_scope):
    # 1 `|add` 2 (operator provided as PathLiteral(PipedPath(...)))
    op_lit = PathLiteral(PipedPath([Name('add')]))
    ast = [[1, op_lit, 2]]
    result = await evaluator.eval(ast, root_scope)
    assert result == 3

@pytest.mark.asyncio
async def test_autocall_zero_arity_function_used_as_argument(evaluator, root_scope):
    # Define a zero-arity SlipFunction: fn {} [42]
    zero_fn_ast = [GetPath([Name('fn')]), Code([]), Code([[42]])]
    zero_fn = await evaluator.eval(zero_fn_ast, root_scope)
    # add (fn {} [42]) 8 -> 50 (argument auto-invoked)
    call_ast = [[GetPath([Name('add')]), Group([zero_fn_ast]), 8]]
    out = await evaluator.eval(call_ast, root_scope)
    assert out == 50

from slip.slip_datatypes import PostPath

@pytest.mark.asyncio
async def test_infix_div_with_root_token_normalization(evaluator, root_scope):
    # Map '/' to |div and ensure GetPath([Root]) normalizes to Name('/')
    root_scope['/'] = PipedPath([Name('div')])
    ast = [[10, GetPath([Root]), 2]]
    out = await evaluator.eval(ast, root_scope)
    assert out == 5.0

@pytest.mark.asyncio
async def test_operator_alias_cycle_detection_raises(evaluator, root_scope):
    # op1 -> op2, op2 -> op1 (cycle)
    root_scope['op1'] = GetPath([Name('op2')])
    root_scope['op2'] = GetPath([Name('op1')])
    ast = [[1, GetPath([Name('op1')]), 2]]
    with pytest.raises(RecursionError):
        await evaluator.eval(ast, root_scope)

@pytest.mark.asyncio
async def test_operator_unexpected_term_raises(evaluator, root_scope):
    # Operator resolves to a non-path/non-piped value -> TypeError
    root_scope['bogus'] = 123
    ast = [[1, GetPath([Name('bogus')]), 2]]
    with pytest.raises(TypeError):
        await evaluator.eval(ast, root_scope)

@pytest.mark.asyncio
async def test_operator_as_path_literal_getpath_unwrap(evaluator, root_scope):
    # Use a PathLiteral(GetPath('+')), with '+' already bound to |add
    op_lit = PathLiteral(GetPath([Name('+')]))
    ast = [[3, op_lit, 4]]
    res = await evaluator.eval(ast, root_scope)
    assert res == 7

@pytest.mark.asyncio
async def test_http_get_packaging_lite_and_full(monkeypatch, evaluator, root_scope):
    # Patch http_get to return a tuple (status, value, headers)
    async def fake_http_get(url, config=None):
        return (200, {'ok': True}, {'Content-Type': 'application/json'})
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_get", fake_http_get)
    # Build path with meta #(response-mode: 'lite')
    meta_lite = Group([[ [SetPath([Name('response-mode')]), 'lite'] ]])
    p_lite = GetPath([Name('http://example/api')], meta=meta_lite)
    out_lite = await evaluator.path_resolver.get(p_lite, root_scope)
    assert out_lite == [200, {'ok': True}]
    # Full
    meta_full = Group([[ [SetPath([Name('response-mode')]), 'full'] ]])
    p_full = GetPath([Name('http://example/api')], meta=meta_full)
    out_full = await evaluator.path_resolver.get(p_full, root_scope)
    assert out_full['status'] == 200 and out_full['value'] == {'ok': True}
    assert out_full['meta']['headers']['content-type'] == 'application/json'

@pytest.mark.asyncio
async def test_http_get_rejects_trailing_segments(evaluator, root_scope):
    # Trailing path segments after http URL are rejected
    p = GetPath([Name('http://example/api'), Name('extra')])
    with pytest.raises(TypeError):
        await evaluator.path_resolver.get(p, root_scope)

@pytest.mark.asyncio
async def test_http_put_content_type_promotion_and_serialization(monkeypatch, evaluator, root_scope):
    captured = {}
    async def fake_http_put(url, payload, config=None):
        captured['url'] = url
        captured['payload'] = payload
        captured['headers'] = (config or {}).get('headers', {})
        return None
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_put", fake_http_put)
    # file: use http set-path with #(content-type: "application/json")
    meta = Group([[ [SetPath([Name('content-type')]), "application/json"] ]])
    sp = SetPath([Name('http://example/put')], meta=meta)
    await evaluator.path_resolver.set(sp, {'a': 1}, root_scope)
    assert captured['url'] == 'http://example/put'
    assert isinstance(captured['payload'], str) and '"a"' in captured['payload']
    assert captured['headers'].get('Content-Type') == 'application/json'

@pytest.mark.asyncio
async def test_http_post_packaging_lite_and_full(monkeypatch, evaluator, root_scope):
    async def fake_http_post(url, payload, config=None):
        return (201, {'id': 7}, {'Content-Type': 'application/json; charset=utf-8'})
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_post", fake_http_post)
    # lite
    meta_lite = Group([[ [SetPath([Name('response-mode')]), 'lite'] ]])
    pp_lite = PostPath([Name('http://example/items')], meta=meta_lite)
    out_lite = await evaluator.path_resolver.post(pp_lite, {'x': 1}, root_scope)
    assert out_lite == [201, {'id': 7}]
    # full
    meta_full = Group([[ [SetPath([Name('response-mode')]), 'full'] ]])
    pp_full = PostPath([Name('http://example/items')], meta=meta_full)
    out_full = await evaluator.path_resolver.post(pp_full, {'x': 1}, root_scope)
    assert out_full['status'] == 201 and out_full['value'] == {'id': 7}
    assert 'headers' in out_full['meta']

@pytest.mark.asyncio
async def test_alias_write_from_pathliteral(evaluator, root_scope):
    # alias holds a PathLiteral(GetPath('target')); write should redirect to target
    root_scope['target'] = 0
    root_scope['alias'] = PathLiteral(GetPath([Name('target')]))
    ast = [[SetPath([Name('alias')]), 11]]
    res = await evaluator.eval(ast, root_scope)
    assert res == 11
    assert root_scope['target'] == 11
    # alias binding remains a PathLiteral
    from slip.slip_datatypes import PathLiteral as _PL
    assert isinstance(root_scope['alias'], _PL)

@pytest.mark.asyncio
async def test_code_expand_splice_expr_requires_list_error(evaluator, root_scope):
    # Inside expression position, splice must evaluate to a list -> TypeError
    bad = Code([[ Group([[GetPath([Name('splice')]), 123]]) ]])
    with pytest.raises(TypeError):
        await evaluator.eval(bad, root_scope)

@pytest.mark.asyncio
async def test_multi_set_assignment_tuple_literal(evaluator, root_scope):
    # ('multi-set', [SetPath('x'), SetPath('y')]) [#[10,20]]
    expr = [
        ('multi-set', [SetPath([Name('x')]), SetPath([Name('y')])]),
        [10, 20]
    ]
    out = await evaluator.eval([expr], root_scope)
    assert out is None
    assert root_scope['x'] == 10 and root_scope['y'] == 20

@pytest.mark.asyncio
async def test_filter_query_with_and_and_empty_predicate(evaluator, root_scope):
    # players with compound predicate: .hp < 50 AND .name = 'C'
    root_scope['players'] = [
        {'hp': 45, 'name': 'A'},
        {'hp': 55, 'name': 'B'},
        {'hp': 10, 'name': 'C'},
    ]
    pred = [
        GetPath([Name('.hp')]), GetPath([Name('<')]), 50,
        GetPath([Name('and')]),
        GetPath([Name('.name')]), GetPath([Name('=')]), 'C'
    ]
    path = GetPath([Name('players'), FilterQuery(None, None, pred)])
    out = await evaluator.path_resolver.get(path, root_scope)
    assert out == [{'hp': 10, 'name': 'C'}]
    # Empty predicate (no operator) on list returns empty (keep nothing)
    path2 = GetPath([Name('players'), FilterQuery(None, None, None)])
    out2 = await evaluator.path_resolver.get(path2, root_scope)
    assert out2 == []

@pytest.mark.asyncio
async def test_get_alias_self_reference_returns_pathliteral(evaluator, root_scope):
    # x bound to GetPath('x') → avoid infinite recursion; returns PathLiteral
    root_scope['x'] = GetPath([Name('x')])
    out = await evaluator.path_resolver.get(GetPath([Name('x')]), root_scope)
    from slip.slip_datatypes import PathLiteral as _PL
    assert isinstance(out, _PL)
    assert isinstance(out.inner, GetPath)

@pytest.mark.asyncio
async def test_get_bound_pathliteral_returned_verbatim(evaluator, root_scope):
    lit = PathLiteral(GetPath([Name('a')]))
    root_scope['p'] = lit
    out = await evaluator.path_resolver.get(GetPath([Name('p')]), root_scope)
    assert out is lit

@pytest.mark.asyncio
async def test_http_delete_packaging_lite_and_full(monkeypatch, evaluator, root_scope):
    async def fake_http_delete(url, config=None):
        return (204, None, {'Content-Type': 'text/plain'})
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_delete", fake_http_delete)
    # lite
    meta_lite = Group([[ [SetPath([Name('response-mode')]), 'lite'] ]])
    dp_lite = DelPath(GetPath([Name('http://example/api')], meta=meta_lite))
    out_lite = await evaluator.path_resolver.delete(dp_lite, root_scope)
    assert out_lite == [204, None]
    # full
    meta_full = Group([[ [SetPath([Name('response-mode')]), 'full'] ]])
    dp_full = DelPath(GetPath([Name('http://example/api')], meta=meta_full))
    out_full = await evaluator.path_resolver.delete(dp_full, root_scope)
    assert out_full['status'] == 204 and out_full['value'] is None
    assert out_full['meta']['headers']['content-type'] == 'text/plain'

@pytest.mark.asyncio
async def test_code_inject_and_statement_splice_expand(evaluator, root_scope):
    # inject: substitutes value at definition-time expansion
    root_scope['val'] = 42
    code_inject = Code([[Group([[GetPath([Name('inject')]), GetPath([Name('val')])]])]])
    out_inject = await evaluator.eval(code_inject, root_scope)
    assert isinstance(out_inject, Code)
    assert out_inject.ast[0][0] == 42
    # statement-level splice: splice Code into sibling expressions
    inner = Code([[1], [2]])
    code_splice = Code([[Group([[GetPath([Name('splice')]), inner]])]])
    out_splice = await evaluator.eval(code_splice, root_scope)
    assert isinstance(out_splice, Code)
    assert out_splice.ast == [[1], [2]]

@pytest.mark.asyncio
async def test_attribute_fallback_on_plain_object_and_pluck_error(evaluator, root_scope):
    class Obj:
        def __init__(self): self.x = 5
    root_scope['obj'] = Obj()
    # Non-mapping object attribute fallback
    v = await evaluator.path_resolver.get(GetPath([Name('obj'), Name('x')]), root_scope)
    assert v == 5
    # Plucking missing field from plain objects raises TypeError
    root_scope['objs'] = [Obj()]
    with pytest.raises(TypeError):
        await evaluator.path_resolver.get(GetPath([Name('objs'), Name('y')]), root_scope)

@pytest.mark.asyncio
async def test_fold_property_chain_bare_and_dotted(evaluator, root_scope):
    # id function echoes its arg
    id_fn = await evaluator.eval([[GetPath([Name('fn')]), Sig(['x'], {}, None, None), Code([[GetPath([Name('x')])]])]], root_scope)
    await evaluator.eval([[SetPath([Name('id')]), id_fn]], root_scope)
    root_scope['thing'] = {'a': {'b': 7}}
    # Dotted chain after base
    ast1 = [[GetPath([Name('id')]), GetPath([Name('thing')]), GetPath([Name('.a')]), GetPath([Name('.b')])]]
    res1 = await evaluator.eval(ast1, root_scope)
    assert res1 == 7
    # Bare chain permitted after a Group-wrapped base
    ast2 = [[GetPath([Name('id')]), Group([[GetPath([Name('thing')])]]), GetPath([Name('a')]), GetPath([Name('b')])]]
    res2 = await evaluator.eval(ast2, root_scope)
    assert res2 == 7

@pytest.mark.asyncio
async def test_python_callable_with_scope_kwarg_and_autocall(evaluator, root_scope):
    def pyfunc(scope=None):
        return scope['a']
    root_scope['pyfunc'] = pyfunc
    out = await evaluator.eval([[GetPath([Name('pyfunc')])]], root_scope)
    assert out == 1

@pytest.mark.asyncio
async def test_delete_with_prune_false_keeps_owner_scope(evaluator, root_scope):
    holder = Scope()
    await evaluator.path_resolver.set(SetPath([Name('Temp')]), holder, root_scope)
    await evaluator.path_resolver.set(SetPath([Name('Temp'), Name('x')]), 1, root_scope)
    meta = Group([[ [SetPath([Name('prune')]), False] ]])
    await evaluator.path_resolver.delete(DelPath(GetPath([Name('Temp'), Name('x')], meta=meta)), root_scope)
    # With prune: false, the 'Temp' binding remains even if now empty
    assert 'Temp' in root_scope and isinstance(root_scope['Temp'], Scope)
    assert 'x' not in root_scope['Temp'].bindings

@pytest.mark.asyncio
async def test_file_get_not_found_raises_pathnotfound(tmp_path, evaluator, root_scope):
    locator = f"file://{(tmp_path / 'nope.txt').as_posix()}"
    with pytest.raises(PathNotFound):
        await evaluator.path_resolver.get(GetPath([Name(locator)]), root_scope)

@pytest.mark.asyncio
async def test_unary_logical_operator_missing_rhs_raises(evaluator, root_scope):
    root_scope['and'] = PipedPath([Name('logical-and')])
    with pytest.raises(SyntaxError):
        await evaluator.eval([[True, GetPath([Name('and')])]], root_scope)

@pytest.mark.asyncio
async def test_post_path_non_http_raises(evaluator, root_scope, tmp_path):
    p = tmp_path / "out.json"
    pp = PostPath([Name(f"file://{p.as_posix()}")])
    with pytest.raises(TypeError):
        await evaluator.path_resolver.post(pp, {'x': 1}, root_scope)

@pytest.mark.asyncio
async def test_http_put_convenience_from_eval(monkeypatch, evaluator, root_scope):
    captured = {}
    async def fake_http_put(url, payload, config=None):
        captured['url'] = url; captured['payload'] = payload; captured['headers'] = (config or {}).get('headers', {})
        return None
    import slip.slip_http as http_mod
    monkeypatch.setattr(http_mod, "http_put", fake_http_put)
    ast = [[GetPath([Name('http://example/put')]), {'a': 1}]]
    out = await evaluator.eval(ast, root_scope)
    assert captured['url'] == 'http://example/put'
    assert '"a"' in captured['payload']
    assert out == {'a': 1}

@pytest.mark.asyncio
async def test_dispatch_exact_arity_truncation_fallback(evaluator, root_scope):
    # Define a single-arg method; call with extra args → exact-arity truncation fallback selects it
    sig = Sig(['x'], {}, None, None)
    body = Code([[GetPath([Name('x')])]])
    await evaluator.eval([[SetPath([Name('g')]), GetPath([Name('fn')]), sig, body]], root_scope)
    res = await evaluator.eval([[GetPath([Name('g')]), 10, 20]], root_scope)
    assert res == 10
