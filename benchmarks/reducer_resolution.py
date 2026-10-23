"""Compare a resolved flat reducer with repeated symbolic resolution."""
import argparse
import copy
from functools import partial
import gc
import hashlib
import json
from operator import itemgetter
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter_ns


BATCH_NS = 100_000_000
WARMUP_CALLS = 3


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def less_than(a, b):
    return a < b


def read_resolved(term, namespace):
    return term(namespace) if callable(term) else term


def read_symbolic(term, namespace):
    if type(term) is str:
        return namespace[term]
    if type(term) is tuple:
        value = namespace
        for key in term:
            value = value[key]
        return value
    return term


def reduce_resolved(terms, namespace):
    value = read_resolved(terms[0], namespace)
    for cursor in range(1, len(terms), 2):
        rhs = read_resolved(terms[cursor + 1], namespace)
        value = terms[cursor](value, rhs)
    return value


def reduce_symbolic(terms, namespace):
    value = read_symbolic(terms[0], namespace)
    for cursor in range(1, len(terms), 2):
        rhs = read_symbolic(terms[cursor + 1], namespace)
        value = namespace[terms[cursor]](value, rhs)
    return value


def read_visible(namespace):
    return namespace["obj"]["visible"]


def read_weight(namespace):
    return namespace["obj"]["stats"]["weight"]


def prepare():
    operators = {"+": add, "-": subtract, "*": multiply, "<": less_than}
    start = perf_counter_ns()
    symbolic = {
        "chain": ["a", "+", "b", "*", "c", "-", 1],
        "condition": ["i", "<", "limit"],
        "sum": ["total", "+", "i"],
        "increment": ["i", "+", 1],
        "visible": [("obj", "visible")],
        "count": ["count", "+", 1],
        "weight": ["total", "+", ("obj", "stats", "weight")],
    }
    symbolic_ns = perf_counter_ns() - start
    start = perf_counter_ns()
    total, i, count = itemgetter("total"), itemgetter("i"), itemgetter("count")
    resolved = {
        "chain": [
            itemgetter("a"), operators["+"], itemgetter("b"),
            operators["*"], itemgetter("c"), operators["-"], 1,
        ],
        "condition": [i, operators["<"], itemgetter("limit")],
        "sum": [total, operators["+"], i],
        "increment": [i, operators["+"], 1],
        "visible": [read_visible],
        "count": [count, operators["+"], 1],
        "weight": [total, operators["+"], read_weight],
    }
    resolved_ns = perf_counter_ns() - start
    return operators, {"resolved": resolved, "symbolic": symbolic}, {
        "resolved": resolved_ns, "symbolic": symbolic_ns,
    }


def run_loop(reducer, expressions, operators, limit):
    namespace = dict(operators, total=0, i=0, limit=limit)
    while reducer(expressions["condition"], namespace):
        namespace["total"] = reducer(expressions["sum"], namespace)
        namespace["i"] = reducer(expressions["increment"], namespace)
    return namespace["total"]


def run_traversal(reducer, expressions, operators, objects):
    namespace = dict(operators, count=0, total=0)
    for obj in objects:
        namespace["obj"] = obj
        if reducer(expressions["visible"], namespace):
            namespace["count"] = reducer(expressions["count"], namespace)
            namespace["total"] = reducer(expressions["weight"], namespace)
    return [namespace["count"], namespace["total"]]


def python_chain(namespace):
    return (namespace["a"] + namespace["b"]) * namespace["c"] - 1


def python_loop(limit):
    total = 0
    i = 0
    while i < limit:
        total = total + i
        i = i + 1
    return total


def python_traversal(objects):
    count = 0
    total = 0
    for obj in objects:
        if obj["visible"]:
            count = count + 1
            total = total + obj["stats"]["weight"]
    return [count, total]


def make_cases(operators, programs):
    objects = [
        {
            "id": f"item-{i}", "name": f"Item {i}", "visible": i % 3 != 0,
            "stats": {"weight": i + 1},
        }
        for i in range(40)
    ]
    chain = {"python": python_chain}
    loop = {"python": python_loop}
    traversal = {"python": python_traversal}
    for name, reducer in (
        ("resolved", reduce_resolved), ("symbolic", reduce_symbolic),
    ):
        expressions = programs[name]
        chain[name] = partial(reducer, expressions["chain"])
        loop[name] = partial(run_loop, reducer, expressions, operators)
        traversal[name] = partial(
            run_traversal, reducer, expressions, operators,
        )
    return {
        "chain": (chain, [dict(operators, a=10, b=5, c=2)], 29),
        "loop-sum": (loop, [1000], 499500),
        "traverse-objects": (traversal, [objects], [26, 533]),
    }


def batch(function, args, calls):
    start = perf_counter_ns()
    for _ in range(calls):
        result = function(*args)
    return perf_counter_ns() - start, result


def check(name, result, expected, args, original):
    if result != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {result!r}")
    if args != original:
        raise AssertionError(f"{name}: workload mutated its input")


def measure_case(name, implementations, args, expected, samples):
    original = copy.deepcopy(args)
    batches = {}
    timings = {name: [] for name in implementations}
    for implementation, function in implementations.items():
        for _ in range(WARMUP_CALLS):
            check(name, function(*args), expected, args, original)
        calls = 1
        while True:
            elapsed, result = batch(function, args, calls)
            check(name, result, expected, args, original)
            if elapsed >= BATCH_NS:
                break
            calls *= 2
        batches[implementation] = calls

    order = list(implementations)
    for sample in range(samples):
        offset = sample % len(order)
        for implementation in order[offset:] + order[:offset]:
            elapsed, result = batch(
                implementations[implementation], args, batches[implementation],
            )
            check(name, result, expected, args, original)
            timings[implementation].append(elapsed / batches[implementation])
    summaries = {
        implementation: {
            "calls_per_batch": batches[implementation],
            "samples_ns_per_call": values,
            "median_ns": statistics.median(values),
            "min_ns": min(values), "max_ns": max(values),
        }
        for implementation, values in timings.items()
    }
    python = summaries["python"]["median_ns"]
    resolved = summaries["resolved"]["median_ns"]
    symbolic = summaries["symbolic"]["median_ns"]
    return {
        "name": name, "result": expected, "timings": summaries,
        "resolved_to_python_ratio": resolved / python,
        "symbolic_to_python_ratio": symbolic / python,
        "symbolic_to_resolved_ratio": symbolic / resolved,
    }


def benchmark(samples=7):
    if samples < 1:
        raise ValueError("samples must be positive")
    operators, programs, preparation = prepare()
    results = [
        measure_case(name, implementations, args, expected, samples)
        for name, (implementations, args, expected)
        in make_cases(operators, programs).items()
    ]
    return {
        "python_version": sys.version, "platform": platform.platform(),
        "gc_enabled": gc.isenabled(), "preparation_ns": preparation,
        "preparation_scope": (
            "expression lists and accessors; imports, function definitions, "
            "shared operator registry and fixtures excluded"
        ),
        "timing_scope": "complete warm workload calls; shared reducer drivers",
        "batch_target_ns": BATCH_NS, "warmup_calls": WARMUP_CALLS,
        "sample_order": "rotate python, resolved, symbolic by sample index",
        "source_sha256": hashlib.sha256(
            Path(__file__).read_bytes(),
        ).hexdigest(),
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    report = benchmark(options.samples)
    print("Expression/accessor preparation (us):", {
        name: round(value / 1000, 2)
        for name, value in report["preparation_ns"].items()
    })
    print(
        f"{'Case':20} {'Python us':>12} {'Resolved us':>12} "
        f"{'Symbolic us':>12} {'Sym/Res':>9} {'Res/Py':>9}"
    )
    for case in report["cases"]:
        timings = case["timings"]
        print(
            f"{case['name']:20} "
            f"{timings['python']['median_ns'] / 1000:12.2f} "
            f"{timings['resolved']['median_ns'] / 1000:12.2f} "
            f"{timings['symbolic']['median_ns'] / 1000:12.2f} "
            f"{case['symbolic_to_resolved_ratio']:8.2f}x "
            f"{case['resolved_to_python_ratio']:8.2f}x"
        )
    if options.output:
        options.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Saved {options.output}")


if __name__ == "__main__":
    main()
