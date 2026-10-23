# SLIP versus direct Python

Run from the repository root:

```bash
uv run python3 benchmarks/python_overhead.py --samples 7 \
  --output benchmarks/python_overhead_kernel_results.json
```

The paired implementations are in `python_overhead.slip` and
`python_overhead.py`. They perform the same algorithm with explicit loops:

- `loop-sum`: sum 0 through 999 using an explicit counter and `while` loop.
- `function-calls`: 1,000 calls to an increment function inside the same loop.
- `traverse-objects`: visit 40 plain dictionaries, test `visible`, and accumulate
  the count and nested `stats.weight` of the 26 visible objects.

The result checks are respectively `499500`, `1000`, and `[26, 533]`. The runner
checks Python and SLIP results before timing and after every timed batch. It also
checks that inputs are unchanged and no effects/call frames accumulate. Focused
tests exercise empty and smaller inputs and a hidden object without `stats`.

## Timing boundaries

SLIP source is parsed and its functions defined once through `ScriptRunner`.
Warm calls use `await evaluator.call(function, args, root_scope)` in one event
loop; Python uses ordinary `function(*args)` calls. Both receive the same Python
input values. Workload state is initialized inside each function call.

The normal interpreter semantics remain enabled, including scope handling,
dispatch, mutation checks, and periodic cooperative yields in `while`. The Python
twins reproduce the algorithms, not the interpreter's internal safety machinery.
No runtime fast path is substituted for the SLIP implementation.

Parsing, fixture construction, correctness checks, output serialization, and
profiling are outside warm timings. The separate preparation number includes
runner construction and initial core/workload loading, after Python imports; it
is not a whole-process cold-start measurement. This benchmark does not exercise
JSON-command validation, per-call `asyncio.run`, host adapters, databases, or the
application's real look/visibility code.

Each implementation gets three warmup calls and independently calibrated batches
targeting at least 100 ms. Seven samples alternate Python/SLIP order. The reported
median is a **batch-average time per complete workload call**, not tail latency
or time per individual addition/function call/object. Garbage collection stays
enabled. JSON includes batch sizes, every sample, ranges, environment, and source
hashes. Ratios divide the SLIP median by the Python median; they are not a
universal language-overhead constant.

## Original measurement

`python_overhead_results.json` records CPython 3.12.11, Koine 0.11.0, and Linux
WSL2 x86-64. Runner preparation took **353.9 ms**, excluding imports.

| Workload | Direct Python | SLIP | SLIP / Python |
| --- | ---: | ---: | ---: |
| 1,000-iteration sum loop | 45.39 µs | 153.42 ms | 3,380× |
| 1,000 increment-function calls with loop | 74.02 µs | 216.39 ms | 2,923× |
| 40-object dictionary traversal | 1.91 µs | 5.69 ms | 2,975× |

The measured interpreter overhead is substantial on these small, Python-friendly
workloads even after excluding parsing and runner setup. The object traversal
cost is about 5.7 ms in absolute terms; the large ratio also reflects how cheap
the equivalent direct Python code is.

A separate diagnostic `cProfile` run, excluded from those timings, recorded:

| Workload | `PathResolver.get` calls | `isinstance` calls |
| --- | ---: | ---: |
| Sum loop | 11,006 | 357,240 |
| Function-call loop | 12,006 | 405,240 |
| Object traversal | 306 | 11,860 |

For the profiled sum loop, `PathResolver.get` accounted for about 38% cumulative
time. For the function-call loop, generic method selection (`_pick_best`)
accounted for about 5.5% cumulative time. Cumulative times overlap, and profiling
itself slows execution. This points to expression/name/operator resolution and
repeated type checks as useful next measurement targets, rather than assuming
multidispatch alone explains the overhead. No runtime optimization was added as
part of this measurement.

## Binding-aware execution reuse

`python_overhead_binding_results.json` retains a separate seven-sample run after
adding per-name binding versions, scope-local binding/operator lookup reuse,
direct ordinary-name reads/writes, and reuse of existing operator paths. The
workload sources and timing protocol are unchanged; the original report remains
available. Preparation took **241.0 ms**, excluding imports.

| Workload | Original SLIP | Updated SLIP | Updated Python | Updated ratio |
| --- | ---: | ---: | ---: | ---: |
| 1,000-iteration sum loop | 153.42 ms | 90.86 ms | 37.57 µs | 2,419× |
| 1,000 increment-function calls with loop | 216.39 ms | 133.75 ms | 60.07 µs | 2,227× |
| 40-object dictionary traversal | 5.69 ms | 3.78 ms | 1.55 µs | 2,436× |

These are separate measurements: direct Python also ran faster in the second
run. Both absolute times and paired ratios improve, but the table is not a
controlled same-run estimate of the speedup attributable solely to the change.
The remaining interpreter overhead is still substantial.

The separate post-change profile records the work actually removed:

| Workload | General path reads | HTTP/file classification | Segment-key evaluation | New GetPath objects | Binding resolutions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sum loop | 0 | 0 / 0 | 0 | 0 | 5 |
| Function-call loop | 0 | 0 / 0 | 0 | 0 | 2,006 |
| Object traversal | 106 | 0 / 0 | 238 | 0 | 4 |

Ordinary names still read current values; relevant rebinding, deletion, shadowing,
parent changes, and syntax edits invalidate reuse. New function invocations get
their own lookup context, accounting for the function workload's new resolutions.
Collection paths continue to use general traversal. `isinstance` counts decrease
from 357,240 to 211,211 for the sum loop, 405,240 to 270,213 for function calls,
and 11,860 to 9,320 for object traversal. Expression interpretation, assignment
handling, and runtime dispatch still contribute work.

To reproduce the separate profile:

```bash
uv run python3 - <<'PY'
import asyncio
import cProfile
import pstats
from benchmarks.python_overhead import make_cases, prepare

async def main():
    runner, _ = await prepare()
    for name, (_, args, expected) in make_cases().items():
        function = runner.root_scope[name]
        await runner.evaluator.call(function, args, runner.root_scope)
        profile = cProfile.Profile()
        profile.enable()
        result = await runner.evaluator.call(function, args, runner.root_scope)
        profile.disable()
        assert result == expected
        print(name)
        pstats.Stats(profile).strip_dirs().sort_stats('tottime').print_stats(15)

asyncio.run(main())
PY
```

## Python execution-kernel simplification

The kernel now keeps known blocks, source terms, produced values, and callable
invocation separate. One async cursor/accumulator loop reduces the existing flat
AST without rebuilding source around intermediate results. Ordinary binding reads
and native calls return values directly; explicitly deferred interpreter work is
distinguished from awaitables stored as data. Generic dispatch enters its selected
method without preparing the invocation again. Source-call frames, mutation
ownership, dynamic rebinding, editable code, and cooperative loop yields remain
enabled. Early returns now stop a remaining reduction or source argument list.

`python_overhead_kernel_before.json` preserves the fresh seven-sample pre-kernel
baseline. `python_overhead_kernel_results.json` records the seven-sample result on
the unchanged workload/harness sources, plus current runtime source hashes and a
separate warm-call profile. The original and binding reports remain available.
The runtime hashes identify that measured kernel checkpoint, before the v0.2.1
grammar-packaging fix; these timings were not rerun for the release.

| Workload | Pre-kernel SLIP | Current SLIP | Speedup | Current Python | Current ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1,000-iteration sum loop | 85.09 ms | 41.14 ms | 2.07× | 37.45 µs | 1,099× |
| 1,000 increment-function calls with loop | 134.72 ms | 65.86 ms | 2.05× | 61.46 µs | 1,072× |
| 40-object dictionary traversal | 3.65 ms | 2.98 ms | 1.22× | 1.59 µs | 1,874× |

These remain separate measurements, with raw samples/ranges retained. Preparation
took **271.2 ms**, compared with **242.5 ms** in the fresh baseline; this increment
does not establish a startup improvement. Warm timings exclude profiling.

The separate current profile records:

| Workload | `isinstance` calls | Plain-name classifications | General path reads | Segment-key evaluations | New GetPath objects |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sum loop | 67,082 | 20,012 | 0 | 0 | 0 |
| Function-call loop | 99,082 | 21,012 | 0 | 0 | 0 |
| Object traversal | 5,967 | 653 | 106 | 238 | 0 |

The sum loop's type checks decreased from the binding checkpoint's 211,211 to
67,082. All three warm profiles perform zero HTTP/file classifications and zero
new binding resolutions; direct local/parent reads still observe current values.
Ordinary read calls remain (8,005 in the sum loop), and repeated name recognition,
assignment, invocation, and general collection-path work still cost time.

Verification: **1,367 pytest tests passed**; focused source correctness lint and
full lint on the new regression modules passed. Independent architecture and
behavior reviews found excessive continuation plumbing and missing return
propagation. The plumbing was removed, six return regressions were added, and
the scoped rechecks found no remaining blocker. Saved-report checks recomputed
statistics and verified workload/runtime hashes, outputs, and input immutability.

This is a measured interpreter improvement, not a production latency guarantee.
The remaining 1,072–1,874× direct-Python ratios are substantial. The application's
actual command/visibility/database path and its latency budget remain unmeasured.

## Isolated resolved-reducer experiment

```bash
uv run python3 benchmarks/reducer_resolution.py --samples 7 \
  --output benchmarks/reducer_resolution_results.json
```

`reducer_resolution.py` tests the proposed callable/accessor execution model with
two small binary reducers. Resolved expressions contain actual Python function
references, `itemgetter` readers, supplied member-reader functions, and literals.
Symbolic expressions contain operator names, operand names, parsed path tuples,
and literals. Every symbolic occurrence performs its namespace lookup/path walk;
source strings are never reparsed. Both call the same ordinary Python arithmetic
functions and read operands exactly once, in order.

The chain computes `(a + b) * c - 1`. The sum loop performs 1,000 iterations and
uses reductions for its condition, accumulation and counter increment. Traversal
uses the same 40-dictionary fixture and visibility/weight algorithm as the full
runtime benchmark. Both reducers share the exact Python control-flow/assignment
drivers; the direct Python controls use ordinary equivalent code. Namespace state
is initialized identically inside each reducer workload call.

Seven-sample medians from `reducer_resolution_results.json`:

| Workload | Direct Python | Resolved | Symbolic | Resolved / Python | Symbolic / resolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Three-operation expression | 0.106 µs | 0.674 µs | 0.691 µs | 6.35× | 1.03× |
| 1,000-iteration sum loop | 40.64 µs | 1,129.17 µs | 1,101.88 µs | 27.79× | 0.98× |
| 40-object dictionary traversal | 1.667 µs | 29.27 µs | 33.38 µs | 17.56× | 1.14× |

The expression and loop are effectively tied between the two reducers at this
measurement's resolution/variation. Traversal benefits from prepared direct
member accessors: about 1.14× throughput, or 12% less time. The resolved model is
6–28× direct Python here, and even the small symbolic reducer is only 7–27×.
Simple repeated dictionary resolution therefore does not itself reproduce the
full runtime's thousandfold overhead. Prepared accessors still perform dictionary
reads and add callable invocations; capturing operators alone does not imply a
large speedup. This experiment does not attribute the full runtime's remaining
cost between necessary semantics and avoidable implementation work.

Expression/accessor construction was measured once, separately: **2.34 µs** for
resolved and **1.77 µs** for symbolic. These are small one-off observations, not
stable compilation-time estimates. Imports, Python function definitions, the
shared primitive registry and fixtures are excluded. Warm timing has three
warmups, calibrated batches targeting 100 ms, seven samples with rotating order,
GC enabled, and correctness/immutability checks outside every batch. The JSON
retains all samples, batch sizes, ranges, ratios, environment and source hash.

Nested readers are supplied Python functions for the fixed benchmark paths.
Automatic accessor construction, full SLIP dispatch, ownership, tasks, source
diagnostics and editable code are not implemented by these prototypes. The shared
Python driver also means this does not measure interpreted control-flow execution.
Captured operators intentionally keep their callable after target-name reassignment;
the production runtime's current alias behavior has not been changed.

Verification: **9 focused tests passed**, covering both benchmark modules, live
operand changes, object replacement, separate namespaces, captured versus symbolic
operators, exactly-once read order, hidden objects, output parity and immutability.
The new code/tests pass flake8. A separate saved-artifact check verified the source
hash, metadata, all seven samples, medians/ranges/ratios and freshly executed results.
