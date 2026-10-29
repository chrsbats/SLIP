# Warm Python SLIP measurements

Run from the repository root:

```bash
uv run python3 benchmarks/python_overhead.py --samples 7 \
  --output /tmp/opencode/slip-overhead.json
```

`python_overhead.slip` and the direct Python functions in `python_overhead.py`
retain the same algorithms and inputs:

| Workload | Work per invocation | Expected result |
| --- | --- | --- |
| loop-sum | Explicit while loop over 0–999 | 499500 |
| function-calls | 1,000 increment calls inside a while loop | 1000 |
| traverse-objects | Visit 40 dictionaries, accumulate 26 visible items | [26, 533] |

## Timing boundary

The Runner parses and defines functions once. Current warm calls use native
`invoke(function, args, runner.scope)`; frozen v0.2.1 uses its ordinary async
evaluator call in one event loop. The harness selects the delivered API without
changing the workload. All ordinary runtime semantics stay enabled; there is no
surrogate reducer or special workload fast path.

Startup, loading, fixture creation, validation, profiling, serialization and
cleanup are outside warm timing. Preparation is reported separately and is
excluded from performance acceptance. Each implementation has three warmups,
independently calibrated batches targeting 100 ms, and seven samples alternating
Python/SLIP order. GC remains enabled. Times are batch averages per complete
workload invocation, not tail latency or per-addition latency.

The report retains all samples/ranges, Python/Koine/package versions, runtime and
workload/harness hashes, outputs, input immutability, empty effects and a separate
one-call profile. Correctness is checked after every batch. Tests exercise empty
and smaller inputs, replacement objects and hidden items without stats.

## Frozen v0.2.1 comparison

The release-completion comparison uses a fresh installation of the protected
v0.2.1 wheel (commit `7913c071d7d156d5a3a4bceeb8ebc8c61a59eca7`) and the
installed 0.3 wheel, with identical Python/Koine and this same harness/workload.
Saved reports and measured medians are added after verification. These
microbenchmarks do not establish application command/database latency.

## Historical evidence

[Earlier measurements](../archive/benchmarks/HISTORY.md) describe prior production
and isolated-reducer checkpoints. Old JSON and `independent/` reports retain their
original source identifiers; they are not current release acceptance.
`reducer_resolution.py` remains an isolated Python experiment with its own tests,
not another SLIP engine or a production performance claim.
