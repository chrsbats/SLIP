
# Appendix B - SLIP Style Guide

For a guided introduction, start with [SLIP Scripting](<01 SLIP Scripting.md>). For language contracts, use the [StdLib Reference](<Appendix A - StdLib Reference.md>).

## Philosophy

This guide collects formatting conventions that make SLIP easy to read. Most of it is advice; the short **Syntax Constraints** section calls out the spacing that changes how code is tokenized.

## Naming Conventions

SLIP uses distinct naming conventions to signal the intended role of a value.

*   **`kebab-case` for Variables and Functions:** Use `kebab-case` for ordinary assignments, generic functions, and object instances.
    ```slip
    -- Correct
    Player: scope #{}
    main-player: create Player [ name: "Kael" ]
    add-numbers: fn {a, b} [ a + b ]

    -- Incorrect
    main_player: none
    addNumbers: none
    ```

*   **`PascalCase` for Prototypes, Types, and Schemas:** Use `PascalCase` for names intended to be prototypes, type aliases, or validation schemas.
    ```slip
    -- Correct: A prototype is a `scope`.
    Character: scope #{
        hp: 100
    }

    -- Correct: A validation schema is a `schema`.
    UserSchema: schema #{
        name: `string`,
        age: (optional `number`)
    }

    -- Correct: A type alias is a `sig`.
    UserID: {string or int}
    ```

*   **`UPPER-KEBAB-CASE` for Application Constants:** Use `UPPER-KEBAB-CASE` for fixed values specific to an application or domain.
    ```slip
    -- Correct
    MAX-HP: 1000
    DEFAULT-TIMEOUT: 5
    ```

*   **`kebab-case` for Core Aliases:** Core library aliases that read like language words use `kebab-case`. This aligns them with built-in literals like `true` and `none`.
    ```slip
    -- Correct (in core.slip)
    ok: `ok`
    err: `err`

    -- Correct usage in code
    if [result.status = ok] [ print "Success" ]
    ```

## Syntax Constraints

These two spacing rules are part of the syntax rather than style preferences.

*   **Assignment (`:`):** Keep the name and assignment colon together because `name:` is a single `set-path` token.
    ```slip
    -- Correct
    x: 10
    ```
    <!-- slip-test: parse-error -->
    ```slip
    -- Syntax Error
    x : 10
    ```

*   **Piped Paths (`|`):** Keep the pipe and following path together because `|path` is a single `piped-path` token.
    ```slip
    -- Correct
    data |map (fn {item} [ item.name ])
    ```
    <!-- slip-test: parse-error -->
    ```slip
    -- Syntax Error: `| map` is not a valid token.
    data | map (fn {item} [ item.name ])
    ```
    ```slip
    -- Valid, though spacing before the pipe is easier to scan.
    data|map (fn {item} [ item.name ])
    ```

Other call-shape constraints are worth remembering:

*   Commas separate list, dict, and signature items. They do not separate function arguments or statements.
*   A function signature can contain at most one `|where` clause.

## Spacing and Indentation

These are readability recommendations:

*   **Indentation:** Use **4 spaces** for each level of indentation.

*   **Pipes:** Put whitespace before a piped path: `data |map transform`.

## Formatting Blocks and Statements

Code blocks and statements should be formatted for maximum readability.

*   **Block Formatting:** Blocks can be single-line for simplicity or multi-line for complex content. A single, consistent style should be used for all multi-line blocks.

    - **Single-line Blocks:** For short functions and simple literals, a single-line format is preferred for its conciseness.
        ```slip
        add: fn {a, b} [a + b]
        items: #[ 1, 2, 3 ]
        config: #{ host: "localhost", port: 8080 }
        ```

    - **Multi-line Blocks (Egyptian Style):** When a block spans multiple lines, keep the opening delimiter (`[`, `{`, etc.) on the introducing line. Indent the content and align the closing delimiter with the start of the statement.
        ```slip
        x: 12

        -- Correct multi-line formatting for `if`
        if [x > 10] [
            print "Greater"
            x + 1
        ] [
            print "Lesser"
            x - 1
        ]

        -- Correct multi-line formatting for a long function
        my-long-func: fn {arg1, arg2} [
            result: arg1 + arg2
            return result
        ]

        my-long-func 1 2
        -- => 3
        ```

*   **Clarity with `return`:** An explicit `return` often makes the result of a multi-line function easier to spot. `return` accepts at most one value; when returning a call, comparison, or logical expression, group it explicitly:
    ```slip
    sum: fn {} [ return (add 1 2) ]
    is-storm?: fn {weather} [ return (weather = `storm`) ]
    is-day?: fn {nighttime?} [ return (not nighttime?) ]
    ```

*   **Refinement with `|where` (default style):** Put a `|where` clause inside the function signature when it makes a dispatch rule clearer.
    ```slip
    -- Correct
    apply-damage: fn {this: Combat, amount |where amount > 0} [
        this.hp: this.hp - amount
    ]
    ```

*   **Function Calls:** Arguments to functions are separated by spaces.
    <!-- slip-test: parse-error -->
    ```slip
    add 10 20      -- Correct
    (add 10 20)    -- Correct
    add 10, 20     -- Wrong: `add` receives only one argument.
    ```

*   Call formatting is line-aware (no special forms). Keep calls on one line when all parts render as single-line. If any argument renders multi-line, keep the head and any consecutive single-line args on the first line; put each remaining argument on its own line at the current indentation. The block/list/dict printers handle the indentation of their contents.
    ```slip
    cond: true
    then: "yes"
    else: "no"

    if [cond] [then] [else]               -- all one-liners
    if [cond] [
        then
    ] [
        else
    ]
    ```

*   **Sig literals for binding metadata:** Use `{}` when an argument declares names to bind rather than computes a value:
    - `fn {args} [body]`
    - `foreach {vars} collection [body]`
    - `for {i} start end [body]`

    Follow the same convention in user-defined binding forms. The braces make the call site self-explanatory: `{y}` declares a binding named `y`.

*   **Commas:** Use one space after a comma inside `sig`, `dict`, and `list` literals.
    ```slip
    config: #{ host: "localhost", port: 8080 }
    numbers: {int, float}
    items: #[ 1, 2, 3 ]
    ```

## Comments

*   **Single-line Comments:** Use `--` followed by a space.
    ```slip
    -- This is a good comment.
    x: 10
    ```

*   **Executable Results:** Put `-- =>` immediately after an expression when the documentation states its result. Every active marker is executed by the documentation test suite.
    ```slip
    10 + 5
    -- => 15
    ```

    For a multiline value, put the opening form after `-- =>` and continue it with consecutive comment lines.

    Python fences are executed by default. If a Python example is intentionally a fragment that depends on surrounding code, mark it explicitly:

    ```html
    <!-- slip-test: fragment -->
    ```

## Metadata and Configuration

*   **Persistent Metadata (`.meta`):** Use standard property access on the reserved `.meta` property to set documentation and other persistent metadata.
    ```slip
    -- Correct
    Character: scope #{}
    Character.meta.doc: "The base prototype for all characters."
    ```

*   **Transient Configuration (`#(...)`):** Use the `#(...)` block immediately following a path to provide one-time configuration for an operation.
    ```slip
    -- Correct
    result: api/call#(timeout: 5)
    ```

## Parentheses

*   **Evaluation Groups:** Use parentheses `(...)` to override left-to-right evaluation or to pass a call, comparison, or logical expression as one argument. Their presence should make the intended grouping clearer.
    ```slip
    -- Default left-to-right evaluation is preferred for clarity.
    result: 10 + 5 * 2  -- -> 30

    -- Use parentheses only to force a different order.
    result: 10 + (5 * 2) -- -> 20
    ```
