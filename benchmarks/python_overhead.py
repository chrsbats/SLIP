"""Compare preloaded SLIP functions with equivalent direct Python functions."""
import argparse
import asyncio
import copy
import gc
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter_ns

from slip import ScriptRunner


SOURCE_PATH = Path(__file__).with_suffix(".slip")
BATCH_NS = 100_000_000
WARMUP_CALLS = 3


def loop_sum(count):
    total = 0
    i = 0
    while i < count:
        total = total + i
        i = i + 1
    return total


def increment(value):
    return value + 1


def function_calls(count):
    total = 0
    i = 0
    while i < count:
        total = increment(total)
        i = i + 1
    return total


def traverse_objects(objects):
    count = 0
    total = 0
    for obj in objects:
        if obj["visible"]:
            count = count + 1
            total = total + obj["stats"]["weight"]
    return [count, total]


def make_cases():
    objects = [
        {
            "id": f"item-{i}",
            "name": f"Item {i}",
            "visible": i % 3 != 0,
            "stats": {"weight": i + 1},
        }
        for i in range(40)
    ]
    return {
        "loop-sum": (loop_sum, [1000], 499500),
        "function-calls": (function_calls, [1000], 1000),
        "traverse-objects": (traverse_objects, [objects], [26, 533]),
    }


async def prepare():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    start = perf_counter_ns()
    runner = ScriptRunner()
    loaded = await runner.handle_script(source)
    elapsed = perf_counter_ns() - start
    if loaded.status != "ok":
        raise RuntimeError(loaded.error_message)
    return runner, elapsed


def python_batch(function, args, calls):
    start = perf_counter_ns()
    for _ in range(calls):
        result = function(*args)
    return perf_counter_ns() - start, result


async def slip_batch(call, function, args, scope, calls):
    start = perf_counter_ns()
    for _ in range(calls):
        result = await call(function, args, scope)
    return perf_counter_ns() - start, result


def check_result(name, result, expected, args, original):
    if result != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {result!r}")
    if args != original:
        raise AssertionError(f"{name}: workload mutated its input")


def summarize(samples, calls):
    return {
        "calls_per_batch": calls,
        "samples_ns_per_call": samples,
        "median_ns": statistics.median(samples),
        "min_ns": min(samples),
        "max_ns": max(samples),
    }


async def measure_case(runner, name, function, args, expected, samples):
    call = runner.evaluator.call
    scope = runner.root_scope
    slip_function = scope[name]
    original = copy.deepcopy(args)
    for _ in range(WARMUP_CALLS):
        check_result(name, function(*args), expected, args, original)
        result = await call(slip_function, args, scope)
        check_result(name, result, expected, args, original)

    python_calls = 1
    while True:
        elapsed, result = python_batch(function, args, python_calls)
        check_result(name, result, expected, args, original)
        if elapsed >= BATCH_NS:
            break
        python_calls *= 2

    slip_calls = 1
    while True:
        elapsed, result = await slip_batch(
            call, slip_function, args, scope, slip_calls
        )
        check_result(name, result, expected, args, original)
        if elapsed >= BATCH_NS:
            break
        slip_calls *= 2

    python_samples = []
    slip_samples = []
    for sample in range(samples):
        # Alternate order to reduce a systematic first/second timing bias.
        if sample % 2 == 0:
            elapsed, result = python_batch(function, args, python_calls)
            check_result(name, result, expected, args, original)
            python_samples.append(elapsed / python_calls)
        elapsed, result = await slip_batch(
            call, slip_function, args, scope, slip_calls
        )
        check_result(name, result, expected, args, original)
        slip_samples.append(elapsed / slip_calls)
        if sample % 2 != 0:
            elapsed, result = python_batch(function, args, python_calls)
            check_result(name, result, expected, args, original)
            python_samples.append(elapsed / python_calls)

    if runner.evaluator.side_effects or runner.evaluator.call_stack:
        raise AssertionError(f"{name}: retained effects or call frames")
    python = summarize(python_samples, python_calls)
    slip = summarize(slip_samples, slip_calls)
    return {
        "name": name,
        "input_size": len(args[0]) if isinstance(args[0], list) else args[0],
        "result": expected,
        "python": python,
        "slip": slip,
        "slip_to_python_ratio": slip["median_ns"] / python["median_ns"],
        "extra_ns_per_call": slip["median_ns"] - python["median_ns"],
    }


async def benchmark(samples=7):
    if os.environ.get("SLIP_DEBUG"):
        raise ValueError("Unset SLIP_DEBUG before measuring overhead")
    if samples < 1:
        raise ValueError("samples must be positive")
    runner, preparation_ns = await prepare()
    results = []
    for name, (function, args, expected) in make_cases().items():
        results.append(await measure_case(
            runner, name, function, args, expected, samples
        ))
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "koine_version": version("koine"),
        "gc_enabled": gc.isenabled(),
        "preparation_ns": preparation_ns,
        "preparation_scope": (
            "runner construction and SLIP loading; imports excluded"
        ),
        "timing_scope": "warm Evaluator.call versus direct Python call",
        "batch_target_ns": BATCH_NS,
        "warmup_calls": WARMUP_CALLS,
        "source_sha256": {
            "slip": hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
            "python": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    report = asyncio.run(benchmark(options.samples))
    preparation_ms = report["preparation_ns"] / 1e6
    print(f"Preparation (imports excluded): {preparation_ms:.1f} ms")
    print(f"{'Case':20} {'Python us':>12} {'SLIP us':>12} {'Ratio':>10}")
    for case in report["cases"]:
        print(
            f"{case['name']:20} {case['python']['median_ns'] / 1000:12.2f} "
            f"{case['slip']['median_ns'] / 1000:12.2f} "
            f"{case['slip_to_python_ratio']:9.1f}x"
        )
    if options.output:
        options.output.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Saved {options.output}")


if __name__ == "__main__":
    main()
