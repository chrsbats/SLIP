"""Compare preloaded SLIP functions with equivalent direct Python functions."""
import argparse
import asyncio
import copy
import cProfile
import gc
import hashlib
import inspect
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import pstats
import statistics
import sys
from time import perf_counter_ns

from slip import ScriptRunner
import slip as slip_package


SOURCE_PATH = Path(__file__).with_suffix(".slip")
BATCH_NS = 100_000_000
WARMUP_CALLS = 3
ASYNC = inspect.iscoroutinefunction(ScriptRunner.handle_script)


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
    loaded = runner.handle_script(source)
    if ASYNC:
        loaded = await loaded
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
    if ASYNC:
        for _ in range(calls):
            result = await call(function, args, scope)
    else:
        for _ in range(calls):
            result = call(function, args, scope)
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
    if ASYNC:
        call, scope = runner.evaluator.call, runner.root_scope
    else:
        from slip.slip_core import invoke
        call, scope = invoke, runner.scope
    slip_function = scope[name]
    original = copy.deepcopy(args)
    for _ in range(WARMUP_CALLS):
        check_result(name, function(*args), expected, args, original)
        _, result = await slip_batch(call, slip_function, args, scope, 1)
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

    effects = runner.evaluator.side_effects if ASYNC else scope.effects
    if effects or (ASYNC and runner.evaluator.call_stack):
        raise AssertionError(f"{name}: retained effects or call frames")
    profile = cProfile.Profile()
    profile.enable()
    _, result = await slip_batch(call, slip_function, args, scope, 1)
    profile.disable()
    check_result(name, result, expected, args, original)
    package = Path(slip_package.__file__).resolve().parent
    counts = {}
    for (filename, _, label), entry in pstats.Stats(profile).stats.items():
        path = Path(filename)
        if path.is_relative_to(package):
            key = path.name + ':' + label
            counts[key] = counts.get(key, 0) + entry[1]
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
        "profile_calls": counts,
        "inputs_unchanged": args == original,
        "effects_empty": not effects,
    }


async def benchmark(samples=7):
    if os.environ.get("SLIP_DEBUG"):
        raise ValueError("Unset SLIP_DEBUG before measuring overhead")
    if samples < 1:
        raise ValueError("samples must be positive")
    runner, preparation_ns = await prepare()
    try:
        results = []
        for name, (function, args, expected) in make_cases().items():
            results.append(await measure_case(
                runner, name, function, args, expected, samples
            ))
    finally:
        close = getattr(runner, 'close', None)
        if close is not None:
            result = close()
            if ASYNC:
                await result
    package = Path(slip_package.__file__).resolve().parent
    sources = sorted(path for path in package.rglob('*')
                     if path.suffix in {'.py', '.slip', '.yaml'})
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "koine_version": version("koine"),
        "gc_enabled": gc.isenabled(),
        "preparation_ns": preparation_ns,
        "preparation_scope": (
            "runner construction and SLIP loading; imports excluded"
        ),
        "timing_scope": "warm native invocation versus direct Python call",
        "execution": "async" if ASYNC else "synchronous",
        "slip_version": version("slip"),
        "package_path": str(package),
        "batch_target_ns": BATCH_NS,
        "warmup_calls": WARMUP_CALLS,
        "source_sha256": {
            "slip": hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
            "python": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "runtime_sha256": {
            str(path.relative_to(package)):
                hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
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
