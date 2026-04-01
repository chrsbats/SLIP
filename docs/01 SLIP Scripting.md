# SLIP Scripter Guide

This guide is a quick, hands-on introduction to SLIP. We'll start with the basics of evaluating expressions and move quickly into reading, transforming, and writing data.

By the end, you will be able to:
- Run a script from a file.
- Read JSON from `file://` or `http://`.
- Filter and reshape data with the Query DSL.
- Write transformed results back to disk.
- Handle errors gracefully.

To run a script, execute:

```bash
slip my-script.slip
```

SLIP is intentionally small:
- everything is an expression
- there is no operator precedence 
- all control flow is done with functions that take code blocks (no special forms)

This guide is about the fast path: read data, transform it, write it back, and handle failures without learning the whole language model first.

---

## 1) The Golden Rule: Left-to-Right 

SLIP evaluates infix operators strictly left-to-right.

```slip
In most languages: 
10 + 5 * 2 = 10 + 10 = 20

In SLIP: 
10 + 5 * 2 = 15 * 2 = 30
```

Use parentheses `(...)` when you need a grouped sub-expression:

```slip
result: 10 + (5 * 2) -- 20
```

You can also separate multiple expressions on one line with `;`:

```slip
a: 1; b: 2
```

---

## 2) Values 

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

- **raw strings**: single quotes, no templating: `'...'`
- **i-strings**: double quotes, specify templates: `"Hello {{name}}"`

```slip
name: "Karl"

msg: "Hello {{name}}"
path: '/tmp/data.json'
```

Multi-line i-strings are automatically de-dented:

```slip
greeting: "
    Hello {{name}}!
    Welcome back.
"
```

---

## 3) Expressions, Calls, and the Pipe

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

---

## 4) Code Blocks and Control Flow

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

---

## 5) Data Structures (Lists and Dicts)

### Lists: `#[...]`

```slip
nums: #[ 10, 20, 30 ]
first: nums[0]
slice: nums[1:3]
```

### Dicts: `#{...}`

```slip
player: #{
    name: "Karl",
    hp: 120
}

player.name
player["hp"]
```

---

## 6) The Path Query DSL (Read)

You can index, slice, filter, and “pluck” with path syntax.

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

---

## 7) Transform Patterns: Build New Data vs Update In Place

When transforming JSON, you’ll usually use one of these patterns:

- **Build a new value** (beginner-friendly, no mutation of the input)
- **Update in place** (fast and convenient)

### 7.1 Build a new list/dict (no mutation)

This pattern reads from an input list and constructs a new list of output rows.

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

### 7.2 Update in place (vectorized updates)

If a query appears on the left side of an assignment, SLIP can update multiple items.

Assignment is an expression: it returns the value it wrote. For vectorized updates, it returns the list of new values written to the matched targets.

Example: boost HP for players with HP < 50:

```slip
players: #[
    #{ name: "Karl",  hp: 120 },
    #{ name: "Jaina", hp: 45  }
]

players.hp[< 50]: * 1.1
```

The “filter then pluck” version is equivalent:

```slip
players[.hp < 50].hp: * 1.1
```

---

## 8) I/O: Read JSON, Transform, Write JSON

This is the core “scripting” workflow.

### 8.1 Read from a file (`file://`)

The file extension controls parsing for structured formats:

- `.json` → JSON
- `.yaml` / `.yml` → YAML
- `.toml` → TOML

```slip
data: file://input.json
```

### Important: scheme GETs are two-step

In the current interpreter, **you cannot filter/pluck directly on the same `file://...` or `http://...` expression**.

This is illegal:

```slip
-- ❌ does not work (scheme GETs can't include a trailing query)
names: file://input.json[0]
```

Rule: with `file://...` and `http://...`, **bind first, then query**. Don’t attach `[...]` or `.field` directly to the scheme path; always query the bound value.

```slip
data: file://input.json
names: data.players.name
```

### 8.2 Read from HTTP (`http://` / `https://`)

```slip
resp: http://api.example.com/players.json
```

Again: bind first, then query.

```slip
players: http://api.example.com/players.json

-- If the API returns a list of player objects:
names: players.name
```

### 8.3 Write to a file

Write JSON by using a `.json` filename:

```slip
out: #{
    names: #[ "Karl", "Jaina" ]
}
file://out.json: out
```

---

## 9) Seeing Output: `emit` (Effects as Data)

SLIP scripts report output as **effects**.

- `emit <channel> <message...>` appends an event to the script’s output log.
- Emitting does **not** mutate your variables; it’s for narration/debugging/logging.
- Your host (or CLI) decides what to do with emitted events (show them, save them, ignore them).
- `print ...` is a convenience that emits to the standard output channel.

```slip
emit "debug" "starting script"
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

---

## 10) Handling Errors Like a Scripter

There are two kinds of “things that go wrong”:

1) **Script errors** (type errors, missing paths, etc.) normally stop the script.
2) **Expected failure** is handled as data (e.g., `response err ...`).

### Catching a crash with `do`

`do` runs a block and returns:

- `log.outcome`: a `response`
- `log.effects`: the emitted effects during that block

If the block returns normally, `log.outcome` is `response ok <value>`.
If the block raises an error, `log.outcome` is `response err <message>`.
If the block already returns a `response`, `do` preserves it.

Tip: `ok` and `err` are standard aliases provided by the core library.

```slip
log: do [
    10 / 0
]

if [log.outcome.status = err] [
    print "It failed: {{log.outcome.value}}"
] [
    print "It worked: {{log.outcome.value}}"
]
```

### HTTP without crashing (lite/full mode)

By default, HTTP raises an error on non-2xx. If you want to handle it yourself, request a response mode:

- preferred: `#(response-mode: \`lite\`)` returns `#[status, value]`
- preferred: `#(response-mode: \`full\`)` returns `#{ status: <int>, value: <any>, meta: #{ headers: #{...} } }`
- legacy `#(lite: true)` and `#(full: true)` are still accepted

```slip
resp: http://api.example.com/players.json#(response-mode: `lite`)
status: resp[0]
body: resp[1]

if [status != 200] [
    print "Request failed with status {{status}}"
] [
    names: body.players.name
    file://out.json: #{ names: names }
]
```

---

## 11) One Complete Script: JSON In → Transform → JSON Out

```slip
-- 1) Read JSON
data: file://input.json

-- 2) Extract and filter
players: data.players
wounded: players[.hp < 50]

-- 3) Transform into a new shape
report: #{
    wounded-count: len wounded,
    names: wounded.name
}

-- 4) Write JSON
file://out.json: report
```

---
