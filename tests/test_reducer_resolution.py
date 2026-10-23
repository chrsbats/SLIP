import copy

import pytest

from benchmarks import reducer_resolution as prototype


def test_workloads_match_python_and_preserve_inputs():
    operators, programs, _ = prototype.prepare()
    for implementations, args, expected in prototype.make_cases(
        operators, programs,
    ).values():
        original = copy.deepcopy(args)
        for function in implementations.values():
            assert function(*args) == expected
            assert function(*args) == expected
            assert args == original

    for name, reducer in (
        ("resolved", prototype.reduce_resolved),
        ("symbolic", prototype.reduce_symbolic),
    ):
        expressions = programs[name]
        for limit, expected in ((0, 0), (7, 21)):
            assert prototype.run_loop(
                reducer, expressions, operators, limit,
            ) == expected
        assert prototype.run_traversal(
            reducer, expressions, operators, [],
        ) == [0, 0]


def test_accessors_observe_current_namespace_and_replacement_objects():
    operators, programs, _ = prototype.prepare()
    for name, reducer in (
        ("resolved", prototype.reduce_resolved),
        ("symbolic", prototype.reduce_symbolic),
    ):
        namespace = dict(operators, total=1, i=2)
        expression = programs[name]["sum"]
        assert reducer(expression, namespace) == 3
        namespace.update(total=10, i=20)
        assert reducer(expression, namespace) == 30
        assert reducer(expression, dict(operators, total=7, i=8)) == 15

        expression = programs[name]["weight"]
        namespace["obj"] = {"stats": {"weight": 4}}
        assert reducer(expression, namespace) == 14
        namespace["obj"]["stats"]["weight"] = 6
        assert reducer(expression, namespace) == 16
        namespace["obj"] = {"stats": {"weight": 9}}
        assert reducer(expression, namespace) == 19


def test_resolved_operator_captures_callable_while_symbolic_follows_name():
    operators, programs, _ = prototype.prepare()
    namespace = dict(operators, a=10, b=5, c=2)
    namespace["+"] = prototype.subtract

    assert programs["resolved"]["chain"][1] is prototype.add
    assert prototype.reduce_resolved(
        programs["resolved"]["chain"], namespace,
    ) == 29
    assert prototype.reduce_symbolic(
        programs["symbolic"]["chain"], namespace,
    ) == 9


@pytest.mark.parametrize("mode", ["resolved", "symbolic"])
def test_operands_are_read_once_in_left_to_right_order(mode):
    operators, programs, _ = prototype.prepare()
    reads = []

    class Namespace(dict):
        def __getitem__(self, key):
            if key in ("a", "b", "c"):
                reads.append(key)
            return super().__getitem__(key)

    namespace = Namespace(operators, a=10, b=5, c=2)
    reducer = getattr(prototype, f"reduce_{mode}")
    assert reducer(programs[mode]["chain"], namespace) == 29
    assert reads == ["a", "b", "c"]


def test_hidden_object_does_not_read_missing_stats():
    operators, programs, _ = prototype.prepare()
    objects = [
        {"visible": False}, {"visible": True, "stats": {"weight": 9}},
    ]
    for name, reducer in (
        ("resolved", prototype.reduce_resolved),
        ("symbolic", prototype.reduce_symbolic),
    ):
        assert prototype.run_traversal(
            reducer, programs[name], operators, objects,
        ) == [1, 9]


def test_report_records_all_implementations_and_samples(monkeypatch):
    monkeypatch.setattr(prototype, "BATCH_NS", 1)
    monkeypatch.setattr(prototype, "WARMUP_CALLS", 1)
    report = prototype.benchmark(samples=2)

    assert report["preparation_ns"]["resolved"] > 0
    assert report["preparation_ns"]["symbolic"] > 0
    assert len(report["source_sha256"]) == 64
    assert len(report["cases"]) == 3
    for case in report["cases"]:
        assert set(case["timings"]) == {"python", "resolved", "symbolic"}
        for timing in case["timings"].values():
            assert timing["calls_per_batch"] >= 1
            assert len(timing["samples_ns_per_call"]) == 2
            assert min(timing["samples_ns_per_call"]) > 0
