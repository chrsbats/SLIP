"""Symbolic Code, native scopes, callable values, and one pop evaluator."""

import inspect
import operator
import re
import struct
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from functools import partial


_MISSING = object()


class Scope(MutableMapping):
    def __init__(self, values=(), parent=None, caller=None):
        self.bindings = dict(values)
        if "meta" in self.bindings:
            raise ValueError("meta is reserved for scope metadata")
        self.meta = {"parent": parent, "caller": caller, "type-id": id(self)}
        if parent is not None:
            for name in ("source_dir", "imports"):
                if name in parent.meta:
                    self.meta[name] = parent.meta[name]
        self.effects = parent.effects if parent is not None else []
        self.signatures = parent.signatures if parent is not None else {}

    def __getitem__(self, key):
        key = scope_key(key)
        if key == "meta":
            return self.meta
        if key in self.bindings:
            return self.bindings[key]
        if self.parent is not None:
            return self.parent[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        self.bindings[scope_key(key)] = value

    def __delitem__(self, key):
        del self.bindings[scope_key(key)]

    def __iter__(self):
        return iter(self.bindings)

    def __len__(self):
        return len(self.bindings)

    def __contains__(self, key):
        key = scope_key(key)
        return key != "meta" and (key in self.bindings or (
            self.parent is not None and key in self.parent
        ))

    def __eq__(self, other):
        return self is other

    @property
    def parent(self):
        return self.meta["parent"]

    @parent.setter
    def parent(self, parent):
        self.meta["parent"] = parent

    @property
    def root(self):
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        return scope


class Code(list):
    """Editable, unevaluated lists of symbolic expressions."""

    def __init__(self, expressions=()):
        super().__init__(expressions)
        self.stacks = None
        self.template = True
        self.source_path = getattr(expressions, "source_path", None)
        self.source_text = getattr(expressions, "source_text", "")
        self.locations = getattr(expressions, "locations", [])


class Group(Code):
    pass


class IString(str):
    pass


@dataclass
class Template:
    parts: list


@dataclass
class Collection:
    kind: str
    code: Code


class Locator(str):
    """An unquoted scheme token, distinct from a quoted data key."""


class Navigation(Enum):
    PARENT = ".."
    CURRENT = "./"
    IDENTITY = "::"


@dataclass
class Path:
    keys: list
    mode: str = "get"
    options: Code | None = None


@dataclass
class MultiPath:
    paths: list


@dataclass
class PathLiteral:
    path: Path


def scope_key(key):
    if (isinstance(key, PathLiteral) and key.path.mode == "get"
            and len(key.path.keys) == 1 and isinstance(key.path.keys[0], str)):
        return key.path.keys[0]
    return key


@dataclass
class Query:
    code: Code
    predicate: bool = False


@dataclass
class Slice:
    start: Code | None = None
    end: Code | None = None


@dataclass
class Parameter:
    name: str
    annotation: object = None
    is_typed: bool = False

    def __post_init__(self):
        self.is_typed = self.is_typed or self.annotation is not None

    def __contains__(self, key):
        return key == "name" or (key == "type" and self.is_typed)

    def __getitem__(self, key):
        if key == "type" and not self.is_typed:
            raise KeyError(key)
        return getattr(self, "annotation" if key == "type" else key)

    def __setitem__(self, key, value):
        if key == "type":
            self.is_typed = True
        setattr(self, "annotation" if key == "type" else key, value)

    def __delitem__(self, key):
        if key != "type" or not self.is_typed:
            raise KeyError(key)
        self.annotation, self.is_typed = None, False


@dataclass
class Sig:
    parameters: list = field(default_factory=list)
    rest: str | None = None
    where: Code | None = None
    return_annotation: object = None
    logic: str | None = None
    types: list = field(default_factory=list)

    @property
    def positional(self):
        return [p.name for p in self.parameters if not p.is_typed]

    @property
    def keywords(self):
        return {p.name: p.annotation for p in self.parameters if p.is_typed}

    @property
    def param_order(self):
        return [(p.name, p.annotation) for p in self.parameters]

    def __getitem__(self, key):
        return getattr(self, key.replace("-", "_"))

    def __setitem__(self, key, value):
        setattr(self, key.replace("-", "_"), value)

    def __post_init__(self):
        self.parameters = [
            Parameter(p) if isinstance(p, str) else p
            for p in self.parameters
        ]

    def bind(self, args, parent, caller):
        count = len(self.parameters)
        if len(args) < count or (self.rest is None and len(args) != count):
            raise TypeError("No matching method: argument count")
        values = {p.name: arg for p, arg in zip(self.parameters, args)}
        if self.rest is not None:
            values[self.rest] = list(args[count:])
        frame = Scope(values, parent, caller)
        if caller is not None:
            frame.effects = caller.effects
            frame.meta["imports"] = caller.meta.get("imports", ())
        return frame


@dataclass
class Pipe:
    target: object


@dataclass
class Get:
    read: object


@dataclass
class Reference(Get):
    """A named/path lookup can select a function at an expression head."""

    # Retain the prepared call boundary without wrapping the selected value.
    piped: bool = False


def is_piped(value):
    return isinstance(value, Pipe) or (
        isinstance(value, Reference) and value.piped
    )


@dataclass(eq=False)
class Write:
    path: Path

    def __call__(self, *, stack, scope):
        location = locate(self.path.keys, scope)
        expression = list(reversed(stack))
        stack.clear()
        if isinstance(location, list):
            if not location:
                return []
            if expression and is_piped(expression[0]):
                return [assign(container, key, expression, scope)
                        for container, key in location]
            value = evaluate(list(reversed(expression)), scope)
            if is_list(value):
                if len(value) != len(location):
                    raise ValueError(
                        "Vector assignment requires matching lengths",
                    )
                values = value
            else:
                values = [value] * len(location)
            return [store(container, key, item)
                    for (container, key), item in zip(location, values)]
        return assign(*location, expression, scope)

    def put(self, value, scope):
        location = locate(self.path.keys, scope)
        if isinstance(location, list):
            return [
                store(container, key, value) for container, key in location
            ]
        return store(*location, value)


def assign(container, key, expression, scope):
    working = list(reversed(expression))
    current = _MISSING
    if working and is_piped(working[-1]):
        try:
            current = container[key]
        except KeyError:
            pass  # A new binding stores the pipe as a callable alias.
        if isinstance(current, Pipe):
            current = _MISSING
    result = evaluate(working, scope, first=current)
    return store(container, key, result)


def assign_many(paths, values=_MISSING, *, stack, scope):
    if values is _MISSING:
        values = evaluate(stack, scope)
    if not is_list(values) or len(values) != len(paths):
        raise TypeError(f"Destructuring requires {len(paths)} values")
    for path, value in zip(paths, values):
        if path.keys and isinstance(path.keys[0], Locator):
            resource_write(
                path, scope.root["put"], value, stack=[], scope=scope,
            )
        else:
            Write(path).put(value, scope)
    return values


def store(container, key, result):
    if isinstance(result, Scope) and isinstance(key, str):
        result.meta.setdefault("name", key)
    if isinstance(result, Lambda):
        local = container
        while isinstance(local, Scope):
            local = local.bindings
        previous = local.get(key) if isinstance(local, Mapping) else None
        if isinstance(previous, Generic):
            previous.methods.append(result)
            result = previous
        else:
            result = Generic([result])
    container[key] = result
    return result


@dataclass(eq=False)
class Delete:
    path: Path

    def __call__(self, *, scope):
        location = locate(self.path.keys, scope)
        if isinstance(location, list):
            result = None
            # Descending indexes retain the original sequence targets.
            for container, key in reversed(location):
                result = remove(container, key)
        else:
            result = remove(*location)
        if self.path.options is not None:
            make_dict(self.path.options, scope)
        return result


def remove(container, key):
    value = container[key]
    del container[key]
    return value


def path_start(keys, scope):
    value, reference = scope, None
    if keys and keys[0] == "/":
        value, keys = scope.root, keys[1:]
    elif keys and isinstance(keys[0], Get):
        value, keys = keys[0].read(scope), keys[1:]
    elif keys and isinstance(keys[0], str) and keys[0].startswith('.'):
        value, reference = scope["."], (scope, ".")
        keys = ([keys[0][1:]] if keys[0] != "." else []) + keys[1:]
    return value, keys, reference


def locate(keys, scope):
    """Walk to one native container/key; extend only for queries or plucks."""
    if Navigation.IDENTITY in keys:
        raise PermissionError("Identity paths are read-only")
    value, keys, reference = path_start(keys, scope)
    for position, key in enumerate(keys):
        if isinstance(value, Get):
            raise PermissionError("References and cells are read-only")
        if key is Navigation.CURRENT:
            continue
        if key is Navigation.PARENT:
            previous = value
            value = parent_scope(value)
            reference = previous.meta, "parent"
            continue
        if isinstance(key, Get):
            key = key.read(scope)
        if isinstance(key, Slice) and position == len(keys) - 1:
            start = execute(key.start, scope) if key.start else None
            end = execute(key.end, scope) if key.end else None
            return value, slice(start, end)
        if isinstance(key, (Query, Slice, slice)) or (
            is_list(value) and isinstance(key, str)
        ):
            locations, many = targets(
                value, keys[position:], scope, reference,
            )
            return locations if many else locations[0]
        reference = value, key
        if position < len(keys) - 1:
            value = member_value(value, key)
    if reference is None:
        raise KeyError("Empty write path")
    return reference


def get_path(keys, scope, *, value=_MISSING):
    reference = None
    if value is _MISSING:
        value, keys, reference = path_start(keys, scope)
    parent, previous = None, None
    for position, key in enumerate(keys):
        value = dereference(value, scope)
        if key in (Navigation.CURRENT, Navigation.IDENTITY):
            continue
        if key is Navigation.PARENT:
            parent, previous = value.meta, "parent"
            value = parent_scope(value)
            continue
        if isinstance(key, Get):
            key = key.read(scope)
        if isinstance(key, (Query, Slice, slice)) or (
            is_list(value) and isinstance(key, str)
        ):
            if position:
                reference = parent, previous
            locations, many = targets(
                value, keys[position:], scope, reference,
            )
            values = [value if location is reference
                      else member_value(*location) for location in locations]
            return values if many else values[0]
        parent, value = value, member_value(value, key)
        previous = key
    return dereference(value, scope)


def dereference(value, scope):
    while isinstance(value, Get):
        value = value.read(scope)
    return value


def member_value(value, key):
    if hasattr(type(value), "__getitem__"):
        return value[key]
    return getattr(value, key)


def parent_scope(value):
    if not isinstance(value, Scope) or value.parent is None:
        raise KeyError("Parent path requires a scope with a parent")
    return value.parent


def targets(value, keys, scope, reference):
    """Extend an already-read prefix into query/pluck write targets."""
    locations = [reference]
    many = False
    for position, key in enumerate(keys):
        if key in (Navigation.CURRENT, Navigation.IDENTITY):
            continue
        if isinstance(key, Get):
            key = key.read(scope)
        following = []
        for reference in locations:
            container, previous_key = reference if reference else (None, None)
            current = value if position == 0 else member_value(
                container, previous_key,
            )
            if key is Navigation.PARENT:
                parent_scope(current)
                following.append((current.meta, "parent"))
            elif isinstance(key, Query):
                many = True
                items = (
                    enumerate(current) if is_list(current)
                    else [(previous_key, current)]
                )
                for index, item in items:
                    item_scope = Scope({".": item}, scope)
                    if execute(key.code, item_scope):
                        if is_list(current):
                            following.append((current, index))
                        else:
                            following.append(reference)
            elif isinstance(key, (slice, Slice)):
                many = True
                selection = key
                if isinstance(key, Slice):
                    start = (
                        execute(key.start, scope) if key.start else None
                    )
                    end = execute(key.end, scope) if key.end else None
                    selection = slice(start, end)
                following.extend(
                    (current, i) for i in range(len(current))[selection]
                )
            elif is_list(current) and isinstance(key, str):
                many = True
                following.extend((item, key) for item in current)
            else:
                following.append((current, key))
        locations = following
    if not locations and not many:
        raise KeyError("Empty path")
    return locations, many


def local_names(code):
    names = set()
    for expression in code:
        for term in expression:
            if isinstance(term, Path) and term.mode == "set":
                if len(term.keys) == 1 and isinstance(term.keys[0], str):
                    names.add(term.keys[0])
            elif isinstance(term, MultiPath):
                names.update(path.keys[0] for path in term.paths
                             if len(path.keys) == 1
                             and isinstance(path.keys[0], str))
            elif isinstance(term, Code):
                names.update(local_names(term))
    return names


def binding_names(code, scope, locals):
    names, dynamic = set(), False
    for expression in code:
        for index, term in enumerate(expression):
            if isinstance(term, Path) and term.mode in ("get", "pipe"):
                known = _MISSING
                if len(term.keys) == 1 and isinstance(term.keys[0], str):
                    known = scope.get(term.keys[0], _MISSING)
                target = known.target if isinstance(known, Pipe) else known
                position = getattr(target, "meta", {}).get("binds")
                if position is not None:
                    if type(position) is not int or position < 0:
                        raise ValueError(
                            "binds must name a nonnegative argument index",
                        )
                    piped = term.mode == "pipe" or (
                        isinstance(known, Pipe) and index > 0
                    )
                    offset = index + position if piped \
                        else index + 1 + position
                    value = expression[offset] if offset < len(expression) \
                        else None
                    if piped and position == 0:
                        value = expression[0] if index == 1 else None
                    if isinstance(value, Sig):
                        names.update(p.name for p in value.parameters)
                    else:
                        dynamic = True
                elif index == 0 and len(expression) > 1 and (
                    known is _MISSING or isinstance(known, Get)
                    or term.keys[0] in locals
                ):
                    following = expression[1]
                    infix = isinstance(following, Path) and (
                        following.mode == "pipe" or (
                            len(following.keys) == 1
                            and isinstance(following.keys[0], str)
                            and isinstance(scope.get(following.keys[0]), Pipe)
                        )
                    )
                    dynamic |= not infix
            nested = term.parts if isinstance(term, Template) else [
                term.code if isinstance(term, Collection) else term,
            ]
            for child in nested:
                if isinstance(child, Code):
                    introduced, unknown = binding_names(child, scope, locals)
                    names.update(introduced)
                    dynamic |= unknown
    return names, dynamic


def bind(code, scope, locals=None, *, shadowed=(), dynamic=False):
    if code.stacks is not None:
        return code
    if isinstance(locals, Sig):
        locals = {p.name for p in locals.parameters}
    names = local_names(code) | (locals or set())
    introduced, unknown = binding_names(code, scope, names)
    shadowed = set(shadowed) | introduced
    dynamic |= unknown
    bound = Code(code)
    bound.stacks = [convert(expr, scope, names, shadowed=shadowed,
                            dynamic=dynamic) for expr in code]
    bound.template = has_injections(code)
    return bound


def has_injections(code):
    for expression in code:
        for term in expression:
            if isinstance(term, Group) and len(term) == 1 and term[0]:
                head = term[0][0]
                if isinstance(head, Path) and head.keys in (
                    ["inject"], ["splice"],
                ):
                    return True
            if isinstance(term, Code) and has_injections(term):
                return True
            if isinstance(term, Collection) and has_injections(term.code):
                return True
    return False


def convert_path(path, scope, locals, *, shadowed=(), dynamic=False):
    keys = []
    for key in path.keys:
        if isinstance(key, Query):
            code = bind(Code(key.code), scope, locals,
                        shadowed=shadowed, dynamic=dynamic)
            head = key.code[0][0] if key.code and key.code[0] else None
            implicit = isinstance(head, Path) and (
                head.mode == "pipe" or (
                    len(head.keys) == 1 and isinstance(head.keys[0], str)
                    and isinstance(scope.get(head.keys[0]), Pipe)
                )
            )
            if key.predicate and implicit:
                code.stacks[0].insert(0, Get(partial(get_path, ["."])))
            key = Query(code, True) if key.predicate \
                else Get(partial(execute, code))
        elif isinstance(key, Group):
            key = Get(partial(execute, bind(
                Code(key), scope, locals, shadowed=shadowed, dynamic=dynamic,
            )))
        elif isinstance(key, Slice):
            key = Slice(
                bind(Code(key.start), scope, locals,
                     shadowed=shadowed, dynamic=dynamic)
                if key.start else None,
                bind(Code(key.end), scope, locals,
                     shadowed=shadowed, dynamic=dynamic)
                if key.end else None,
            )
        keys.append(key)
    options = bind(Code(path.options), scope, locals,
                   shadowed=shadowed, dynamic=dynamic) \
        if path.options is not None else None
    return Path(keys, path.mode, options)


def convert(expression, scope, locals=None, *, shadowed=(), dynamic=False):
    if len(expression) > 1 and any(
        isinstance(term, Path) and term.mode == "del"
        and not (term.keys and isinstance(term.keys[0], Locator))
        for term in expression
    ):
        raise SyntaxError("del-path cannot be part of a larger expression")
    result = []
    for index, term in enumerate(expression):
        match term:
            case MultiPath():
                result.append(partial(assign_many, [
                    convert_path(path, scope, locals,
                                 shadowed=shadowed, dynamic=dynamic)
                    for path in term.paths
                ]))
            case Group():
                code = bind(Code(term), scope, locals,
                            shadowed=shadowed, dynamic=dynamic)
                result.append(Get(partial(execute, code)))
            case Code() if locals is not None:
                result.append(Get(partial(code_value, bind(
                    Code(term), scope, locals,
                    shadowed=shadowed, dynamic=dynamic,
                ))))
            case Collection():
                if term.kind == "dict":
                    constructor = make_dict
                elif term.kind == "list":
                    constructor = make_list
                else:
                    constructor = partial(make_bytes, term.kind)
                result.append(Get(partial(
                    constructor, bind(Code(term.code), scope, locals,
                                      shadowed=shadowed, dynamic=dynamic),
                )))
            case Template():
                parts = [Get(partial(execute, bind(
                    Code(part), scope, locals,
                    shadowed=shadowed, dynamic=dynamic,
                )))
                         if isinstance(part, Code) else part
                         for part in term.parts]
                result.append(Get(partial(interpolate, parts)))
            case Path():
                path = convert_path(term, scope, locals,
                                    shadowed=shadowed, dynamic=dynamic)
                if path.keys and isinstance(path.keys[0], Locator):
                    result.append(resource_operation(path, scope))
                    continue
                if path.mode == "set":
                    result.append(Write(path))
                    continue
                if path.mode == "del":
                    result.append(Delete(path))
                    continue
                known = _MISSING
                if (
                    len(path.keys) == 1 and isinstance(path.keys[0], str)
                    and (path.keys[0] not in (locals or ())
                         or path.keys[0] in shadowed or dynamic)
                ):
                    # Binding inspects lexical names, never host members.
                    key = path.keys[0]
                    if isinstance(key, str) and not key.startswith('.'):
                        known = scope.get(key, _MISSING)
                value = (
                    known if is_function(known) or isinstance(known, Pipe)
                    else path_getter(path.keys)
                )
                if is_function(known) and (
                    path.keys[0] in shadowed or dynamic
                ):
                    signature(known, scope)
                    value = Reference(partial(
                        captured_value, path.keys[0], known, scope,
                    ), piped=isinstance(known, Pipe) and bool(result))
                if path.mode == "pipe" and isinstance(known, Pipe):
                    raise TypeError(
                        "Cannot explicitly pipe an already piped alias",
                    )
                if path.mode == "pipe" and not isinstance(value, Pipe):
                    value = Pipe(value)
                elif isinstance(value, Pipe) and not result:
                    signature(value, scope)
                    value = Reference(lambda scope, value=value: value)
                result.append(value)
            case _:
                result.append(term)
        if (isinstance(term, Path) and term.mode == "get"
                or is_function(term)):
            following = expression[index + 1] \
                if index + 1 < len(expression) else None
            if isinstance(following, Path) and following.mode == "pipe":
                # A bare callable before a pipe is its input, not a call.
                value = result[-1]
                if isinstance(value, Reference) and not value.piped:
                    result[-1] = Get(value.read)
                elif is_function(value) and not isinstance(value, Pipe):
                    signature(value, scope)
                    result[-1] = Get(lambda scope, value=value: value)
    for value in result:
        if isinstance(value, Pipe):
            value = value.target
        if is_function(value):
            signature(value, scope)
    return result


def is_function(value):
    return isinstance(value, Pipe) or (
        callable(value) and not isinstance(value, (Mapping, Sequence))
    )


def is_list(value):
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray),
    )


def read(value, scope):
    if isinstance(value, Get):
        return value.read(scope)
    if isinstance(value, Pipe) and isinstance(value.target, Get):
        return Pipe(value.target.read(scope))
    return value


def path_getter(keys):
    return Reference(partial(get_path, keys))


def captured_value(name, captured, definition, scope):
    current = scope
    root = definition.root
    while current is scope or (
        current is not definition and current is not root
    ):
        values = current.bindings
        while isinstance(values, Scope):
            values = values.bindings
        if name in values:
            return dereference(values[name], scope)
        if current is definition:
            break
        current = current.parent
        if current is None:
            break
    return captured


def resource_operation(path, scope):
    name = {"get": "get", "pipe": "get", "set": "put",
            "del": "del", "post": "post"}[path.mode]
    operation = scope.root[name]
    signature(operation, scope)
    if path.mode in ("get", "pipe"):
        getter = Get(partial(resource_read, path, operation))
        return Pipe(getter) if path.mode == "pipe" else getter
    return partial(resource_write, path, operation)


def resource_read(path, get, scope):
    options = make_dict(path.options, scope) \
        if path.options is not None else {}
    value = invoke(get, [path.keys[0], options], scope)
    return get_path(path.keys[1:], scope, value=value)


def resource_write(path, operation, *values, stack, scope):
    if len(path.keys) != 1:
        raise ValueError("Resource writes require a locator without a query")
    options = make_dict(path.options, scope) \
        if path.options is not None else {}
    args = [path.keys[0]]
    if path.mode != "del":
        if len(values) > 1:
            raise TypeError("Resource write requires one value")
        args.append(values[0] if values else evaluate(stack, scope))
    response = invoke(operation, [*args, options], scope)
    return args[1] if path.mode == "set" else response


def make_list(code, scope):
    return [
        evaluate(list(reversed(expr)), scope) for expr in code.stacks
    ]


def code_value(value, scope):
    """Fresh syntax sharing prepared lists and inserted native values."""
    if isinstance(value, Code):
        result = type(value)(value)
        result[:] = [[code_value(term, scope) for term in expression]
                     for expression in value]
        result.stacks, result.template = value.stacks, value.template
        return result
    if isinstance(value, (Collection, Template, Path, MultiPath, PathLiteral,
                          Query, Slice, Parameter, Sig)):
        copied = {}
        for description in fields(value):
            item = getattr(value, description.name)
            copied[description.name] = [code_value(v, scope) for v in item] \
                if isinstance(item, list) else code_value(item, scope)
        return replace(value, **copied)
    return value


def make_dict(code, scope):
    target = Scope(parent=scope)
    execute(code, target)
    return target.bindings


def make_bytes(kind, code, scope):
    values = make_list(code, scope)
    formats = {"u8": "B", "u16": "H", "u32": "I", "u64": "Q",
               "i8": "b", "i16": "h", "i32": "i", "i64": "q",
               "f32": "f", "f64": "d"}
    try:
        if kind == "b1":
            bits = "".join("1" if value else "0" for value in values)
            bits += "0" * (-len(bits) % 8)
            return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
        if kind not in formats:
            raise TypeError(f"Unknown byte-stream type: {kind}")
        if kind.startswith("u") or kind == "i8":
            mask = (1 << int(kind[1:])) - 1
            values = [int(value) & mask for value in values]
            if kind == "i8":
                return bytes(values)
        elif kind.startswith("i"):
            values = [int(value) for value in values]
        return struct.pack("<" + formats[kind] * len(values), *values)
    except (TypeError, ValueError, OverflowError, struct.error) as error:
        raise TypeError(f"Invalid value for {kind} byte stream: {error}") \
            from error


def interpolate(parts, scope):
    return IString("".join([str(read(part, scope)) for part in parts]))


def pop_arguments(minimum, maximum, stack, scope, args):
    if stack is not None:
        while stack and len(args) < maximum:
            value = argument(stack, scope, required=len(args) < minimum)
            if value is _MISSING:
                break
            args.append(value)
        if len(args) < minimum:
            raise TypeError(
                f"Expected at least {minimum} arguments, got {len(args)}"
            )
    return args


def supplied_arguments(minimum, stack, scope, args):
    if len(args) < minimum:
        raise TypeError(
            f"Expected at least {minimum} arguments, got {len(args)}"
        )
    return args


def signature(function, scope):
    if isinstance(function, Pipe):
        function = read(function, scope).target
    bound = getattr(function, "_slip_arguments", None)
    if bound is None:
        cached = scope.signatures.get(id(function))
        bound = cached[1] if cached is not None else None
    if bound is not None:
        return bound
    bound = bind_signature(function)
    if isinstance(function, (Lambda, Generic, Write, Delete)):
        function._slip_arguments = bound
    else:
        scope.signatures[id(function)] = function, bound
    return bound


def bind_signature(function):
    if isinstance(function, (Lambda, Generic)):
        return lambda: function.arity, partial(slip_arguments, function)
    if inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(
        getattr(function, "__call__", None),
    ):
        raise TypeError("Async functions are unsupported by synchronous SLIP")
    parameters = inspect.signature(function).parameters.values()
    positional = [p for p in parameters if p.kind in (
        p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD,
    )]
    minimum = sum(p.default is p.empty for p in positional)
    maximum = (
        float("inf") if any(p.kind == p.VAR_POSITIONAL for p in parameters)
        else len(positional)
    )
    providers = {
        "scope": lambda stack, scope: scope,
        "stack": lambda stack, scope: stack if stack is not None else [],
    }
    keywords = [(p.name, providers[p.name]) for p in parameters
                if p.kind == p.KEYWORD_ONLY and p.name in providers]
    take = partial(pop_arguments, minimum, maximum)
    if any(name == "stack" for name, _ in keywords):
        take = partial(supplied_arguments, minimum)

    def arguments(stack, scope, args):
        values = take(stack, scope, args)
        return values, {name: get(stack, scope) for name, get in keywords}

    return lambda: (minimum, maximum), arguments


def slip_arguments(function, stack, scope, args):
    values = pop_arguments(*function.arity, stack, scope, args)
    return values, {"scope": scope}


def invoke(function, args, scope, stack=None):
    if isinstance(function, Pipe):
        function = read(function, scope).target
    _, arguments = signature(function, scope)
    args, keywords = arguments(stack, scope, args)
    return function(*args, **keywords)


def argument(stack, scope, required=False):
    term = stack.pop()
    if not required and is_piped(term):
        stack.append(term)
        return _MISSING
    value = read(term, scope)
    if isinstance(value, Pipe) and not required:
        stack.append(value)
        return _MISSING
    return value


def evaluate(stack, scope, first=_MISSING):
    """Pop a reversed working list, retaining the saved expression."""
    if first is _MISSING:
        if not stack:
            return None
        head = stack.pop()
        if is_function(head) and not isinstance(head, Pipe):
            last = invoke(head, [], scope, stack)
        else:
            last = read(head, scope)
            if isinstance(head, Reference) and is_function(last):
                last = invoke(last, [], scope, stack)
    else:
        last = first
    while stack:
        function = read(stack.pop(), scope)
        if isinstance(function, Pipe):
            function = function.target
        if not is_function(function):
            raise TypeError(f"Expected a piped function, got {function!r}")
        last = invoke(function, [last], scope, stack)
    return last


def execute(code, scope):
    result = None
    saved = code.stacks
    for index, expression in enumerate(code if saved is None else saved):
        try:
            prepared = convert(expression, scope) \
                if saved is None else expression
            result = evaluate(list(reversed(prepared)), scope)
        except Exception as error:
            location = dict(code.locations[index]) \
                if index < len(code.locations) else {}
            location["file"] = code.source_path or scope.meta.get(
                "source_path", "<script>",
            )
            lines = code.source_text.splitlines()
            line = location.get("line", 0)
            location["source"] = lines[line - 1] \
                if 0 < line <= len(lines) else ""
            if not getattr(error, "slip_trace", None):
                error.slip_trace = []
                error.error_token = {
                    key: location[key] for key in ("line", "col", "text")
                    if key in location
                }
            error.slip_trace.append(location)
            raise
    return result


@dataclass(eq=False)
class Lambda:
    sig: Sig
    body: Code
    definition_scope: Scope
    meta: dict = field(default_factory=dict)

    def __getitem__(self, key):
        if key == "methods":
            return [self]
        if key not in ("meta", "sig", "body"):
            raise KeyError(key)
        return getattr(self, key)

    def __post_init__(self):
        names = local_names(self.body) | {p.name for p in self.sig.parameters}
        if self.sig.rest:
            names.add(self.sig.rest)
        self.code = bind(Code(self.body), self.definition_scope, names)
        if self.code.source_path is None:
            self.code.source_path = self.definition_scope.meta.get(
                "source_path",
            )
        self.stacks = self.code.stacks
        self.meta["type"] = self.sig
        self.meta["parent"] = self.definition_scope
        self.meta.setdefault(
            "guards", [self.sig.where] if self.sig.where else [],
        )
        self.guards = [bind(Code(code), self.definition_scope, names)
                       for code in self.meta["guards"]]
        count = len(self.sig.parameters)
        self.arity = count, float("inf") if self.sig.rest else count

    def __call__(self, *args, scope):
        frame = self.sig.bind(args, self.definition_scope, scope)
        try:
            return execute(self.code, frame)
        except Return as returned:
            return returned.value


def specificity(value, annotation, scope=None):
    if annotation is None:
        return 0
    if isinstance(annotation, Path) and scope is not None:
        try:
            annotation = resolve_type(annotation, scope)
        except KeyError:
            return None
    if isinstance(annotation, Sig) and annotation.logic:
        scores = [specificity(value, item, scope) for item in annotation.types]
        if annotation.logic == "and":
            return min(scores) if all(s is not None for s in scores) else None
        return max((s for s in scores if s is not None), default=None)
    if isinstance(annotation, Scope):
        current, distance = value, 0
        while isinstance(current, Scope):
            if current is annotation:
                return 1000 - distance
            current, distance = current.parent, distance + 1
        return None
    if isinstance(annotation, PathLiteral):
        annotation = annotation.path.keys[0]
    types = {
        "int": int, "float": float, "string": str, "i-string": IString,
        "boolean": bool, "sig": Sig,
        "list": list, "dict": dict, "scope": Scope, "code": Code,
        "path": PathLiteral, "none": type(None),
    }
    if annotation == "id":
        matches = isinstance(value, str) and value.startswith("id:")
        return 2 if matches else None
    if annotation == "number":
        return 1 if type(value) in (int, float) else None
    if annotation == "function":
        return 1 if is_function(value) else None
    if annotation == "list":
        return 1 if is_list(value) else None
    if annotation == "scope":
        return 1 if isinstance(value, Scope) else None
    if annotation == "dict":
        matches = isinstance(value, Mapping) and not isinstance(value, Scope)
        return 1 if matches else None
    expected = types.get(annotation)
    return 1 if expected is not None and type(value) is expected else None


@dataclass(eq=False)
class Generic:
    methods: list
    meta: dict = field(default_factory=dict)

    def __getitem__(self, key):
        if key not in ("methods", "meta"):
            raise KeyError(key)
        return getattr(self, key)

    def __post_init__(self):
        self._arity_count = -1
        self._arity = 0, 0

    @property
    def arity(self):
        if self._arity_count != len(self.methods):
            self._arity = (
                min((method.arity[0] for method in self.methods), default=0),
                max((method.arity[1] for method in self.methods), default=0),
            )
            self._arity_count = len(self.methods)
        return self._arity

    def __call__(self, *args, scope):
        candidates = []
        for order, method in enumerate(self.methods):
            sig = method.sig
            count = len(sig.parameters)
            if len(args) < count or (not sig.rest and len(args) != count):
                continue
            scores = tuple(
                (1 if arg is None else None)
                if parameter.is_typed and parameter.annotation is None
                else specificity(arg, parameter.annotation,
                                 method.definition_scope)
                for arg, parameter in zip(args, sig.parameters)
            )
            if any(score is None for score in scores):
                continue
            rank = (
                any(p.is_typed for p in sig.parameters),
                sig.rest is None, scores, bool(method.guards), order,
            )
            candidates.append((rank, method))
        if len(candidates) > 1:
            candidates.sort(key=lambda item: item[0], reverse=True)
        for _, method in candidates:
            if method.guards:
                frame = method.sig.bind(args, method.definition_scope, scope)
                if not all(execute(guard, frame) for guard in method.guards):
                    continue
            return method(*args, scope=scope)
        labels = {Scope: "scope", PathLiteral: "path", Code: "code",
                  str: "string", IString: "i-string", bool: "boolean",
                  type(None): "none"}
        names = [labels.get(type(arg), type(arg).__name__) for arg in args]
        message = "No matching method\nargs: (" + ", ".join(names)
        message += ")\ncandidates:"
        for method in self.methods:
            parameters = []
            for parameter in method.sig.parameters:
                annotation = parameter.annotation
                if isinstance(annotation, PathLiteral):
                    annotation = ".".join(map(str, annotation.path.keys))
                elif isinstance(annotation, Scope):
                    annotation = "scope"
                elif isinstance(annotation, Sig):
                    annotation = "signature"
                text = parameter.name
                if parameter.is_typed:
                    text += ": " + str(annotation)
                parameters.append(text)
            if method.sig.rest:
                parameters.append(method.sig.rest + "...")
            reason = "argument count/type mismatch"
            if any(method is candidate for _, candidate in candidates):
                reason = "guard did not pass"
            message += "\n- {" + ", ".join(parameters) + "}: " + reason
        raise TypeError(message)


class Return(BaseException):
    def __init__(self, value):
        self.value = value


class Failure(Exception):
    def __init__(self, error):
        self.error = error
        super().__init__(error["message"])


def error_details(error):
    if isinstance(error, Failure):
        return dict(error.error)
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", type(error).__name__)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()
    return {
        "kind": PathLiteral(Path([
            "syntax" if isinstance(error, SyntaxError) else "runtime",
        ])),
        "code": PathLiteral(Path([name])), "message": str(error), "data": None,
    }


def fn(sig, body, *, scope):
    parameters = [
        Parameter(p.name, resolve_type(p.annotation, scope, defer=True),
                  p.is_typed)
        for p in sig.parameters
    ]
    return Lambda(Sig(parameters, sig.rest, sig.where, sig.return_annotation),
                  body, scope)


def resolve_type(annotation, scope, *, defer=False):
    if isinstance(annotation, Sig) and annotation.logic:
        return Sig(logic=annotation.logic, types=[
            resolve_type(item, scope, defer=defer) for item in annotation.types
        ])
    if isinstance(annotation, (Path, PathLiteral)):
        path = annotation.path \
            if isinstance(annotation, PathLiteral) else annotation
        builtin = {"int", "float", "number", "string", "i-string", "id",
                   "boolean", "list", "dict", "scope", "code", "sig",
                   "function", "path", "none"}
        if (len(path.keys) == 1 and isinstance(path.keys[0], str)
                and path.keys[0] in builtin):
            return PathLiteral(path)
        try:
            resolved = get_path(convert_path(path, scope, None).keys, scope)
        except KeyError:
            if defer:
                return path
            raise
        return resolve_type(resolved, scope, defer=defer) \
            if isinstance(resolved, Sig) and resolved.logic else resolved
    return annotation


def conditional(*values, stack, scope):
    if len(values) > 3:
        raise TypeError("if takes a condition and one or two branches")
    supplied = list(values)
    condition = supplied.pop(0) if supplied else \
        pop_arguments(1, 1, stack, scope, [])[0]
    branches = [(False, value) for value in supplied]
    if not branches:
        if not stack:
            raise TypeError("Expected at least 2 arguments for if")
        branches.append((True, stack.pop()))
    if len(branches) < 2 and stack and not is_piped(stack[-1]):
        branches.append((True, stack.pop()))
    accepted = execute(condition, scope) if isinstance(condition, Code) \
        else condition
    index = 0 if accepted else 1
    if index >= len(branches):
        return None
    deferred, selected = branches[index]
    if deferred:
        selected = read(selected, scope)
    return execute(selected, scope) if isinstance(selected, Code) else selected


def while_loop(condition, body, *, scope):
    if condition.stacks is None or body.stacks is None:
        names = local_names(body)
        condition = bind(condition, scope, names)
        body = bind(body, scope, names)
    result = None
    while execute(condition, scope):
        result = execute(body, scope)
    return result


def return_value(value=_MISSING, *, stack=None, scope=None):
    if value is _MISSING:
        value = argument(stack, scope, required=True) if stack else None
    if stack:
        raise TypeError(
            "return takes at most one value; "
            "wrap complex return expressions in parentheses",
        )
    raise Return(value)


def fail(code, data=_MISSING):
    if data is _MISSING:
        code, data = PathLiteral(Path(["error"])), code
    if isinstance(code, str):
        code = PathLiteral(Path([code]))
    if isinstance(code, Path):
        code = PathLiteral(code)
    if not isinstance(code, PathLiteral):
        raise TypeError("Failure code must be a path or string")
    from .slip_syntax import format_path

    raise Failure({
        "kind": PathLiteral(Path(["domain"])), "code": code, "data": data,
        "message": data.get("message", format_path(code.path))
        if isinstance(data, Mapping) else str(data),
    })


def do(code, *, scope):
    start = len(scope.effects)
    try:
        value = execute(code, scope)
        return {
            "status": PathLiteral(Path(["ok"])), "value": value,
            "error": None, "effects": list(scope.effects[start:]),
        }
    except Exception as error:
        details = error_details(error)
        return {
            "status": PathLiteral(Path(["err"])), "value": None,
            "error": details, "effects": list(scope.effects[start:]),
        }


def emit(topics, *messages, scope):
    message = (
        messages[0] if len(messages) == 1 else " ".join(map(str, messages))
    )
    scope.effects.append({
        "topics": topics if isinstance(topics, list) else [topics],
        "message": message,
    })


def run(code, *, scope):
    target = Scope(parent=scope.root)
    target.effects = scope.effects
    for name in ("source_dir", "imports"):
        if name in scope.meta:
            target.meta[name] = scope.meta[name]
    source = expand(code, scope) if code.template else code
    return execute(bind(Code(source), target), target)


def run_with(code, target, *, scope):
    frame = Scope(parent=scope, caller=scope)
    frame.bindings = target
    frame.effects = scope.effects
    frame.meta["lexical"] = scope.meta.get("lexical", scope)
    for name in ("source_dir", "imports"):
        if name in scope.meta:
            frame.meta[name] = scope.meta[name]
    source = expand(code, scope) if code.template else code
    return execute(bind(Code(source), frame), frame)


def current_scope(*, scope):
    return scope.meta.get("lexical", scope)


def call(function, args=(), *, scope):
    if isinstance(function, str):
        from .slip_syntax import to_path
        function = to_path(function)
    if isinstance(function, PathLiteral):
        function = read(convert([function.path], scope)[0], scope)
    if isinstance(function, Write):
        if len(args) != 1:
            raise TypeError("Set path requires one value")
        return function.put(args[0], scope)
    if isinstance(function, Pipe):
        function = function.target
    if not callable(function):
        raise TypeError("Expected a callable target")
    return invoke(function, args, scope)


def expand(code, scope):
    """Fill explicit inject/splice groups while retaining symbolic source."""
    output = type(code)()
    output.source_text, output.source_path = code.source_text, code.source_path
    for index, expression in enumerate(code):
        location = code.locations[index] if index < len(code.locations) else {}
        terms = []
        for term in expression:
            special = None
            if isinstance(term, Group) and len(term) == 1 and term[0]:
                head = term[0][0]
                if isinstance(head, Path) and head.keys in (
                    ["inject"], ["splice"],
                ):
                    special = head.keys[0]
            if special:
                working = list(reversed(convert(term[0], scope)[1:]))
                value, = pop_arguments(1, 1, working, scope, [])
                if working:
                    raise TypeError(
                        f"{special} takes one value; group nested expressions",
                    )
                if special == "splice":
                    if isinstance(value, Code):
                        if len(expression) != 1:
                            raise TypeError("Code splice requires a statement")
                        expanded = expand(value, scope)
                        output.extend(expanded)
                        output.locations.extend(
                            expanded.locations or [location] * len(expanded),
                        )
                    else:
                        terms.extend(value)
                else:
                    terms.append(value)
            elif isinstance(term, Code):
                terms.append(expand(term, scope))
            elif isinstance(term, Collection):
                terms.append(Collection(
                    term.kind, expand(term.code, scope),
                ))
            else:
                terms.append(term)
        if terms:
            output.append(terms)
            output.locations.append(location)
    return output


def logical_and(first=_MISSING, second=_MISSING, *, stack, scope):
    if first is _MISSING:
        first = pop_arguments(1, 1, stack, scope, [])[0]
    if second is _MISSING and not stack:
        raise TypeError("and requires a right operand")
    if first:
        return argument(stack, scope, required=True) \
            if second is _MISSING else second
    if second is _MISSING:
        stack.pop()
    return first


def logical_or(first=_MISSING, second=_MISSING, *, stack, scope):
    if first is _MISSING:
        first = pop_arguments(1, 1, stack, scope, [])[0]
    if second is _MISSING and not stack:
        raise TypeError("or requires a right operand")
    if not first:
        return argument(stack, scope, required=True) \
            if second is _MISSING else second
    if second is _MISSING:
        stack.pop()
    return first


def add(left, right):
    if is_list(left) and not is_list(right):
        return [*left, right]
    return left + right


def language_scope():
    functions = {
        "add": add, "sub": operator.sub, "mul": operator.mul,
        "div": operator.truediv, "eq": operator.eq, "ne": operator.ne,
        "lt": operator.lt, "le": operator.le, "gt": operator.gt,
        "ge": operator.ge, "pow": operator.pow,
    }
    scope = Scope({**functions, **{
        f"core-{name}": function for name, function in functions.items()
    }})
    for name, function in {
        "+": add, "-": operator.sub, "*": operator.mul,
        "/": operator.truediv, "**": operator.pow, "=": operator.eq,
        "!=": operator.ne, "<": operator.lt, "<=": operator.le,
        ">": operator.gt, ">=": operator.ge,
        "and": logical_and, "or": logical_or,
    }.items():
        scope[name] = Pipe(function)
    scope.bindings.update({
        "fn": fn, "if": conditional, "while": while_loop,
        "core-bind": bind, "core-execute": execute,
        "return": return_value, "fail": fail, "do": do, "emit": emit,
        "run": run, "run-with": run_with, "call": call,
        "current-scope": current_scope, "len": len, "not": operator.not_,
        "logical-and": logical_and, "logical-or": logical_or,
        "scope": Scope, "ok": PathLiteral(Path(["ok"])),
        "err": PathLiteral(Path(["err"])),
    })
    return scope
