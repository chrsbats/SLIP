import pytest
import asyncio
from slip.slip_runtime import ScriptRunner

def run_slip(code):
    runner = ScriptRunner()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(runner.handle_script(code))
    finally:
        loop.close()

def test_debug_infix_and_operator():
    code = """
    -- If this fails, `and` (from root.slip) is not executable as an infix operator.
    (true and false)
    """
    res = run_slip(code)
    if res.status != 'ok':
        print("SLIP ERROR (test_debug_infix_and_operator):")
        print(res.error_message)
        print("EFFECTS:", res.side_effects)
    assert res.status == 'ok'
    assert res.value is False

def test_basic_where_sugar():
    # Basic smoke test: where clause selects the guarded method.
    code = """
    gt-10: fn { n |where n > 10 } [ true ]
    gt-10: fn { n } [ false ]

    #[ gt-10 15, gt-10 5 ]
    """
    res = run_slip(code)
    if res.status != 'ok':
        print("SLIP ERROR (test_basic_where_sugar):")
        print(res.error_message)
        print("EFFECTS:", res.side_effects)
    assert res.status == 'ok'
    assert res.value == [True, False]

def test_where_with_multiple_conditions():
    code = """
    check: fn { n |where n > 10 and n < 20 } [ `in-range` ]
    check: fn { n } [ `out-of-range` ]
    #[ check 15, check 5, check 25 ]
    """
    res = run_slip(code)
    if res.status != 'ok':
        print("SLIP ERROR (test_where_with_multiple_conditions):")
        print(res.error_message)
        print("EFFECTS:", res.side_effects)
    assert res.status == 'ok'
    assert res.value == ["`in-range`", "`out-of-range`", "`out-of-range`"]

def test_where_accesses_lexical_scope():
    code = """
    limit: 100
    over-limit: fn { n |where n > limit } [ true ]
    over-limit: fn { n } [ false ]
    
    #[ over-limit 150, over-limit 50 ]
    """
    res = run_slip(code)
    if res.status != 'ok':
        print("SLIP ERROR (test_where_accesses_lexical_scope):")
        print(res.error_message)
        print("EFFECTS:", res.side_effects)
    assert res.status == 'ok'
    assert res.value == [True, False]

def test_where_in_resolver_transaction():
    code = """
    Bank: resolver #{ balance: 100 }

    withdraw: fn { this: Bank, amount |where amount > 0 and this.balance >= amount } [
        this.balance: this.balance - amount
        response ok this.balance
    ]

    withdraw: fn { this: Bank, amount } [
        response err "insufficient-funds"
    ]

    res1: Bank |withdraw 40
    res2: Bank |withdraw 100

    #[ res1.value, res2.status ]
    """
    res = run_slip(code)
    if res.status != 'ok':
        print("SLIP ERROR (test_where_in_resolver_transaction):")
        print(res.error_message)
        print("EFFECTS:", res.side_effects)
    assert res.status == 'ok'
    assert res.value == [60, "`err`"]

def test_where_syntax_error_multiple_clauses():
    # Grammar only allows one optional sig_where; a second |where should be a parse error.
    code = "f: fn { n |where n > 0 |where n < 10 } [ n ]"
    res = run_slip(code)
    assert res.status == 'err'
