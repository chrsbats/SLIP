# Legacy behavior migration

These tests call the shipped `slip.ScriptRunner`, using synchronous calls
and context-managed cleanup. The package and CLI select the rewritten runtime.
No test-time import replacement, async adapter or private-runtime facade is used.

The current batches port behavior assertions from:

- `tests/test_chapter_001.py`: expression order, calls, lazy Code, assignment and
  invalid expression forms.
- `tests/test_chapter_002.py`: values, path modes/equality, queries, interpolation
  and non-interpolated strings. Multi-part tests are split into named cases.
- `tests/test_chapter_003.py`: assignment, overloads, scopes, destructuring, updates,
  deletion and grouped path arguments. Both originally duplicated assignment cases
  are retained as separate cases.
- Three deletion assertions from `tests/test_interpreter_coverage.py`,
  `tests/test_interpreter_extra_coverage.py` and `tests/test_slip_interpreter.py`.
- `tests/test_chapter_004.py` through `test_chapter_007.py`, including
  `test_chapter_006_control_flow.py`: pipes, inheritance, dispatch, guards, controls,
  caller-local bindings, returns and effects (`test_functions_and_controls.py`).
- Chapters 008–010: metadata, guards, schemas/normalization, sandbox and targeted
  execution, interpolation, Code construction and file-loaded inject/splice.
- `test_test_framework.py`, `test_sig_reflection.py` and non-authority
  `test_where_sugar.py` cases: examples, summaries, detached canonical signatures,
  host-ID hydration and guards. The resolver transaction case remains deferred.

Scripts have been compacted where only whitespace/comments change; result and
error assertions remain substantive. Native values are compared directly.

The function/control batch uses the documented `{}` signature in the old test that
used `fn []`, retaining its last-defined-method assertion. It checks the inheritance
error's once-only rule without requiring legacy prose. Fixed-arity prefix evaluation
rejects a trailing value where a piped function is required; the corresponding
`call f #[1, 2]` case retains the dispatch-specific `No matching method` assertion.
These are separate executable checks, not a changed argument-consumption engine.

The advanced batch groups the right-hand comparison in `and (n < 20)`, following
the documented flat evaluation rule. The reflection port constructs the canonical
ordered `Parameter` list instead of assigning a legacy derived `param_order` view.
The old positional-example fixture declared `a`/`b` but referred to missing `x`/`y`;
the port explicitly binds the referenced names to the same 10/32 values. Missing
sample/expected names have separate structured-failure and continuation regressions.

The approved signature-count correction replaces ambiguous named-function helper
pipes with ordinary calls: `example f description`, `public module.function` and
`command function`. Piping a constructor/call result remains covered, including
zero-argument command projection. Result, effect, identity, guard and float-sample
assertions are retained; no following function's arity determines call boundaries.

The user's subsequent explicit-execution amendment supersedes zero-argument
argument auto-calls, bare-callable no-input fallbacks and ancestor pruning. Scope
deletion cases now require empty ancestors to remain, independently of spelling;
the old pruning-option case uses ordinary metadata instead. Function arguments
remain values, nested calls such as `(current-scope)` are explicit, and ordinary
function aliases use `core-function`. Results/effects/identity assertions remain
except for the explicitly replaced pruning expectations. The independent core
test for zero-arity argument execution now supplies an explicit group.

Chapter 010's path construction uses `to-path`; `call` always invokes, including
zero-argument targets when args are omitted. Lookup errors cannot turn into path
data. Dynamic set/delete calls still pass evaluated argument lists. The assertion
uses the documented
infix `and` instead of a missing `logical-and` alias. Runner initialization/cleanup
uses the synchronous public entrypoints rather than `_initialize`.

## Approved example scope

The user clarified that examples were intended to provide implicit signatures and
a future optimized typed/C path, but current Python simplicity/speed take priority.
Automatic example-driven method synthesis is therefore deferred. The ordinary
chapter 008 int/float calls remain covered; its typed-clone/guard case is represented
by a declared typed signature, not counted as implemented type inference. Additional
tests verify retained float samples, unchanged callable/signature/method identity,
and inline/late attachment with explicit example execution. The future optimization
direction is retained in SPEC.

Run this batch with:

```bash
uv run pytest tests/legacy -q --tb=short
```

## Approved string differences

The user prioritized reasonable expectations over legacy compatibility and approved
the rules in SPEC “Approved string expectations”. The port of legacy
`test_raw_string_is_verbatim_no_interpolation_or_escapes` now requires a decoded
newline while continuing to require no interpolation. Multiline framing is trimmed
before escape decoding; the earlier independent newline-retention expectation is
updated too. Focused tests preserve explicit newlines, content whitespace, both
string types and source/file-cache round trips.

[INVENTORY.md](INVENTORY.md) accounts for all original modules by current behavior
equivalents, approved adaptations, private mechanics and named deferrals. Original
engine-coupled sources remain in `archive/reference-tests/*.py.txt`; current tests
use normal discovery. Artifacts and frozen warm performance are separate gates.
