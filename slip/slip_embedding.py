"""The Python boundary over native containers and the independent evaluator."""

import inspect
from collections.abc import Mapping, MutableMapping, MutableSequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from .slip_core import (
    Failure, Locator, PathLiteral, Return, Scope,
    convert_path, error_details, execute, get_path, invoke, is_list,
)
from .slip_jobs import job_result
from .slip_library import SOURCE, library_scope
from .slip_resources import Resources
from .slip_syntax import attach_source, parse, to_path


@dataclass
class ExecutionResult:
    status: str
    value: object = None
    error: dict | None = None
    side_effects: list = field(default_factory=list)
    error_token: dict | None = None

    @property
    def error_message(self):
        return self.error["message"] if self.error is not None else None

    @property
    def slip_result(self):
        return self.value


class SLIPHost:
    """Base for application-owned hosts; runners borrow injected instances."""


def slip_api_method(function):
    function._slip_api_method = True
    return function


class LiveMapping(MutableMapping):
    """Read the current container at a saved host location."""

    def __init__(self, read, scope, hide_marker=False):
        self.read, self.scope = read, scope
        self.hide_marker = hide_marker

    def __getitem__(self, key):
        if self.hide_marker and key == "__slip__":
            raise KeyError(key)
        return host_value(
            self.read()[key], partial(member, self.read, key), self.scope,
        )

    def __setitem__(self, key, value):
        if self.hide_marker and key == "__slip__":
            raise KeyError(key)
        self.read()[key] = value

    def __delitem__(self, key):
        if self.hide_marker and key == "__slip__":
            raise KeyError(key)
        del self.read()[key]

    def __iter__(self):
        return (key for key in self.read()
                if not self.hide_marker or key != "__slip__")

    def __len__(self):
        data = self.read()
        return len(data) - (self.hide_marker and "__slip__" in data)

    def __contains__(self, key):
        return (not self.hide_marker or key != "__slip__") \
            and key in self.read()


class LiveSequence(MutableSequence):
    def __init__(self, read, scope):
        self.read, self.scope = read, scope

    def __getitem__(self, key):
        data = self.read()
        if isinstance(key, slice):
            return [host_value(
                data[index], partial(member, self.read, index), self.scope,
            ) for index in range(*key.indices(len(data)))]
        return host_value(
            data[key], partial(member, self.read, key), self.scope,
        )

    def __setitem__(self, key, value):
        self.read()[key] = value

    def __delitem__(self, key):
        del self.read()[key]

    def __len__(self):
        return len(self.read())

    def __iter__(self):
        for index, value in enumerate(self.read()):
            yield host_value(
                value, partial(member, self.read, index), self.scope,
            )

    def insert(self, index, value):
        self.read().insert(index, value)


class LiveScope(Scope):
    def __init__(self, read, scope, metadata):
        super().__init__(parent=prototype(metadata, scope))
        self.bindings = LiveMapping(read, scope, hide_marker=True)

    @Scope.parent.getter
    def parent(self):
        metadata = scope_metadata(self.bindings.read())
        self.meta["parent"] = prototype(metadata, self.bindings.scope)
        return self.meta["parent"]

    def __getitem__(self, key):
        if key == "meta":
            self.meta["parent"] = self.parent
        return super().__getitem__(key)


def member(read, key):
    return read()[key]


def scope_metadata(value):
    if not isinstance(value, Mapping) or "__slip__" not in value:
        return None
    metadata = value["__slip__"]
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise ValueError("__slip__ metadata must be a mapping")
    if metadata.get("version", 1) != 1:
        raise ValueError("Unsupported __slip__ version")
    if metadata.get("type") != "scope":
        raise ValueError("Unsupported __slip__ type")
    return metadata


def prototype(metadata, scope):
    name = metadata.get("prototype") if metadata is not None else None
    if name is None:
        return None
    if not isinstance(name, str) or not name:
        raise TypeError("Expected a prototype name")
    try:
        result = scope[name]
    except KeyError:
        result = Scope()
        scope.root[name] = result
    if not isinstance(result, Scope):
        raise TypeError(f"Expected scope prototype: {name}")
    return result


def host_value(value, read, scope):
    if isinstance(value, Scope):
        return value
    if isinstance(value, Mapping):
        metadata = scope_metadata(value)
        if metadata is not None:
            return LiveScope(read, scope, metadata)
        return LiveMapping(read, scope)
    if is_list(value):
        return LiveSequence(read, scope)
    return value


def as_slip(value, *, scope):
    memo = {}

    def convert(node):
        mapping = isinstance(node, Mapping)
        if isinstance(node, Scope) or not (mapping or is_list(node)):
            return node
        uid = getattr(node, "uid", None)
        key = (type(node), uid) if uid is not None else id(node)
        if key in memo:
            return memo[key][1]
        metadata = scope_metadata(node) if mapping else None
        if mapping:
            result = Scope(parent=prototype(metadata, scope)) \
                if metadata is not None else {}
        else:
            result = []
        memo[key] = node, result
        if mapping:
            for name, item in node.items():
                if metadata is None or name != "__slip__":
                    result[name] = convert(item)
        else:
            result.extend(convert(item) for item in node)
        return result

    return convert(value)


def missing_host_data(object_id):
    raise RuntimeError("host-data is not configured")


class ScriptRunner:
    def __init__(self, host_object=None, host_data=None, *, http_client=None,
                 background_io=True):
        self.root_scope = library_scope()
        self.scope = Scope(parent=self.root_scope)
        self.host_data = (
            host_data if host_data is not None else missing_host_data
        )
        host_methods = {}
        if host_object is not None:
            for name, member in inspect.getmembers(type(host_object)):
                if getattr(member, "_slip_api_method", False):
                    host_methods[name.replace("_", "-")] = getattr(
                        host_object, name,
                    )
        self.library = parse(SOURCE)
        attach_source(self.library, SOURCE, "<stdlib>")
        self.root_scope.meta["source_path"] = "<stdlib>"
        self.resources = Resources(self.root_scope, http_client,
                                   background_io=background_io)
        self.root_scope.bindings.update({
            "host-data": self.host_data, "host-object": self.host_object,
            "as-slip": as_slip,
            "resource": self.resources.resource, "get": self.resources.get,
            "put": self.resources.put, "del": self.resources.delete,
            "post": self.resources.post,
            "import": self.resources.import_module,
            "submit": self.submit, "job-done": Future.done,
            "job-result": job_result,
        })
        self.root_scope.bindings.update(host_methods)
        self.loaded = False
        self.closed = False

    @property
    def source_dir(self):
        return self.resources.source_dir

    @source_dir.setter
    def source_dir(self, directory):
        self.resources.source_dir = directory

    def host_object(self, object_id, *, scope):
        self.resources.check_host_thread()
        if isinstance(object_id, (Scope, LiveMapping, LiveSequence)):
            return object_id
        value = invoke(self.host_data, [object_id], scope)
        return host_value(value, lambda: value, scope)

    def handle_script(self, source, *, source_path=None):
        def run(frame):
            code = parse(source)
            if source_path is not None:
                attach_source(code, source, str(source_path))
            return execute(code, frame)

        return self._run(run, source_path=source_path)

    def _run(self, operation, *, source_path=None):
        self.resources.check_host_thread()
        if self.closed:
            raise RuntimeError("ScriptRunner is closed")
        frame = Scope(parent=self.root_scope)
        frame.bindings = self.scope
        frame.effects = []
        frame.meta["source_dir"] = str(Path(source_path).resolve().parent
                                       if source_path is not None
                                       else self.source_dir or Path.cwd())
        frame.meta["source_path"] = str(source_path) \
            if source_path is not None else "<script>"
        try:
            if not self.loaded:
                execute(self.library, self.root_scope)
                self.loaded = True
            value = operation(frame)
        except Return as returned:
            value = returned.value
        except Exception as error:
            details = error_details(error)
            if not isinstance(error, Failure):
                details["message"] = format_error(error)
                frame.effects.append({"topics": ["stderr"],
                                      "message": details["message"]})
            details.setdefault("trace", list(getattr(error, "slip_trace", [])))
            return ExecutionResult("err", error=details,
                                   side_effects=list(frame.effects),
                                   error_token=getattr(
                                       error, "error_token", None,
                                   ))
        return ExecutionResult("ok", value, side_effects=list(frame.effects))

    def import_public_module(self, target):
        from .slip_public import PublicModule

        self.resources.check_host_thread()
        if self.closed:
            raise RuntimeError("ScriptRunner is closed")
        if not self.loaded:
            execute(self.library, self.root_scope)
            self.loaded = True
        frame = Scope(parent=self.root_scope)
        frame.bindings = self.scope
        frame.effects = []
        frame.meta["source_dir"] = str(self.source_dir or Path.cwd())
        exports = self.resources.import_module(target, scope=frame)
        return PublicModule(self, exports)

    def submit(self, operation, args=(), *, scope=None):
        self.resources.check_host_thread()
        if self.closed:
            raise RuntimeError("ScriptRunner is closed")
        if self.resources.worker is None:
            raise RuntimeError(
                "Background I/O is disabled (background_io=False)",
            )
        scope = self.scope if scope is None else scope
        if isinstance(operation, str):
            operation = to_path(operation)
        if isinstance(operation, PathLiteral):
            path = operation.path
            if path.keys and isinstance(path.keys[0], Locator):
                return self.resources.submit(path, args, scope=scope)
            if path.mode != "get":
                raise TypeError("Expected an async function get-path")
            operation = get_path(convert_path(path, scope, None).keys, scope)
        return self.resources.worker.submit(operation, *args)

    def close(self):
        self.resources.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()


def format_error(error):
    prefix = "" if isinstance(error, SyntaxError) \
        else type(error).__name__ + ": "
    message = prefix + str(error)
    trace = getattr(error, "slip_trace", [])
    if trace:
        first = trace[0]
        message += f"\nin line {first.get('line', '?')} of {first['file']}"
        if first["source"]:
            message += "\n" + first["source"]
            message += "\n" + " " * max(0, first.get("col", 1) - 1) + "^"
        message += "\nSLIP stacktrace:"
        for entry in reversed(trace):
            message += f"\n  {entry['file']}:{entry.get('line', '?')} "
            message += entry.get("text", "")
    return message
