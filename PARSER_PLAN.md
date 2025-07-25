
## Plan for Parsing SLIP with Koine

### 1. Guiding Principles

The SLIP language reference makes it clear that the parser's role is intentionally "dumb" regarding semantics. The goal is to produce an Abstract Syntax Tree (AST) that is a direct, 1:1 representation of the source code's structure. The evaluator, not the parser, handles operator precedence and other semantic interpretations.

Our Koine grammar will adhere to these core principles:

1.  **Direct Representation:** The parser will not reorder expressions. An infix expression like `10 + 5 * 2` will be parsed into a flat list of tokens, not a nested tree based on operator precedence. We will achieve this by avoiding Koine's `left_associative_op` structure for these rules and instead using simple sequences.
2.  **Explicit Nesting Only:** The AST will only contain nested structures when the source code uses explicit grouping operators like `(...)`, `[...]`, `#{...}`, etc.
3.  **Assignment is a Special Form:** The colon (`:`) for assignment is the only true "special form" with its own unique syntax. The grammar will treat the left-hand side (LHS) as a literal, unevaluated pattern.
4.  **Target AST:** The grammar will be designed to produce an AST that precisely matches the structure defined in **Appendix C** of the SLIP Language Reference.

### 2. Top-Level Grammar Structure

A SLIP script is a sequence of expressions, which can be separated by newlines or semicolons.

-   **`program` (Start Rule):** The root of our grammar. It will be tagged as `code`. It will parse `zero_or_more` `line_expression`s, separated by optional whitespace and terminators (newline or `;`), and collect their resulting `expr` nodes as its children. This produces the `[code [expr ...], [expr ...]]` structure.
-   **`line_expression`:** A single logical line of code that produces one `expr` node. To correctly generate a `set-path` for the LHS of an assignment (as required by Appendix C), the parser must check for a `colon_expr` before falling back to a `full_expression`.
-   **`full_expression`:** This rule will enforce SLIP's `prefix_call (pipe_chain)*` grammar. It will be a `sequence` of a `prefix_expression` followed by `zero_or_more` `pipe_expression`s. This structure correctly parses `data |map [...]` but makes an invalid expression like `add 1 add 2` a syntax error, as required.
-   **`prefix_expression`:** This rule will represent a simple expression like `add 1 2` or `10 + 5 * 2`. It will be defined as a `one_or_more` sequence of `term`s. The resulting AST node for this rule will be promoted to produce the desired flat list of its children.

This top-level design ensures we get flat lists for simple infix math while enforcing the overall structure that prevents ambiguous chains of function calls.

### 3. Core Concepts & Grammar Rules

Here is a breakdown of how we will model each major language feature.

#### 3.1. Colon Expressions (:)

This is the most unique syntactic feature. The left-hand side is an unevaluated pattern.

-   **`colon_expr`:** A rule that parses expressions containing a top-level colon (`:`). It is defined as a `sequence: [assignment_target, ':', full_expression]`. The rule itself will be tagged as `expr`. This is necessary for the parser to distinguish `x: 1` from `x 1`, allowing it to generate the required `set-path` node for the `assignment_target` on the left.
-   **`assignment_target`:** A `choice` rule to capture the different binding patterns:
    -   A **`set_path`** pattern (e.g., `user.name`, `items[0]`). This will look very similar to the `path` rule but will produce `set-path` tagged nodes in the AST.
    -   A **`multi_set`** pattern (e.g., `[x, y]`). This will be a rule that parses a list of `set-path`s inside square brackets `[]` and produces a `multi-set` tagged node.
    -   A **dynamic target** pattern (`(...)`). This will re-use the `group` rule to allow a parenthesized expression to be evaluated as the assignment target.

Using Koine's `ast: { tag: '...' }` directive is critical here to distinguish `set-path` from a normal, readable `path`.

#### 3.2. Paths (for Reading)

Paths are the core of identity in SLIP. A `path` can be composed of multiple segments.

-   **`path`:** A rule that produces a node tagged `path`. It will be a `sequence` of an optional `pipe` segment followed by one or more other segments.
-   **`path_segment`:** A `choice` of the following segment types, each with its own rule:
    -   `name_segment`: A sequence of identifiers separated by dots (e.g., `user.name`). Will be parsed into a series of `[name '...']` nodes. The rule will also handle variadic parameter syntax (e.g., `tags...`) by matching a name followed by `...` and capturing the full text in the `name` node.
    -   `parent_segment`: The `../` operator, producing a `[parent]` node.
    -   `root_segment`: The `/` operator at the start of a path, producing a `[root]` node.
    -   `pwd_segment`: The `./` operator, producing a `[pwd]` node.
    -   `index_segment`: Dynamic access with `[...]`, containing an expression (e.g., `items[i]`), producing an `[index ...]` node.
    -   `slice_segment`: Dynamic access with `[...]`, containing a `start:end` pattern (e.g., `items[1:4]`), producing a `[slice ...]` node.
    -   `dynamic_segment`: A parenthesized `(...)` expression that resolves to a path segment, producing an `[expr ...]` node.

#### 3.3. Literals and Primary Terms

These are the fundamental building blocks of expressions.

-   **`term`:** This will be a central `choice` rule that matches any of the following:
    -   `number_literal`: A regex for integers and floats. Will use `ast: { type: 'number' }`.
    -   `string_literal`: See below.
    -   `boolean_literal`: `literal: 'true'` or `literal: 'false'`. Will use `ast: { type: 'bool' }`.
    -   `none_literal`: `literal: 'none'`. Will use `ast: { type: 'null' }`.
    -   `path_literal`: A backticked path `` `... ``.
    -   `path`: A regular (unquoted) path for lookups.
    -   `group`: A parenthesized `(...)` expression.
    -   `code_block`: A `[...]` block.
    -   `list_literal`: A `#[...]` block.
    -   `dict_literal`: A `{...}` block.
    -   `env_literal`: A `#{...}` block.

-   **`string_literal`:** A `choice` between two types of strings:
    -   **`raw_string`**: A single-quoted string (`'...'`). The contents are captured literally. The AST node will be tagged `string`.
    -   **`interpolated_string`**: A double-quoted string (`"..."`). The parser captures the entire content, including the `{{...}}` markers, as a single piece of text. The AST node will be tagged `i-string`. The evaluator is responsible for processing the interpolation.

#### 3.4. Comments

The grammar must correctly parse and discard comments.

-   **Single-Line (`//`):** The rule for this will be `sequence: ['//', positive_lookahead(whitespace | end_of_line), rest_of_line]`. The `positive_lookahead` is crucial to enforce the whitespace requirement without consuming it, distinguishing a comment from a path like `//server/path`. The entire rule will be marked `ast: { discard: true }`.
-   **Multi-Line (`/* ... */`):** Standard regex is insufficient for nestable comments. We will define a recursive grammar rule:
    -   `block_comment`: `sequence: ['/*', zero_or_more(choice: [text_chunk, block_comment]), '*/']`.
    -   `text_chunk` will be a regex that matches any character sequence that does not contain `/*` or `*/`.
    -   The entire `block_comment` rule will be marked `ast: { discard: true }`.

### 4. Ambiguity Resolution

The SLIP grammar is designed to be unambiguous for a PEG parser like Koine, provided the choices are ordered correctly.

1.  **Keywords vs. Paths:** In any `choice` block, rules for keywords (`if`, `fn`, `true`, `none`, etc.) must be listed *before* the general `path` rule. This ensures `if` is parsed as a keyword, not a path named `if`.
2.  **Colon Expression vs. Other Expressions:** The `line_expression` rule will try to match a `colon_expr` first. This is a standard PEG parser technique to handle grammars where one pattern is a more specific version of another. It ensures the left-hand side of a `:` is correctly parsed as a `set-path`.
3.  **Flat Infix vs. Prefix Calls:** The `prefix_call (pipe_chain)*` structure resolved the ambiguity of chained calls like `add 1 add 2`. Our grammar directly implements this structure.

### 5. AST Examples

To make the target AST concrete, here are examples of how SLIP source code will be parsed according to this plan and the specification in Appendix C. In these examples, `<...>` represents a literal value token.

#### Simple Infix Expression

This demonstrates the flat list structure for expressions without explicit grouping.

-   **Source:** `10 + 5`
-   **AST:** `[expr <number 10>, [path [name '+']], <number 5>]`

#### Piped Expression

This shows how a `pipe_expression` follows a `prefix_expression`, and how the `|` operator is parsed as a `pipe` segment on the subsequent path.

-   **Source:** `data |map [x * 2]`
-   **AST:** `[expr [path [name 'data']], [path [pipe], [name 'map']], [code [expr [path [name 'x']], [path [name '*']], <number 2>]] ]`

#### Simple Assignment

This shows the structure for the most common operation, highlighting the `set-path` node.

-   **Source:** `user.name: "John"`
-   **AST:** `[expr [set-path [name 'user'], [name 'name']], <string "John">]`

#### Destructuring Assignment

This shows the `multi-set` node for destructuring a list into multiple targets.

-   **Source:** `[x, y]: #[10, 20]`
-   **AST:** `[expr [multi-set [set-path [name 'x']] [set-path [name 'y']]], [list <number 10>, <number 20>] ]`

#### Path with Multiple Segments

This demonstrates how a complex path is composed of different segment types.

-   **Source:** `../data[0].name`
-   **AST:** `[path [parent], [name 'data'], [index <number 0>], [name 'name']]`

#### Interpolated String

This shows how an interpolated string is parsed into a single opaque `i-string` node. The evaluator, not the parser, will handle the `{{...}}` content.

-   **Source:** `"Hello, {{name}}!"`
-   **AST:** `[i-string "Hello, {{name}}!"]`


### 6. AST Generation Strategy

We will make extensive use of Koine's `ast` directives to transform the parse tree into the clean, specified AST from Appendix C.

-   **`ast: { discard: true }`:** Will be used heavily for whitespace, punctuation (`(`, `)`, `,`, `:`, etc.), and comments.
-   **`ast: { promote: true }`:** Will be used to flatten the tree where intermediate rules are not needed in the final AST (e.g., for `prefix_expression` to produce a flat list).
-   **`ast: { tag: '...' }`:** Will be used on almost every significant rule to create the correctly tagged nodes (e.g., `path`, `set-path`, `list`, `expr`).
-   **`ast: { leaf: true }`:** Will be used for terminal rules like `number`, `string_content`, and operators to capture their text value.
-   **`ast: { structure: { ... } }` and `map_children`:** These can be used to create nodes with named children. However, for most of SLIP's AST, the target structure is a simple tagged list. We must adhere to the Appendix C specification and avoid creating named children. For `assignment`, a simple `[expr <target>, <value>]` node will be generated from a sequence rule.

This plan provides a complete roadmap to building a robust SLIP parser that respects the language's unique design philosophy and produces the exact AST required by the evaluator.
