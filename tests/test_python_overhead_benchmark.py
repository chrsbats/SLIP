import copy

import pytest

from benchmarks import python_overhead
from slip import ScriptRunner


@pytest.mark.asyncio
async def test_benchmark_workloads_match_python_and_preserve_inputs():
    runner, _ = await python_overhead.prepare()
    cases = [
        (name, *case) for name, case in python_overhead.make_cases().items()
    ] + [
        ("loop-sum", python_overhead.loop_sum, [0], 0),
        ("loop-sum", python_overhead.loop_sum, [7], 21),
        ("function-calls", python_overhead.function_calls, [0], 0),
        ("function-calls", python_overhead.function_calls, [7], 7),
        ("traverse-objects", python_overhead.traverse_objects, [[]], [0, 0]),
        (
            "traverse-objects",
            python_overhead.traverse_objects,
            [[{"visible": False}, {"visible": True, "stats": {"weight": 9}}]],
            [1, 9],
        ),
    ]
    for name, function, args, expected in cases:
        original = copy.deepcopy(args)
        for _ in range(2):
            assert function(*args) == expected, name
            result = await runner.evaluator.call(
                runner.root_scope[name], args, runner.root_scope
            )
            assert result == expected, name
            assert args == original, name
        assert not runner.evaluator.side_effects
        assert not runner.evaluator.call_stack


@pytest.mark.asyncio
async def test_benchmark_report_preloads_once_and_records_samples(monkeypatch):
    loads = []
    original = ScriptRunner.handle_script

    async def record_load(runner, source):
        loads.append(source)
        return await original(runner, source)

    monkeypatch.delenv("SLIP_DEBUG", raising=False)
    monkeypatch.setattr(ScriptRunner, "handle_script", record_load)
    monkeypatch.setattr(python_overhead, "BATCH_NS", 1)
    monkeypatch.setattr(python_overhead, "WARMUP_CALLS", 1)
    report = await python_overhead.benchmark(samples=2)

    assert len(loads) == 1
    assert report["preparation_ns"] > 0
    assert {case["name"] for case in report["cases"]} == {
        "loop-sum", "function-calls", "traverse-objects",
    }
    for case in report["cases"]:
        for language in ("python", "slip"):
            timings = case[language]
            assert timings["calls_per_batch"] >= 1
            assert len(timings["samples_ns_per_call"]) == 2
            assert all(value > 0 for value in timings["samples_ns_per_call"])
        assert case["slip_to_python_ratio"] > 0
