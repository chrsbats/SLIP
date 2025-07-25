# SLIP Parser Implementation Notes

This document records ambiguities and missing details discovered in the "SLIP Language Reference.md" while creating a formal grammar. Resolving these points is crucial for a correct and robust parser implementation.

### 1. Ambiguity in Identifier vs. Operator Syntax

The specification treats operators like `+`, `=`, and `*` as paths, but it does not formally define the character set for a `name` segment of a path.

- **Observation:** Examples use kebab-case (`is-active`), but operators use symbols (`+`, `**`).
- **Problem:** The parser needs a precise rule (i.e., a regular expression) to distinguish a valid `name` segment from other language constructs. Is `is-active?` a valid path? Is `a+b` one path or three tokens (`a`, `+`, `b`)?
- **Proposed Rule:** We should assume that a `name` segment consists of alphanumeric characters, underscores, and hyphens, but cannot be composed *only* of symbols that are also operators. A path that is an operator (`+`, `*`, etc.) is parsed as a single-segment path.

A formal definition is needed. For example:
-   `NAME_SEGMENT_REGEX`: `[a-zA-Z_][a-zA-Z0-9_-]*`
-   `OPERATOR_PATH_REGEX`: `[\+\-\*\/=<>!]+` (or a specific list)

The `term` rule in the grammar must then be ordered to check for specific operator literals (`+`, `*`, `and`, etc.) *before* attempting to parse a general `name` path.

### 2. Expression Term Delimiters

The specification implies that terms within a single expression are separated by whitespace.

- **Observation:** `10 + 5` is clearly three terms. `user.name` is clearly one term. The `.` character is an intra-path separator, not an expression-level delimiter.
- **Problem:** This rule is implicit. A formal grammar needs to make it explicit.
- **Clarification:** The parser will be built with the assumption that `one_or_more` whitespace characters separate the `term`s within a `prefix_expression`. The `path` rule will handle consuming the `.` characters internally.

### 3. Contradiction in Interpolated String Parsing

There are conflicting specifications for how interpolated strings (`"..."`) should be parsed.

1.  **Your Instruction:** The parser should produce a single, opaque node: `[i-string "Hello, {{name}}!"]`. This suggests the parser does not look inside the string at all.
2.  **Language Spec (Section 8.2):** This section was updated to describe a Jinja2-like mechanism and provides a specific AST: `[string "This line is indented by ", [expr [path [name 'indent_level']]], " spaces..."]`. This requires the parser to identify and parse the `{{...}}` blocks as expression "islands".
3.  **Language Spec (Appendix C):** This appendix, the formal AST reference, does not show an AST for an interpolated string at all, only a simple string value like `<string "John">`.

- **Problem:** These three specifications are mutually exclusive. We need a single source of truth.
- **Recommendation:** Your instruction (Option 1) is the most consistent with SLIP's "dumb parser" philosophy. It simplifies the parser's job significantly and leaves the complex work of interpolation to the evaluator, as intended. The parser would simply tag the node as `i-string` and capture the entire raw content. **We will proceed with this model unless you direct otherwise.**

### 4. Missing AST for Path Literals

The specification defines a path literal using backticks (e.g., `` `user.name ``) to create a literal `path` object without performing a lookup.

- **Problem:** Appendix C defines the AST for a `path` that is *evaluated* (`[path [name 'user']...]`), but not for a `path` that is a *literal value*.
- **Proposed AST:** A new AST node tag is required. I propose `path-literal`.
    - **Source:** `` `user.name ``
    - **Proposed AST:** `[path-literal [name 'user'], [name 'name']]`

This distinguishes it from an evaluated path lookup and allows the evaluator to handle it correctly.
### 1. RESOLVED: Identifier vs. Operator Syntax

The character sets for path names and operators have been clarified.

-   **`name` segment:** A path segment intended for variables, functions, etc.
    -   **Rule:** Consists of one or more characters from the set `A-Z`, `a-z`, `0-9`, and `-`. Underscores (`_`) are not permitted.
    -   **Regex:** `[a-zA-Z0-9-]+`
-   **`operator` path:** A path composed entirely of operator symbols. By convention, these are bound to piped paths to create infix syntax.
    -   **Rule:** Consists of one or more characters from the set `!@#$%^&*-+`.
    -   **Regex:** `[!@#$%^&*-+]+`
    -   The `/` operator is a special case and will be defined as its own literal.
-   **Resolution:** The grammar's `term` rule must attempt to match keywords (`true`, `fn`, etc.) and operator paths (`+`, `**`, etc.) *before* attempting to match a general `name` path.

### 3. RESOLVED: Interpolated String Parsing

The correct parsing strategy for interpolated strings (`"..."`) has been confirmed.

-   **Conflict:** The language reference contained conflicting descriptions of how interpolated strings should be handled by the parser.
-   **Resolution:** The parser's role is to be "dumb." It will not attempt to parse the `{{...}}` blocks within a double-quoted string.
    -   **Source:** `"Hello, {{name}}!"`
    -   **AST:** `[i-string "Hello, {{name}}!"]`
-   The parser will generate a single `i-string` node containing the raw, unmodified content of the string. The evaluator is responsible for passing this string and the current environment to a Jinja2 rendering engine.

### 5. Reference: Path Segment Types

Based on clarifications, the following is the definitive list of path segments the parser must recognize. A `path` or `set-path` node will contain an ordered list of these segment nodes.

| Segment Name | Syntax           | Example AST Fragment | Notes                                                              |
| :----------- | :--------------- | :------------------- | :----------------------------------------------------------------- |
| `name`       | `user-name`      | `[name 'user-name']` | The basic building block.                                          |
| `pipe`       | `|`              | `[pipe]`             | Must be the first segment. Not allowed in a `set-path`.            |
| `root`       | `/` (at start)   | `[root]`             | Refers to the root environment. e.g., `/config`.                   |
| `parent`     | `../`            | `[parent]`           | Moves up one level in the environment chain.                       |
| `pwd`        | `./`             | `[pwd]`              | "Present Working Directory." Refers to the current `env` object.   |
| `index`      | `[...]`          | `[index <expr>]`     | Dynamic index access with a single expression.                     |
| `slice`      | `[start:end]`    | `[slice <e1> <e2>]`  | Slice access. `start` and `end` are optional expressions.          |
| `dynamic`    | `(...)`          | `[expr ...]`         | A computed segment. The result of the `expr` is used as a key.     |
