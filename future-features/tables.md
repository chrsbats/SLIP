# Plan: Table Datatype and Lazy Views for SLIP

Purpose
- Introduce a first-class, dataframe-like table type with lazy views to align with the language spec and deliver vectorized performance where possible.
- Keep existing list/scope semantics intact; tables are “core-adjacent,” not “everything is a table.”

Design Principles
- Preserve language ergonomics: paths, filters, and vectorized assignments should “just work.”
- Be backend-agnostic: start with a pure-Python fallback; allow pandas/polars later without changing surface semantics.
- Laziness first: filter and pluck operations should return lightweight views; only materialize when required (iteration, explicit conversion).

Terminology
- Table: a columnar collection of rows (row = dict/scope). Holds common fields as columns and a single extras column for dynamic keys.
- TableView: a lazy, filtered view over a base table (mask or row indices).
- ColumnView: a lazy view of a single table column (optionally projecting from extras).
- Extras column: a dict/JSON column (e.g., "__extra__") that stores non-schema keys per row.

Schema Story
- Reuse existing Schema objects (scopes). No new “static schema” type.
- At construction, compile schema into backend dtypes (cached). Optional/Default markers are honored by the existing validate function.
- Table.meta['schema'] keeps the original schema; Table may cache a compiled dtype map internally.

Runtime Datatypes (new)
- slip.slip_table.Table
  - Fields: backend (“python”, “pandas”, “polars”), df/rows, schema, extras_field="__extra__".
  - Protocol:
    - slip_pluck(name) -> ColumnView
    - slip_filter(filter_query, evaluator, scope) -> TableView
    - slip_apply_update(field, filter_query, update_terms, evaluator, scope) -> list|None
    - slip_apply_assign(field, filter_query, value_terms, evaluator, scope) -> list|None
    - slip_iter_rows() -> iterator over row dicts/scopes (materializes lazily if needed)
    - __len__(), optional __getitem__ for row i materialization.
- slip.slip_table.TableView
  - Wraps base table with a mask/indices. Exposes the same protocol, delegating to base with mask composition.
- slip.slip_table.ColumnView
  - Wraps a column (or a projection into extras). Provides len, iteration, and optional vector ops.

Interpreter Integration
- type-of / primitive typing
  - Recognize Table/TableView/ColumnView as `table`.
- Printer
  - Compact summaries, e.g., table<Character> rows=1_234 cols=[name,hp,mp,...].
  - Do not dump full rows by default.
- PathResolver
  - Pluck:
    - If container has slip_pluck, return ColumnView (lazy).
    - Else, current list pluck behavior (materialized Python list).
  - Filters (FilterQuery):
    - If container has slip_filter, return TableView (lazy), compiled where possible (vector mask).
    - Else, current list filtering (Python loops).
  - Vectorized writes (set-path Name + FilterQuery):
    - If base has slip_apply_update/slip_apply_assign, delegate (masked backend operation).
    - Else, current list-based logic.
- Control flow
  - foreach/map/filter/reduce accept Table/TableView; iteration yields rows (dicts/scopes). Laziness preserved until iteration.
- File/HTTP
  - No change initially. Table IO (csv/parquet) can be added later via slip_file and content-type/extension normalize.

Spec Semantics (unchanged at surface)
- Path read:
  - players.name on a Table returns a ColumnView (lazy). On a list, returns a Python list (eager) as today.
- Filter:
  - players[.hp < 50] returns a TableView (lazy) for Table, or a Python list for list.
- Vectorized write:
  - players.hp[< 50]: + 10
    - Table: masked vector add in backend.
    - List: per-item loop (as today).
- Materialization:
  - Iteration (foreach) and explicit conversion (table-to-list) materialize as needed.
  - Equality: tables compare by identity (like SlipDict), not deep row equality (documented).

Standard Library Surface (initial)
- table-from-list rows: `ordered`, sch: `scope` -> `table`
  - Validates rows, populates typed columns, packs remaining keys into extras.
- table-to-list tbl: `table` -> `ordered`
  - Produces a list of row dicts/scopes for interop with existing code.
- Optional: columns tbl -> list of column names; count tbl -> int.

Backend Strategy
- Phase 1: pure-Python fallback (rows + indices as masks).
  - Correctness + laziness without new dependencies.
- Phase 2: pluggable backends (polars recommended; pandas acceptable).
  - Compile simple predicates to masks: .field <op> literal/column; “and/or” chains; optional not.
  - Use backend assignment for masked updates/assign.

Predicate Compilation (for Table.filter)
- Supported first:
  - .field <op> literal: < <= > >= = !=
  - .field <op> .other_field
  - logical-and, logical-or at top level
- Fallback to per-row overlay for:
  - Nested Group/List expressions, function calls, non-deterministic ops, complex conjunction trees.
- Operator semantics and rebinding:
  - Comparators and logicals remain language-level operators bound in root.slip (not hard-coded primitives).
  - The predicate compiler only vectorizes when those operators resolve to the StdLib defaults (by identity or an intrinsic marker); if they are rebound or shadowed, it falls back to per-row evaluation to preserve semantics.
  - This keeps surface flexibility while enabling native backend masks/assignments for the common case.

Phased Rollout
- Phase 1 (lowest risk)
  - Implement Table, TableView, ColumnView with Python fallback.
  - Add view protocol hooks in PathResolver (pluck/filter/vector writes).
  - Update type-of and printer.
  - Add stdlib: table-from-list, table-to-list.
- Phase 2 (performance)
  - Backend integration (polars/pandas).
  - Predicate compiler for common cases.
  - Masked assignment for vectorized writes.
  - Optional: csv/parquet IO via slip_file (detect via extension or #(format: ...)).
- Phase 3 (ergonomics)
  - Aggregations (sum/avg/min/max) on ColumnView via stdlib helpers.
  - Join/merge primitives (optional).
  - Auto-promotion heuristics (opt-in): convert large list-of-scopes to Table under guard.

Testing Strategy
- Golden-path semantics:
  - Pluck/filter/update parity between list and table (values match when materialized).
- Laziness:
  - Ensure pluck and filter return views; no eager Python lists on Table.
- Vectorized writes:
  - players.hp[< 50]: + 10 updates only masked rows; retains unmapped columns/rows.
- Schema handling:
  - Defaults and optional fields applied; extras collected.
- Fallbacks:
  - Complex predicates correctly fall back to per-row evaluation.

Open Questions
- Do we want list pluck/filter to adopt a generic lazy “SeqView” in the future? (Not required for tables; can be separate.)
- Should ColumnView behave like a list for add/concat? (Likely not; keep explicit conversions.)
- Stable column name resolution precedence: column beats extras, extras fallback documented.

Risks and Mitigations
- Backend dependency bloat:
  - Start with pure-Python; add optional extras in extras_require (pip install slip[tables]).
- Semantic drift:
  - Preserve existing list behavior; introduce laziness only for Table.
- Predicate corner cases:
  - Compile only simple cases; fall back to per-row evaluator for the rest.

Migration Guidance
- Existing scripts continue to work.
- To opt in:
  - Construct a table via table-from-list (or future file IO).
  - Use the same path/filter/update syntax; results are now lazy views and vectorized updates.

Acceptance Criteria (for Phase 1)
- New “table” recognized by type-of and printer.
- players.name and players[.hp < 50] return lazy views on Table; eager lists on list.
- players.hp[< 50]: + 10 updates correctly on Table and list.
- table-from-list/table-to-list round-trip for basic rows + schema + extras.

Implementation Notes
- Keep the view protocol duck-typed; PathResolver checks for method presence rather than concrete classes.
- Cache compiled schema → dtype mapping in the Table for repeated operations.
- Avoid leaking backend objects to user space; expose only SLIP datatypes (Table/Views, lists/scopes when materialized).

Shared-Scope Persistence and Tensors (Summary)
- Model: A persisted shared-scope (via “etcher”) stores JSON-like SLIP values in SQLite (or redislite). On boot, the environment rehydrates that scope and execution continues with the same bindings. Tables fit naturally here (SQLite-backed; optional DuckDB for local analytics reads).
- Tensors outside the DB: For n‑D arrays (images/audio/embeddings), persist a small handle in the shared-scope and store the array bytes in a file/object store (not in SQLite). This avoids write amplification and keeps NumPy/Zarr/HDF5 performance.
- Handle shape (JSON, stored in SQLite): { "__type__": "tensor", "store": "npy|zarr|h5", "uri": "file://…", "key|dataset": "/group/arr"?, "shape": [..], "dtype": "float32", "chunks": [..]? }. Etcher rehydrates this as a lazy Tensor proxy that supports slicing/indexing; PathResolver needs no changes.
- Recommended stores:
  - NPY/NPZ: default for small/medium immutable arrays; simple and memmap‑friendly.
  - Zarr: large/chunked arrays, partial I/O, cloud/object storage friendliness.
  - HDF5: single‑file packaging and SWMR multi‑reader; heavier dependency, less cloud‑native than Zarr.
- Persistence policy for tensors:
  - Manual publish (default): compute in memory; save explicitly (or on assignment into shared-scope etcher detects tensors, writes the blob, then stores/updates the handle).
  - Optional “statement‑boundary flush”: mark dirty on mutation; flush once per top‑level statement to checkpoint tensors.
  - Atomic writes: write to a temp path, fsync, then rename; for Zarr, write to a temp directory and rename atomically. After the blob is durable, update the handle in the same SQLite txn.
  - GC: Etcher’s existing GC can track blobs by uri/hash/refcount and sweep orphans.
- Tables + tensors:
  - Tables remain vectorized via WHERE/UPDATE in SQLite; store tensor handles/URIs in columns for rows that reference arrays.
  - Typical flow: filter rows in a Table, then open tensors lazily only for the selected rows.
  - ByteStreams: keep for small inline data; optionally spill large ByteStreams to a tensor store and replace with a handle automatically.
- Backends and scale:
  - Primary persistence: SQLite (write‑through per op). DuckDB can be used locally for fast reads (same predicate IR → SQL).
  - Upgrade path: Postgres later (reuse the same predicate→SQL). pg_duckdb can accelerate SELECTs; MotherDuck is analytics‑oriented (not OLTP).
- Developer experience:
  - “Just write SLIP”: shared-scope persists transparently; Tables behave the same; tensors are loaded on demand from handles and saved when you choose—no DB protocol tokens required in user code.
