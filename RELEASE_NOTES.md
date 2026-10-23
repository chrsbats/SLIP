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
