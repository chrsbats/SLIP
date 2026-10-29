# SLIP v0.3.0 — synchronous Python runtime

## Included

- One synchronous, run-to-completion evaluator over prepared callable references,
  live getters, native Scopes and editable symbolic Code. The old interpreter and
  its unused pystache dependency are removed.
- The public `slip.ScriptRunner` and CLI use this runtime. Use ordinary `with`,
  synchronous `handle_script`, `slip file.slip` or `python3 -m slip file.slip`.
- Explicit Runner-owned external I/O jobs return pollable native Futures. The
  default keeps one worker; `background_io=False` opts out while retaining
  foreground HTTP. Injected resources remain caller-owned.
- Native host views, prototypes/dispatch, public JSON commands and prepared
  hydration, file/HTTP resources, portable symbolic Code caches, schemas,
  refs/cells, examples/reflection and source diagnostics.
- Tests consolidated under normal `tests/` discovery. Original coupled test
  sources remain in `archive/reference-tests/`; `tests/legacy/INVENTORY.md`
  records public equivalents, approved adaptations, private mechanics and deferrals.
- Koine `>=0.11.2`, preserving native float representation and source round trips.

## Intentional changes and current scope

- Known callable bindings capture when a definition executes; data/member reads,
  parameters and nearer local binders remain live. Generic captures observe new
  methods on that same object. Explicit fresh Code execution observes source edits.
- A function at an expression head or pipe position invokes; missing arguments
  error. Function arguments remain values at every arity. Group nested calls:
  `f time` passes a function; `f (time)` passes its result. Completed grouped
  callable results stay data; `call` explicitly invokes them.
- `call` only invokes, including zero arguments when omitted. Use `to-path` for
  path construction and `core-function` for explicit callable aliases.
- Deletion removes only addressed entries; empty ancestors remain.
- Both quote styles decode escapes; single quotes do not interpolate. Multiline
  framing normalizes before decoding escapes.
- Local SLIP task/sleep suspension, resolver/this transaction authority, remote
  RPC and automatic example-driven signature/method synthesis remain deferred.
  Examples retain metadata and execute on request using explicit signatures.

## Release verification

Final source-matched suite, installed artifact/consumer checks and frozen warm
measurements are recorded on completion. Startup is excluded from performance
acceptance. Historical async-to-sync reports do not establish frozen-release speed.

## Distribution

Use this repository's GitHub release or Git dependency. Public PyPI's `slip` is an
unrelated project. The protected v0.2.1 artifacts and Domain pin remain separate.

---

# SLIP v0.2.1 — frozen Python runtime

This release preserves the tested Python runtime as a rollback baseline before
further callable-reference/accessor work.

## Included

- Binding-aware scope and operator lookup reuse, with live rebinding, shadowing,
  editable syntax, host reads, and independent call scopes preserved.
- A simpler flat expression reducer and invocation path, including early-return
  propagation and explicit separation of deferred work from awaitable data.
- Regression tests and the recorded Python overhead/reducer experiments.
- Installable wheels and source distributions containing `root.slip` and all
  three grammar files. Runner parsing, bare-evaluator bootstrapping, interpolation,
  imports, and compiled-code cache fingerprints use the packaged grammars.
- Koine `>=0.11.1`, including the upstream native-parser fixes.

The benchmark reports identify their measured source checkpoints. They are
historical measurements, not new release-performance or application-latency claims.

## Verification

Release checks use published Koine **0.11.1**, including its Linux native wheel.

- Full SLIP suite: **1,378 passed** on Python 3.12.
- Installed-wheel resource/runtime checks outside the checkout: **4 passed** on
  Python 3.13, covering runner parsing, bare evaluation, interpolation, public
  module invocation, and persistent compiled-code cache reuse.
- Focused lint and whitespace checks passed.
- Current `langscape-domain` working-tree compatibility: **150 passed** both with
  the editable baseline and with the installed wheel. Checks cover commands,
  schemas, prepared-runner isolation, live visibility, and Etcher integration.

## Distribution

Use this repository's GitHub release or a Git dependency on its release commit.
The `slip` project on public PyPI is a different project. The Domain dependency
uses the full release commit SHA so future SLIP checkout changes cannot affect it.
