# Original behavior disposition for 0.3

The original collection contained **1,474 cases in 80 modules**. This is a
historical inventory, not the current pass count or a one-to-one case migration.
Multi-assertion cases were split and overlapping assertions consolidated. Current
tests use normal discovery under `tests/`, with no legacy exclusion or adapter.

Original engine-coupled sources remain in
`archive/reference-tests/<module>.py.txt`. Directly adapted public and unchanged
parser modules remain executable under `tests/`. The table accounts for all 80
original modules by contract family; current paths are relative to `tests/`.
Mixed modules are assessed by behavior, never classified wholesale as private.

| Original modules (without `test_`/`.py`) | Executable equivalents | Disposition |
| --- | --- | --- |
| chapter_001, chapter_002, chapter_003 | legacy/test_chapter_001.py, legacy/test_chapter_002.py, legacy/test_chapter_003.py; test_strings.py, test_explicit_execution.py | Public expressions, values, paths, updates, scopes and deletion retained; approved changes below. |
| chapter_004, chapter_005, chapter_006, chapter_006_control_flow, chapter_007 | legacy/test_functions_and_controls.py; test_scope_functions.py, test_documented_library.py | Pipes, prototypes, ordered dispatch, caller-local controls, returns and effects retained. |
| chapter_008, chapter_009, chapter_010 | legacy/test_advanced.py, legacy/test_schemas.py, legacy/test_metaprogramming.py; test_schema_refs_examples.py | Metadata, signatures, schemas/defaults/validation, sandbox/target execution and inject/splice retained. Example-driven synthesis deferred. |
| chapter_011 | test_sync_execution.py, test_documented_library.py; legacy/test_host_effects.py | Ordinary loops retained; local tasks/sleep/suspension and task lifecycle deferred. |
| chapter_012, host_binding, etcher_integration | test_embedding.py, test_host_views.py, test_as_slip.py, test_membership.py; legacy/test_host_effects.py, legacy/test_persistent_data.py | Native methods, live/replaced containers, prototypes, explicit snapshots and real Etcher persistence retained. Async loaders rejected; task/authority portions deferred. |
| chapter_013, chapter_014, chapter_015, outcome, outcome_contract, status_helper, with_log, error_tracing | test_embedding.py, test_source_diagnostics.py, test_sync_execution.py; legacy/test_host_effects.py, legacy/test_resources_results.py, legacy/test_boundary_contracts.py, legacy/test_execution_composition.py | Native results, ordered effects, structured errors, source traces, return propagation and opaque identity retained. Private Outcome/view/display classes superseded. |
| core, root_slip, runtime_primitives, dispatch_precedence, membership, as_slip | Same-named executable modules; test_public_api.py, test_host_views.py | Direct synchronous ports, including native membership without reads, rehydration and exact/variadic precedence. |
| callable_capture, binding_resolution, prepared_execution | test_pop_core.py, test_bind_once.py, test_simple_model.py, test_code_cache.py, test_public_api.py; legacy/test_focused_contracts.py, legacy/test_release_contracts.py, legacy/test_capture_and_evaluation.py | Capture, live operands, dynamic binders, source order, nested paths/templates/guards, fresh Code and runner-local caches retained. Private cache/adaptor records and active-stack refresh superseded. |
| evaluation_once, reduction_kernel | test_argument_consumption.py, test_explicit_execution.py, test_sync_execution.py; legacy/test_execution_composition.py, legacy/test_capture_and_evaluation.py, legacy/test_boundary_contracts.py | Computed-key effects, short-circuit cell/file/HTTP reads, callable-selection order, recursive traversal/counts, returns and identity retained. Implicit awaiting/private ReturnSignal superseded. |
| call_modes, to_path | test_explicit_execution.py, test_documented_metaprogramming.py; legacy/test_metaprogramming.py, legacy/test_focused_contracts.py | Invocation-only call, explicit grouping, setter arity, dynamic set/delete and path conversion retained under approved call rules. |
| contract_dispatch, filter_predicates, vectorized_set_paths | test_dispatch_precedence.py, test_pop_core.py, test_remaining_values.py; legacy/test_functions_and_controls.py, legacy/test_focused_contracts.py, legacy/test_execution_composition.py, legacy/test_capture_and_evaluation.py | Dispatch tiers/order/guards, grouped filters, original mutation targets and captured selectors retained. |
| slip, slip_datatypes, slip_interpreter, interpreter_coverage, interpreter_extra_coverage, interpreter_unit | test_pop_core.py, test_simple_model.py, test_remaining_values.py, test_scope_functions.py; legacy/test_boundary_contracts.py, legacy/test_focused_contracts.py, legacy/test_release_contracts.py, legacy/test_persistent_data.py | Public Scope lookup/deletion, paths, destructuring, foreach, get-body identity and errors retained. Old AST layouts, View placeholders, registries and private evaluator mock calls superseded. |
| contract_resolver_transactions, contract_this_reserved, ref, cell, where_sugar | test_schema_refs_examples.py, test_remaining_values.py, test_sync_execution.py; legacy/test_host_effects.py, legacy/test_examples_reflection.py | Ordinary refs/cells, identity/read-only paths and nonauthority where retained. Resolver ownership/transaction/receiver cases deferred, not passed. |
| public_command_api, sig_reflection, test_framework | test_public_api.py, test_scope_functions.py, test_schema_refs_examples.py; legacy/test_examples_reflection.py, legacy/test_release_contracts.py | JSON/schema execution, hydration, overloads/rest/guards, detached signatures, get-body, examples and cached distinct host stores retained. Automatic example synthesis deferred. |
| file_scheme_io, fs_scheme_paths, import, pathresolver_helpers | test_file_resources.py, test_code_cache.py; legacy/test_resources_results.py | Files, home/parent/absolute/relative locators, module shadows/cycles/retry/isolation, source directories and portable caches retained. Private suffix reconstruction superseded by structural paths. |
| http_path_helpers, http_path_queries, http_response_modes, http_scheme_paths, http_utils, runtime_http_and_import | test_http_resources.py, test_runtime_http_and_import.py, test_io_jobs.py; legacy/test_resources_results.py, legacy/test_release_contracts.py | Verbs, queries, envelopes, wire codecs, retries, evaluation once, ordered multi-target writes, imports and ownership retained. Private transport tuple/helper shapes superseded. |
| serialize, serialize_helpers, additional_coverage | test_value_operations.py, test_http_resources.py, test_file_resources.py; legacy/test_resources_results.py | Language codecs, HTML/XML sniffing, YAML alias/charset, XML lists, default text headers and locator behavior retained through public boundaries. |
| bytestream_literals, printer_calls, slip_printer, slip_transformer | test_value_operations.py, test_source_printing.py, test_strings.py, test_remaining_values.py, test_code_cache.py; legacy/test_chapter_002.py, legacy/test_examples_reflection.py | Streams, signatures, paths, strings and valid source/value/cache round trips retained. Private transformed-class/segment repr/hash layouts and exact printer whitespace superseded. |
| parser, parser_paths, parser_placeholder, parser_sig, root_comment_and_sig_integration | Same-named unchanged executable modules | Original Koine syntax assertions retained: question marks, escapes, comments, separators, paths and mixed-signature rejection. |
| documentation_examples | test_documentation_examples.py | All fences parse/transform; every active result marker executes; standalone Python and named file/host/command workflows execute. Resolver illustrations labeled future behavior. |
| package_resources, repl | Same-named executable modules | Public resources/class identity, cache, CLI rendering/errors/directories and cleanup retained; clean wheel/sdist checks are an additional release gate. |
| python_overhead_benchmark | test_python_overhead_benchmark.py | Unchanged workload values, inputs, warm boundary and sample records retained; actual frozen comparison is separate. |
| reducer_resolution | test_reducer_resolution.py | Retained isolated Python experiment, not a runtime dependency or evidence of production speed. |

## Explicitly approved adaptations

- Single quotes decode escapes without interpolation; multiline framing normalizes
  before escape decoding. No legacy verbatim-backslash quirk.
- Arguments retain functions at every arity; nested calls are grouped. Aliases use
  `core-function`. Heads/pipes invoke, missing arguments error. `call` invokes;
  `to-path` constructs paths. No cross-function arity guessing.
- Deletion removes exactly addressed entries, retaining empty ancestors.
- Known captures survive definition-environment rebinding; local binders/operands
  stay live. No active-stack refresh: new definitions and explicit fresh execution
  observe source edits.
- Ordered Parameter records replace private Sig storage; native values replace
  wrapper display strings. Example fixture names were corrected while retaining
  missing-name failures. Attached and in-signature guards retain capture.
- One synchronous evaluator replaces implicit awaits and async Runner setup. Opaque
  results stay data; explicit external async jobs return native Futures. Local
  tasks/sleep/continuations, resolver/this authority, example inference and remote
  RPC remain named deferrals.

## Review evidence

Source review `ses_e87de968effebqGpDfywatDw7s` identified B1–B4/G1 and C1–C4
assertion gaps. Their equivalents are the release, capture, resource and bind-once
tests listed above. Architecture review `ses_e87ab3408ffePkkuz9KZemN3OK` closed
prepared when/cond, nested lexical scope and same-scope binder findings within the
existing model. Source review does not substitute for executed tests, installed
artifacts or measured performance; final evidence is recorded in release status.
