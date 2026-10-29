"""Native functions and SLIP definitions using the same pop evaluator."""

import copy
import json
import math
import operator
import random
import textwrap
import time
from collections.abc import Mapping
from importlib.resources import files

import toml
from safer_yaml import dumps, loads

from .slip_core import (
    Code, Collection, Failure, Generic, Get, IString, Lambda, Locator,
    Parameter, Path, PathLiteral, Pipe, Scope, Sig, Template, bind,
    convert_path, dereference, emit, execute, fail, get_path, invoke,
    is_function, is_list,
    language_scope, make_dict, make_list, resolve_type, resource_read,
    run_with, specificity,
)


SOURCE = files(__package__).joinpath("root.slip").read_text(encoding="utf-8")


def add(left, right):
    if isinstance(left, list) and not isinstance(right, list):
        return [*left, right]
    return left + right


def extract_simple_param(sig):
    if len(sig.parameters) != 1 or sig.rest:
        raise ValueError("Expected a signature with one parameter")
    return sig.parameters[0].name


def foreach(sig, data, body, *, scope):
    names = [parameter.name for parameter in sig.parameters]
    body = bind(body, scope, set(names))
    mapping = hasattr(data, "items")
    entries = data.items() if mapping else data
    for entry in entries:
        values = entry[:1] if mapping and len(names) == 1 else entry
        if not mapping and len(names) == 1:
            values = (entry,)
        if not is_list(values) or len(values) != len(names):
            raise TypeError("foreach destructuring requires matching lengths")
        scope.bindings.update(zip(names, values))
        execute(body, scope)


foreach.meta = {"binds": 0}


def loop(body, *, scope):
    body = bind(body, scope)
    while True:
        execute(body, scope)


def map_values(first, second, *, scope):
    function, data = (first, second) if is_function(first) else (second, first)
    return [invoke(function, [value], scope) for value in data]


def filter_values(first, second, *, scope):
    function, data = (first, second) if is_function(first) else (second, first)
    return [value for value in data if invoke(function, [value], scope)]


def reduce_values(function, accumulator, data, *, scope):
    for value in data:
        accumulator = invoke(function, [accumulator, value], scope)
    return accumulator


def range_values(*args):
    return list(range(*args))


def keys(mapping):
    return list(mapping.keys())


def values(mapping):
    return list(mapping.values())


def items(mapping):
    return [list(pair) for pair in mapping.items()]


def zip_values(first, second):
    return [list(pair) for pair in zip(first, second)]


def contains(key, container):
    return key in container


def update(target, patch):
    target.update(patch)
    return target


def inherit(obj, prototype):
    if obj.parent is not None:
        raise ValueError("Inheritance may only be set once")
    obj.parent = prototype
    return obj


def is_a(obj, prototype):
    while isinstance(obj, Scope):
        if obj is prototype:
            return True
        obj = obj.parent
    return False


def with_values(obj, config, *, scope):
    if isinstance(config, Code):
        run_with(config, obj, scope=scope)
    else:
        obj.update(config)
    return obj


def create(prototype=None, config=None, *, scope):
    obj = Scope(parent=prototype)
    if config is not None:
        with_values(obj, config, scope=scope)
    return obj


def type_of(value):
    types = {
        int: "int", float: "float", bool: "boolean", str: "string",
        IString: "i-string", list: "list", dict: "dict", Scope: "scope",
        Code: "code", Sig: "sig", PathLiteral: "path", type(None): "none",
        bytes: "string", bytearray: "string",
    }
    name = "function" if is_function(value) else types.get(type(value))
    if name is None:
        if is_list(value):
            name = "list"
        elif isinstance(value, Scope):
            name = "scope"
        elif isinstance(value, Mapping):
            name = "dict"
        else:
            raise TypeError(f"Unknown SLIP type: {type(value).__name__}")
    return PathLiteral(Path([name]))


def to_str(value):
    if isinstance(value, (Code, Collection, Path, PathLiteral, Sig, Template)):
        from .slip_syntax import format_source
        return format_source(value)
    return value.decode("utf-8", errors="replace") \
        if isinstance(value, (bytes, bytearray)) else str(value)


def plain_data(value):
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Mapping):
        return {key: plain_data(item) for key, item in value.items()}
    if is_list(value):
        return [plain_data(item) for item in value]
    return value


def format_name(value):
    if isinstance(value, PathLiteral):
        path = value.path
        if (path.mode != "get" or path.options is not None
                or len(path.keys) != 1):
            return None
        value = path.keys[0]
    return str(value) if isinstance(value, str) else None


def serialize_value(format, value):
    name = format_name(format)
    if name not in ("json", "yaml", "toml"):
        raise ValueError(f"Unsupported serialization format: {format!r}")
    data = plain_data(value)
    if name == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if name == "yaml":
        return dumps(data)
    return toml.dumps(data)


def deserialize_value(format, value):
    decoders = {"json": (json.loads, loads), "yaml": (loads,),
                "toml": (toml.loads,)}
    name = format_name(format)
    if name not in decoders:
        raise ValueError(f"Unsupported serialization format: {format!r}")
    text = to_str(value)
    for decode in decoders[name]:
        try:
            return decode(text)
        except Exception:
            pass  # Preserve the reference's best-effort structured decoding.
    return text


def emit_value(topics, *messages, scope):
    if len(messages) == 2 and format_name(messages[0]) in (
        "json", "yaml", "toml",
    ):
        messages = (serialize_value(*messages),)
    return emit(topics, *messages, scope=scope)


def now():
    return time.time()


def to_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def to_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def logarithm(value):
    return math.log(value)


def find(text, needle, start=0):
    index = text.find(needle, start)
    return index if index >= 0 else None


def join(first, *rest):
    if isinstance(first, PathLiteral):
        paths = [first, *rest]
        if not all(isinstance(value, PathLiteral) for value in paths):
            raise TypeError("Path join requires path values")
        return PathLiteral(Path([
            key for value in paths for key in value.path.keys
        ]))
    if len(rest) != 1:
        raise TypeError("String join requires a list and separator")
    return rest[0].join(map(str, first))


def replace(source, old, new):
    if isinstance(source, str):
        return source.replace(old, new)
    result = copy.deepcopy(source)
    for index in range(len(result)):
        if result[index] == old[0]:
            result[index] = new[0]
    return result


def validate(data, schema, *, scope):
    def normalize(data, schema):
        if not isinstance(data, Mapping):
            raise TypeError("validate expects a mapping")
        chain, current = [], schema
        while isinstance(current, Scope):
            chain.append(current)
            current = current.parent
        fields = {}
        for current in reversed(chain):
            fields.update(current.bindings)
        output, errors = {}, []
        for name, spec in fields.items():
            marker = spec.get("__marker__") if isinstance(spec, dict) else None
            if name not in data:
                if marker == PathLiteral(Path(["default"])):
                    output[name] = spec["value"]
                elif marker != PathLiteral(Path(["optional"])):
                    errors.append({"field": name,
                                   "error": "field is required"})
                continue
            value = data[name]
            if marker == PathLiteral(Path(["optional"])):
                spec = spec["type"]
            if isinstance(spec, (Path, PathLiteral, Sig)):
                spec = resolve_type(spec, scope)
            if isinstance(spec, Scope) and is_a(spec, scope.root["Schema"]):
                if isinstance(value, Mapping):
                    output[name], nested = normalize(value, spec)
                    errors.extend(nested)
                else:
                    errors.append({"field": name, "error": "expected mapping"})
            elif (isinstance(spec, (PathLiteral, Sig))
                  and specificity(value, spec) is None):
                expected = to_str(spec)
                actual = to_str(type_of(value))
                errors.append({"field": name,
                               "error": f"expected type {expected}, "
                                        f"got {actual}"})
            else:
                output[name] = value
        return output, errors

    if not isinstance(schema, Scope):
        raise TypeError("validate expects a schema scope")
    output, errors = normalize(data, schema)
    if errors:
        fail(PathLiteral(Path(["invalid"])), errors)
    return output


def reference(path, *, scope):
    from .slip_syntax import to_path

    path = to_path(path).path
    if not isinstance(path, Path) or path.mode != "get":
        raise TypeError("ref expects a get-path")
    path = convert_path(path, scope, None)

    def read(caller):
        frame = Scope(parent=scope, caller=caller)
        frame.effects = caller.effects
        if path.keys and isinstance(path.keys[0], Locator):
            return resource_read(path, scope.root["get"], frame)
        return get_path(path.keys, frame)

    return Get(read)


def cell(inputs, body, *, scope):
    if not isinstance(inputs, Sig) or not isinstance(body, Code):
        raise TypeError("cell expects a signature and Code")
    if inputs.rest or any(not p.is_typed for p in inputs.parameters):
        raise TypeError("cell inputs require named values or paths")
    sources = {}
    for parameter in inputs.parameters:
        value = parameter.annotation if parameter.is_typed \
            else PathLiteral(Path([parameter.name]))
        sources[parameter.name] = reference(value, scope=scope) \
            if isinstance(value, (Path, PathLiteral)) else value
    code = bind(Code(body), scope, set(sources))

    def read(caller):
        frame = Scope({name: dereference(value, caller)
                       for name, value in sources.items()}, scope, caller)
        frame.effects = caller.effects
        return execute(code, frame)

    return Get(read)


def where(function, condition, *, scope):
    if (not isinstance(function, (Lambda, Generic))
            or not isinstance(condition, Code)):
        raise TypeError("where expects a function and Code")
    methods = function.methods if isinstance(function, Generic) else [function]
    for method in methods:
        names = {p.name for p in method.sig.parameters}
        if method.sig.rest:
            names.add(method.sig.rest)
        method.meta["guards"].append(condition)
        method.guards.append(bind(
            Code(condition), method.definition_scope, names,
        ))
    return function


def example(function, description):
    if (not isinstance(function, (Lambda, Generic))
            or not isinstance(description, Sig)):
        raise TypeError("example expects a function and a signature")
    function.meta.setdefault("examples", []).append(description)
    return function


def test_function(function, *, scope):
    methods = function.methods if isinstance(function, Generic) else [function]
    descriptions = list(function.meta.get("examples", []))
    if isinstance(function, Generic):
        for method in methods:
            descriptions.extend(method.meta.get("examples", []))

    def value(spec):
        if isinstance(spec, Path):
            return get_path(convert_path(spec, scope, None).keys, scope)
        if isinstance(spec, Code):
            return execute(spec, scope)
        return spec

    failures = []
    for index, description in enumerate(descriptions):
        try:
            args = [value(p.annotation) if p.is_typed
                    else value(Path([p.name])) for p in description.parameters]
            expected = value(description.return_annotation)
            actual = invoke(function, args, scope)
        except Exception as error:
            failures.append({"index": index, "err": str(error)})
            continue
        if actual != expected:
            failures.append({"index": index, "expected": expected,
                             "actual": actual})
    if failures:
        fail(PathLiteral(Path(["test-failed"])), failures)
    return len(descriptions)


def test_all(target=None, *, scope):
    target = scope if target is None else target
    bindings = target
    while isinstance(bindings, Scope):
        bindings = bindings.bindings
    functions = [(name, value) for name, value in bindings.items()
                 if isinstance(value, (Lambda, Generic))]
    summary = {"scanned": len(functions), "with-examples": 0,
               "passed": 0, "failed": 0, "details": []}
    for name, function in functions:
        methods = function.methods if isinstance(function, Generic) else []
        if not (function.meta.get("examples") or any(
            method.meta.get("examples") for method in methods
        )):
            continue
        summary["with-examples"] += 1
        try:
            test_function(function, scope=scope)
        except Failure as error:
            summary["details"].append({"name": name, "err": str(error)})
            summary["failed"] += 1
        else:
            summary["passed"] += 1
    if summary["failed"]:
        fail(PathLiteral(Path(["test-failed"])), summary)
    return summary


def function_value(path, *, scope):
    value = get_path(convert_path(path.path, scope, None).keys, scope)
    if not is_function(value):
        raise TypeError("Expected a function path")
    return value


def get_sig(function, *, scope=None):
    if isinstance(function, PathLiteral):
        function = function_value(function, scope=scope)
    method = function
    if isinstance(function, Generic):
        if len(function.methods) != 1:
            raise ValueError("get-sig requires exactly one method")
        method = function.methods[0]
    return sig(method.sig)


def public(function, *, scope):
    if isinstance(function, PathLiteral):
        function = function_value(function, scope=scope)
    if not isinstance(function, (Lambda, Generic)):
        raise TypeError("public expects a SLIP function")
    methods = function.methods if isinstance(function, Generic) else [function]
    result = Generic(list(methods), dict(function.meta))
    result.meta["public"] = True
    return result


def sig(value):
    def annotation(value):
        if isinstance(value, Scope):
            return value
        return sig(value) if isinstance(value, Sig) else copy.deepcopy(value)

    if isinstance(value, Sig):
        return Sig([
            Parameter(p.name, annotation(p.annotation), p.is_typed)
            for p in value.parameters
        ], value.rest, copy.deepcopy(value.where),
            annotation(value.return_annotation), value.logic,
            [annotation(item) for item in value.types])
    return Sig([
        Parameter(item["name"], item.get("type"), "type" in item)
        for item in value["parameters"]
    ], value.get("rest"), value.get("where"),
        value.get("return-annotation", value.get("return_annotation")))


def get_body(function, signature, *, scope):
    signature = Sig([
        Parameter(p.name, resolve_type(p.annotation, scope), p.is_typed)
        for p in signature.parameters
    ], signature.rest, signature.where, signature.return_annotation)
    methods = function.methods if isinstance(function, Generic) else [function]
    for method in methods:
        if method.sig == signature:
            return method.body
    raise LookupError("No matching method")


def list_values(code, *, scope):
    return make_list(bind(code, scope), scope)


def dict_values(code, *, scope):
    return make_dict(bind(code, scope), scope)


def print_value(*messages, scope):
    return emit_value("stdout", *messages, scope=scope)


def stderr_value(*messages, scope):
    return emit_value("stderr", *messages, scope=scope)


def seed_random(seed, *, scope):
    scope.root.random.seed(seed)


def random_value(*, scope):
    return scope.root.random.random()


def random_int(start, end, *, scope):
    return scope.root.random.randint(start, end)


def task(code, *, scope):
    raise NotImplementedError("task is unsupported by synchronous SLIP")


def sleep(seconds):
    raise NotImplementedError("sleep is unsupported by synchronous SLIP")


def library_scope():
    from .slip_syntax import to_path

    scope = language_scope()
    scope.random = random.Random()
    scope.bindings.update({
        "add": add, "extract-simple-param": extract_simple_param,
        "foreach": foreach, "loop": loop, "map": map_values,
        "filter": filter_values, "reduce": reduce_values,
        "range": range_values, "sort": sorted, "reverse": lambda x: x[::-1],
        "zip": zip_values, "keys": keys, "values": values, "items": items,
        "has": operator.contains, "core-has": operator.contains,
        "contains": contains, "core-contains": contains,
        "in": Pipe(contains), "update": update,
        "copy": copy.copy, "clone": copy.deepcopy,
        "inherit": inherit, "is-a": is_a, "create": create,
        "with": with_values, "type-of": type_of, "to-str": to_str,
        "to": serialize_value, "from": deserialize_value, "emit": emit_value,
        "get-sig": get_sig, "sig": sig, "get-body": get_body,
        "validate": validate, "ref": reference, "cell": cell,
        "where": where, "example": example, "test": test_function,
        "test-all": test_all,
        "public": public,
        "core-function": function_value,
        "to-path": to_path,
        "list": list_values, "dict": dict_values,
        "print": print_value, "stderr": stderr_value,
        "sleep": sleep, "task": task, "time": now,
        "seed-random": seed_random, "random": random_value,
        "random-int": random_int,
        "join": join,
        "split": str.split, "replace": replace, "find": find,
        "dedent": textwrap.dedent,
        "indent": textwrap.indent,
        "abs": abs, "floor": math.floor, "ceil": math.ceil,
        "core-abs": abs, "core-len": len, "core-not": operator.not_,
        "core-neq": operator.ne, "core-gte": operator.ge,
        "core-lte": operator.le,
        "trunc": math.trunc, "round": round, "sqrt": math.sqrt,
        "exp": math.exp, "log": logarithm, "log10": math.log10,
        "to-int": to_int, "to-float": to_float,
        "str-join": join, "str-replace": str.replace,
    })
    return scope
