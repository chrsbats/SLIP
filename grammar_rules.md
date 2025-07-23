
## SLIP Grammar: An Unambiguity Analysis 

This document provides a detailed breakdown of the SLIP language's grammar, explaining the rules that ensure the syntax is unambiguous and can be parsed deterministically. The primary goal is to assist in the creation of a formal grammar by highlighting the specific tokens and structural patterns that differentiate seemingly similar constructs.

### Core Parsing Philosophy

The SLIP parser is "syntactically smart" but "semantically dumb." It recognizes a fixed set of structural patterns but does not understand operator precedence. Its primary job is to translate source text into a direct, 1:1 Abstract Syntax Tree (AST) representation. The key to its unambiguity lies in a few core principles:

1.  **Prefix-First Grammar:** Every line or expression block must begin with a recognizable prefix form (a path for a function call, a value for an infix chain, an assignment pattern, etc.).
2.  **Distinct Bracketing:** Each type of bracket (`(`, `[`, `{`, `#{`, `#[`) signals a unique syntactic context.
3.  **Whitespace Sensitivity (in specific cases):** Whitespace is crucial for disambiguating certain tokens, most notably the `//` comment.
4.  **The set-path (`<path>:`) as a "special form":** The set-path expression with an assignment operator `:` is the only true "special form" in the grammar. 
    - `x:` Here x is considered to be a quoted path.
    - `(function-the-return-a-path):`  The expression in () is evaluated. It is assumed it returns a quoted path. 
    - `[x,(y)]: #[10,20]`  A destructuring version that set the path x to 10 and whatever path (y) evaluates to 20.

---

### 1. Top-Level Expressions: Distinguishing Call Types

At the beginning of any expression (including a new line), the parser must distinguish between different types of calls. The structure is `prefix_call (infix_chain)*`.

#### 1.1. Prefix Call vs. Infix Chain

*   **Prefix Call:** `function arg1 arg2 ...`
    *   **Example:** `add 1 2`
    *   **Grammar Rule:** An expression starting with a `path` followed by one or more subsequent expressions is a prefix call. The parser groups this into a single `[expr ...]` node.
    *   **Unambiguity:** The expression `add 1 add 2` is a syntax error because after the prefix call `add 1` is parsed, the next token `add` cannot start a valid infix chain.

*   **Infix Chain:** `value piped_path arg1 ...` or `value infix_op_path arg1 ...`
    *   **Example:** `data |map [...]` or `10 + 5`
    *   **Grammar Rule:** An expression starting with a value (a literal, a parenthesized group, etc.) followed by a *piped path* (a path starting with `|`) or an infix operator path (like `+`) begins an infix chain.
    *   **Unambiguity:** The parser can differentiate these two main forms by looking at the **type of token** that follows the first complete value. If it's a **piped path** (e.g., `|map`) or an infix operator path (e.g., `+`), it's an infix chain. Otherwise, the initial expression must be a self-contained prefix call.

---

### 2. Path and Operator Syntax

Paths are fundamental and have a flexible syntax, but clear rules prevent ambiguity with other language constructs.

#### 2.1. Piped Paths and the `|` Character

*   **Example:** `data |map [...]`
*   **Grammar Rule:** The `|` character is **not a standalone operator**. It is a special character that can appear only at the very beginning of a path, turning it into a "piped path." The parser should have a single token definition for `path` that can optionally begin with `|`. When it sees `|map`, it should not produce two tokens (`|` and `map`), but a single `path` token whose AST representation is `[path [pipe] [name 'map']]`.
*   **Unambiguity:** This resolves all ambiguity at the parsing level. There is no "pipe operator" to conflict with anything. There are simply two kinds of paths recognized by the tokenizer: regular paths (like `map`) and piped paths (like `|map`). The evaluator is responsible for interpreting a `value` followed by a `piped_path` as an implicit pipe call.

#### 2.2. Infix Operators (`+`, `*`, etc.)

*   **Example:** `10 + 20`
*   **Grammar Rule:** Infix operators are simply `path`s (e.g., a path with one segment, `[name '+']`). They are not special keywords. The evaluator, not the parser, gives them their infix meaning. When the evaluator sees `10 + 5`, it resolves the path `+` and finds it is bound to a *piped path* (e.g., `|add`). This triggers the exact same evaluation rule as an explicit piped path, making the syntax perfectly consistent.
*   **Unambiguity:** The parser treats `+` identically to any other path like `add`. The grammar rule that an expression of the form `value path ...` is an implicit pipe call is what makes this work. There is no ambiguity for the parser because it doesn't need to treat `+` differently from `foo`.

#### 2.3. The Comment Operator `//`

*   **Example:** `x: 10 // a comment` vs. a path like `http://host`
*   **Grammar Rule:** The sequence `//` is treated as a single-line comment **if and only if** it is followed by a whitespace character or the end of the line/file.
*   **Unambiguity:** This rule explicitly resolves the conflict. A path can contain `/` but not the sequence `//`. The parser can use lookahead: upon seeing `//`, it checks the next character. If it's whitespace, it's a comment; otherwise, it is a syntax error, as `//` is a reserved sequence.

---

### 3. Grouping Operators: `()`, `[]`, `{}`, `#[]`, `#{}`

Each bracketing form has a unique and non-overlapping purpose.

*   **`(...)` - Evaluation Group:**
    *   **Example:** `10 + (5 * 2)`
    *   **Grammar Rule:** A `(` begins an evaluation group. The parser will parse the contents as a standard SLIP expression list, which will be evaluated immediately at runtime.
    *   **Unambiguity:** The `(` token is unique to this purpose.

*   **`[...]` - Code Block Literal:**
    *   **Example:** `if condition [...] [...]`
    *   **Grammar Rule:** A `[` begins a `code` literal. The parser will parse the contents as a list of expressions but will wrap the entire result in a `[code ...]` AST node, signifying that it should not be evaluated immediately.
    *   **Unambiguity:** The `[` token is unique for creating `code` literals. It cannot be confused with list indexing, which always follows a value (e.g., `my_list[0]`).

*   **`#[...]`, `#{...}`, `{...}`, `#{...}`- Constructor Literals:**
    *   **Examples:** `items: #[1, 2]`, `config: #{a:1}`, `data: {b:2}`
    *   **Grammar Rule:** These are parsed as distinct two-character opening tokens: `#[`, `#{`, `{` and `#{`. Each signals a unique constructor type (`list`, `env`, `dict`, `env`).
    *   **Unambiguity:** The parser can treat `#[`, `#{`, `{` and `#{` as single, unique tokens that open a specific literal type. There is no overlap between them or with the simple `[` code block. The closing tokens `]` and `}` correspond to their opening counterparts.

---

### 4. The Assignment Operator `:`

The colon `:` is the only operator with special parsing rules for its left-hand side (LHS). The LHS is treated as a *pattern*, not an expression to be evaluated.

*   **Rule:** The parser must analyze the structure of the tokens to the left of the `:` to determine the assignment type.

#### 4.1. Simple vs. Destructuring vs. Dynamic Assignment

*   **Simple Path:** `user.name: "John"`
    *   **Grammar Rule:** If the LHS is a single, valid `path` structure, it is a simple assignment. The parser creates a `[set-path ...]` node.

*   **Destructuring List:** `[x, y]: #[10, 20]`
    *   **Grammar Rule:** If the LHS begins with `[` and ends with `]`, it is a destructuring assignment. The contents of the brackets must be a comma-separated list of valid `set-path` patterns. The parser creates a `[multi-set ...]` node.

*   **Dynamic Target:** `(get_path "name"): "John"`
    *   **Grammar Rule:** If the LHS begins with `(` and ends with `)`, it is a dynamic assignment. The contents are parsed as a regular, evaluatable expression.

*   **Unambiguity:** The outermost tokens of the LHS (`path`, `[...]`, or `(...)`) provide a clear, unambiguous signal to the parser about which assignment strategy to parse. A path cannot start with `[` or `(`, a list cannot be unbracketed, and a group must be parenthesized.

#### 4.2. Property vs. Slice Assignment

*   **Property:** `users[0].is_active: false`
    *   **Grammar Rule:** This is a standard `set-path` where the final segment is a name (`.is_active`).

*   **Slice Replacement:** `items[1:3]: #["new"]`
    *   **Grammar Rule:** This is a `set-path` where the final segment is a slice (`[1:3]`).

*   **Unambiguity:** The parser can distinguish these because a property access is always `.name`, while a slice or index is `[...]`. These path segments are structurally distinct. The grammar for a `set-path` allows for a sequence of these segments, and the parser simply records them in order.

---

### 5. Function and Method Definitions

The `fn` and `method` primitives are standard prefix function calls.

*   **`fn` Example:** `double: fn [x] [x * 2]`
*   **`method` Example:** `render: method [obj] [obj.type = `player] [...]`
*   **Grammar Rule:** `fn` and `method` are parsed as paths that begin a prefix function call.
    *   `fn` expects an argument list (`[...]`) followed by a `code` block (`[...]`).
    *   `method` expects an argument list (`[...]`), a predicate `code` block (`[...]`), and a body `code` block (`[...]`).
*   **Unambiguity:** These follow the standard prefix call syntax. The parser identifies the `fn` or `method` path and then expects a specific number of bracketed arguments to follow. There is no conflict with other grammar rules.

---

### 6. String Literals and Interpolation

*   **Single vs. Double Quotes:** `''` vs. `""`
    *   **Grammar Rule:** Single-quoted strings are raw literals. Double-quoted strings can contain interpolation blocks.
    *   **Unambiguity:** The opening quote determines the parsing mode for the string's content.

*   **Interpolation:** `"Hello, {{name}}!"`
    *   **Grammar Rule:** Inside a double-quoted string, the `{{` token refers to a templated expression. The parser will just return the full string, and the evaluator will use a jinja2 library to render the template.
    *   **Unambiguity:** The opening double quote determines the parsing mode for the string's content.

### Summary of Unambiguous Rules for a Parser

| Construct | Key Differentiator | Explanation |
| :--- | :--- | :--- |
| **Prefix vs. Infix Call** | Token type after first value | A piped path (`|map`) or infix operator path (`+`) signals an infix chain. Anything else means the first expression is a complete prefix call. |
| **Comment `//`** | Whitespace lookahead | `//` followed by whitespace is a comment. `//` is otherwise a reserved sequence, illegal in paths. |
| **Grouping Brackets** | Opening token(s) | `(`, `[`, `#[`, `#{`, `{` are all unique tokens that define the type of the block that follows. |
| **Assignment LHS** | Outermost structure | A bare `path`, a `[...]` list, or a `(...)` group on the LHS signals a simple, destructuring, or dynamic assignment, respectively. |
| **String Interpolation** | Context (inside `""`) | The `{...}` form is only syntactically special inside a double-quoted string. |
| **Piped Path (`\|map`)** | `\|` at the start of a path token | The `\|` is part of the path's syntax, not a separate operator. It creates a distinct "piped path" token type. |

By adhering to these clear and distinct rules, the SLIP grammar, while expressive, remains deterministic and free of ambiguity for a parser to process.