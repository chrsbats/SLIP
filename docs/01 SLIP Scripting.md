# SLIP Scripting

This guide is a quick, hands-on introduction to SLIP.

It is organized around the next practical question in the programmer's mind. Start at the top and stop as soon as you know enough to do your work.

By the end, you will be able to:
- Run a script from a file.
- Read JSON from `file://` or `http://`.
- Filter and reshape data with the Query DSL.
- Write transformed results back to disk.
- Handle errors gracefully.

---

## How do I write and run a SLIP script?

The first useful thing to know is that a SLIP script is just a sequence of expressions in a file.

Here is a complete script:

```slip
name: "Karl"
hp: 120

print "{{name}} has {{hp}} HP"

hp
```

This script:

- binds two names
- emits one line of output with `print`
- returns the value of the last expression

### Run a script file

```bash
uv run python slip.py my-script.slip
```

When you run a script file, SLIP evaluates the file from top to bottom.

### Start the REPL

```bash
uv run python slip.py
```

The REPL is useful when you want to try small expressions before writing a full script.

### What a script is made of

SLIP is intentionally small:

- everything is an expression
- there is no operator precedence
- control flow is mostly regular function calls over code blocks

This guide is about the fast path: read data, transform it, write it back, and handle failures without learning the whole language model first.

### Takeaway

To get started, think of a SLIP script as:

- a file full of expressions
- evaluated in order
- with the final expression becoming the script's result

## How do expressions evaluate?

Read a SLIP expression in the order it appears on the page.

SLIP evaluates infix operators strictly left-to-right.

```slip
-- Most languages evaluate the multiplication first, producing 20.

-- SLIP reads from left to right: 10 + 5 is 15, then 15 * 2 is 30.
10 + 5 * 2
-- => 30
```

Use parentheses `(...)` when you need a grouped sub-expression:

```slip
result: 10 + (5 * 2) -- 20
```

You can also separate multiple expressions on one line with `;`:

```slip
a: 1; b: 2
```

### Takeaway

Read SLIP exactly in the order it appears on the page.

- no hidden precedence rules
- parentheses mean "do this first"
- semicolons let you put more than one expression on a line

---

## How do I work with values and data?

Most scripts start by binding some values, shaping a little data, and moving on.

Comments use `--` for single lines and `{-- ... --}` for block comments.

### Numbers, booleans, none

```slip
count: 3
ratio: 0.75
enabled: true
missing: none
```

### Strings

SLIP has two string types:

- **raw strings**: single quotes, no interpolation: `'...'`
- **i-strings**: double quotes, evaluate `{{...}}` as SLIP expressions: `"Hello {{name}}"`

```slip
name: "Karl"

msg: "Hello {{name}}"
path: '/tmp/data.json'
```

Interpolation can call functions and read paths in the current scope:

```slip
display-name: fn {obj} [ obj.name ]
item: #{ name: 'brass key' }

"You take {{display-name item}}."
```

Multi-line i-strings are automatically de-dented:

```slip
greeting: "
    Hello {{name}}!
    Welcome back.
"
```

### Lists and dicts

The two most common data structures are lists and dicts.

```slip
nums: #[ 10, 20, 30 ]
player: #{ name: "Karl", hp: 120 }

#[ nums[0], player.name ]
```

### Takeaway

For basic scripting, the values to reach for first are:

- numbers
- booleans
- strings
- lists
- dicts

With those basic values, you can call functions and use control flow.

---

## How do I call functions and use control flow?

Once you have values, the next question is how to do work with them.

### Function calls

Calls are space-separated (no commas):

```slip
-- The following returns 30
add 10 20  
```

### The pipe `|`

The pipe passes the value on the left as the first argument:

```slip
-- Returns 30
10 |add 20 
-- Also returns 30
10 |add 5 |mul 2
```

### Defining functions with `fn`

You define a function using a signature `{...}` and a body `[...]`:

- `{...}` is a **sig literal**: it declares parameters rather than evaluating them
- `[...]` is a code block: it is passed as code and run by `fn`

```slip
add-ten: fn {n} [
    n + 10
]
```

Call it:

```slip
result: add-ten 5
```

### Code blocks

A `[...]` block is a **code value** (unevaluated code). Control-flow functions decide when to run it.

### `if`

`if` takes:
- a condition block
- a then block
- an optional else block (if omitted, `if` returns `none` when the condition is falsey)

```slip
hp: 40

status: if [hp > 50] [
    "Healthy"
] [
    "Wounded"
]
```

### `while`

```slip
i: 3
while [i > 0] [
    print i
    i: i - 1
]
```

### `foreach`

`foreach` takes a **sig literal** for the loop variable pattern.

This is the same idea as `fn {args} [...]`: the `{...}` part tells SLIP what names to bind, not what values to compute.

```slip
items: #[ "Sword", "Shield", "Potion" ]
foreach {item} items [
    print "You have a {{item}}"
]
```

Tip: for dicts, `{k}` iterates keys; `{k, v}` iterates key/value pairs.

### Takeaway

The common pattern is:

- call functions with spaces
- pipe values when it reads more naturally
- use `fn` to define reusable behavior
- pass code blocks to control-flow functions like `if`, `while`, and `foreach`

---

## How do I query and update collections?

Path syntax lets you index, slice, filter, and “pluck” values from collections.

### Filtering lists with `[ ... ]`

Inside a filter predicate:

- `.field` means “field on the current item”
- bare names are lexical variables from outside the list

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

wounded: players[.hp < 50]
names: wounded.name
```

### Pluck (vectorized field access)

If you do `.name` on a list of dicts/scopes, you get a new list of names:

```slip
names: players.name -- #["Karl", "Jaina"]
hps: players.hp     -- #[120, 45]
```

Note: for lists, filters and plucks return normal (eager) lists in the current interpreter.

### Build new data vs update in place

When transforming JSON, you’ll usually use one of these patterns:


- **Build a new value** when you want a clean transformed result
- **Update in place** when you want to change the existing data directly

### Build a new list or dict

This pattern reads from an input list and constructs a new result.

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

wounded: players[.hp < 50]

wounded-report: #{
    count: len wounded,
    names: wounded.name
}
```

### Update in place

If a query appears on the left side of an assignment, SLIP can update multiple items.

Assignment is an expression: it returns the value it wrote. For vectorized updates, it returns the list of new values written to the matched targets.

Example: boost HP for players with HP < 50:

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

-- Pluck every HP value.
players.hp
-- => #[120, 45]

-- Select HP values below 50.
players.hp[< 50]
-- => #[45]

-- Replace each selected value with itself times 1.1.
players.hp[< 50]: * 1.1
-- => #[49.5]

players.hp
-- => #[120, 49.5]
```

The “filter then pluck” version is equivalent:

```slip
players[.hp < 50].hp: * 1.1
```

### Takeaway

For collection work, the usual progression is:

- filter with `[...]`
- pluck with `.field`
- either build a new result or update matching values in place

---

## How do I read files and HTTP data?

This is the core scripting workflow: load data, reshape it, and save it again.

Here is the complete shape:

```slip
-- Read JSON.
data: file://input.json

-- Filter and reshape it.
wounded: data.players[.hp < 50]
report: #{
    wounded-count: len wounded,
    names: wounded.name
}

-- Write JSON.
file://out.json: report
```

The following sections unpack each step.

### Read from a file (`file://`)

The file extension controls parsing for structured formats:

- `.json` → JSON
- `.yaml` / `.yml` → YAML
- `.toml` → TOML

```slip
data: file://input.json
```

### Query a scheme read directly

Read paths can continue into indexes, filters, and fields. The query is applied to the value after the file is loaded:

```slip
first-name: file://input.json[0].name
```

Binding first is also useful when you reuse the data or want to make a longer transformation easier to read:

```slip
data: file://input.json
names: data.players.name
```

### Read from HTTP (`http://` / `https://`)

```slip
resp: http://api.example.com/players.json
```

HTTP reads work the same way, so a short query can stay attached to the path:

```slip
names: http://api.example.com/players.json[.hp > 100].name
```

### Write to a file

Write JSON by using a `.json` filename:

```slip
out: #{
    names: #[ "Karl", "Jaina" ]
}
file://out.json: out
```

### Takeaway

The standard pattern is:

1. read and query the data source directly, or bind it when that is clearer
2. transform the resulting value
3. write out the result if needed

---

## How do I report output, success, and failure?

Scripts usually need to do three things beyond pure calculation:

- report output
- signal success or failure
- recover from expected failure cases

SLIP scripts report output as **effects**.

- `emit <topic-or-topics> <message...>` appends an event to the script’s output log.
- Emitting does **not** mutate your variables; it’s for narration/debugging/logging.
- A single dict or list message is preserved as structured data for the host.
- Your host (or CLI) decides what to do with emitted events (show them, save them, ignore them).
- `print ...` is a convenience that emits to the standard output topic.

```slip
emit "debug" "starting script"
emit "event" #{ type: 'start', ok: true }
print "Hello, world"
```

You can emit from anywhere, including loops and functions:

```slip
count-down: fn {n} [
  i: n
  while [i > 0] [
    emit "debug" "i = {{i}}"
    i: i - 1
  ]
  emit "debug" "done"
]

count-down 3
```

### Handling failures and expected errors

There are two kinds of “things that go wrong”:

1) **Script errors** (type errors, missing paths, etc.) normally stop the script.
2) **Expected domain failure** is signaled with `fail`, optionally with a code and structured data.

Functions return ordinary values. Use `return` when you want to leave a function early:

```slip
find-player: fn {players, player-id} [
    matches: players[.id = player-id]
    if [(len matches) = 0] [
        fail `not-found` #{ player-id: player-id }
    ]
    return matches[0]
]
```

### Capturing failures with `do`

`do` runs a block and returns an `Outcome` directly:

- `.status`: `ok` or `err`
- `.value`: the ordinary result on success
- `.error`: structured failure details on error
- `.effects`: effects emitted during the block

For a domain failure, `.error` includes `.kind`, `.code`, `.message`, and `.data`. Runtime and protocol failures use the same top-level `Outcome` shape.

```slip
log: do [
    10 / 0
]

if [log.status = err] [
    print "It failed: {{log.error.message}}"
] [
    print "It worked: {{log.value}}"
]
```

### HTTP failures and full responses

By default, a successful HTTP read returns its decoded body. A non-2xx response signals a structured protocol failure, which `do` can capture:

```slip
request: do [ http://api.example.com/players.json ]

if [request.status = err] [
    print "Request failed with HTTP status {{request.error.protocol-status}}"
] [
    names: request.value.players.name
    file://out.json: #{ names: names }
]
```

Request `#(response-mode: \`full\`)` only when you need the full HTTP response envelope, including status and headers. Full mode returns `#{ status: <int>, value: <body>, meta: #{ headers: #{...} } }` and leaves non-2xx handling to your code.

```slip
resp: http://api.example.com/players.json#(response-mode: `full`)
if [(resp.status >= 200) and (resp.status < 300)] [
    print resp.value
] [
    print "Request failed with HTTP status {{resp.status}}"
]
```

### Takeaway

For everyday scripting:

- use `print` or `emit` for output
- return ordinary values and use `fail` for failures
- use `do` when you want to capture a failure instead of stopping immediately

With these tools, you know enough SLIP to write useful self-contained scripts.

---
