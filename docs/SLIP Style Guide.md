
### **The Official SLIP Style Guide v1.0**

**1. Philosophy**

This guide defines the canonical formatting conventions for the SLIP language. The goal is to produce code that is clean, consistent, and easy to read. While the language grammar is flexible in some areas, this guide presents the single, official style that should be used in all SLIP projects.

The official formatting tool, `slipfmt`, will automatically enforce these rules.

**2. Naming Conventions**

SLIP uses distinct naming conventions to signal the intended role of a variable. The linter (`sliplint`) will enforce these conventions to prevent common errors.

*   **`kebab-case` for Variables and Functions:** All standard assignments, including generic functions and instances of objects, **MUST** use `kebab-case`.
    ```slip
    // Correct
    main-player: create Player "Kael"
    add-numbers: fn {a, b} [ a + b ]

    // Incorrect
    main_player: ...
    addNumbers: ...
    ```

*   **`PascalCase` for Prototypes, Types, and Schemas:** Any name intended to be used as a prototype, a type alias, or a validation schema **MUST** use `PascalCase`. The linter will warn if a `PascalCase` name is assigned a value other than a `scope`, `schema`, or `sig`.
    ```slip
    // Correct: A prototype is a `scope`.
    Character: scope #{
        hp: 100
    }

    // Correct: A validation schema is a `schema`.
    UserSchema: schema #{
        name: string,
        age: (optional number)
    }

    // Correct: A type alias is a `sig`.
    UserID: {string, int}
    ```

*   **`UPPER-KEBAB-CASE` for Application Constants:** Names representing fixed, constant values specific to an application or domain **MUST** use `UPPER-KEBAB-CASE`.
    ```slip
    // Correct
    MAX-HP: 1000
    DEFAULT-TIMEOUT: 5
    ```

*   **`kebab-case` for Core Aliases:** Core library aliases that function like keywords (e.g., for response statuses) **SHOULD** use `kebab-case`. This aligns them with built-in literals like `true` and `none`.
    ```slip
    // Correct (in core.slip)
    ok: `ok`
    err: `err`

    // Correct usage in code
    respond ok "Success"
    ```

**3. Spacing and Indentation**

SLIP's syntax requires specific spacing rules for clarity and to avoid ambiguity.

*   **Indentation:** Use **4 spaces** for each level of indentation.

*   **Assignment (`:`):** There **MUST NOT** be any whitespace between a name and the assignment colon. This is a syntactic requirement, as `name:` is a single `set-path` token.
    ```slip
    // Correct
    x: 10

    // Syntax Error
    x : 10
    ```

*   **Piped Paths (`|`):** There **MUST NOT** be any whitespace between the pipe character and the following path. This is a syntactic requirement, as `|path` is a single `piped-path` token. There **MUST** be whitespace *before* the pipe character to separate it from the preceding term.
    ```slip
    // Correct
    data |map [ ... ]

    // Syntax Error: `| map` is not a valid token.
    data | map [ ... ]

    // Syntax Error: `data|map` would be parsed as a single, invalid path name.
    data|map [ ... ]
    ```

**4. Formatting Blocks and Statements**

Code blocks and statements should be formatted for maximum readability.

*   **Block Formatting:** Blocks can be single-line for simplicity or multi-line for complex content. A single, consistent style should be used for all multi-line blocks.

    - **Single-line Blocks:** For short functions and simple literals, a single-line format is preferred for its conciseness.
        ```slip
        add: fn {a, b} [a + b]
        items: #[ 1, 2, 3 ]
        config: #{ host: "localhost", port: 8080 }
        ```

    - **Multi-line Blocks (Egyptian Style):** For any block that spans multiple lines, the opening delimiter (`[`, `{`, etc.) **MUST** remain on the same line as the statement that introduces it. The content is indented, and the closing delimiter is on its own line, aligned with the start of the statement.
        ```slip
        // Correct multi-line formatting for `if`
        if [x > 10] [
            print "Greater"
            x + 1
        ] [
            print "Lesser"
            x - 1
        ]

        // Correct multi-line formatting for a long function
        my-long-func: fn {arg1, arg2} [
            // ... implementation
            return result
        ]
        ```

*   **Clarity with `return`:** In a multi-line function body, it is strongly recommended to use an explicit `return` for the final expression. This removes any ambiguity about what the function's output is and improves readability.

*   **Function Calls:** Arguments to functions are separated by spaces. Commas are not used.
    ```slip
    add 10 20      // Correct
    (add 10 20)    // Correct
    add 10, 20     // Syntax Error
    ```

*   **Commas:** Use one space after a comma inside `sig`, `dict`, and `list` literals.
    ```slip
    config: #{ host: "localhost", port: 8080 }
    numbers: {int, float}
    items: #[ 1, 2, 3 ]
    ```

**5. Comments**

*   **Single-line Comments:** Use `//` followed by a space.
    ```slip
    // This is a good comment.
    x: 10
    ```

**6. Metadata and Configuration**

*   **Persistent Metadata (`.meta`):** Use standard property access on the reserved `.meta` property to set documentation and other persistent metadata.
    ```slip
    // Correct
    Character.meta.doc: "The base prototype for all characters."
    ```

*   **Transient Configuration (`#(...)`):** Use the `#(...)` block immediately following a path to provide one-time configuration for an operation.
    ```slip
    // Correct
    response: api/call#(timeout: 5)
    ```

**7. Parentheses**

*   **Evaluation Groups:** Use parentheses `(...)` only when necessary to override the default left-to-right evaluation order. Their presence should be a strong signal to the reader that something non-standard is happening.
    ```slip
    // Default left-to-right evaluation is preferred for clarity.
    result: 10 + 5 * 2  // -> 30

    // Use parentheses only to force a different order.
    result: 10 + (5 * 2) // -> 20
    ```
