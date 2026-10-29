"""External I/O and module loading through native functions and Scopes."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import toml
import xmltodict
from safer_yaml import dump, dumps, load, loads

from .slip_cache import load_code
from .slip_core import (
    Code, Failure, Path as SlipPath, PathLiteral, Return, Scope,
    bind, execute, make_dict,
)
from .slip_library import plain_data
from .slip_jobs import IOWorker
from .slip_syntax import format_source, parse


@dataclass
class Resource:
    locator: str
    options: dict = field(default_factory=dict)


class Resources:
    def __init__(self, root_scope, http_client=None, *, background_io=True):
        if (http_client is not None
                and not isinstance(http_client, httpx.Client)):
            raise TypeError("Synchronous SLIP requires an httpx.Client")
        self.root_scope = root_scope
        self.source_dir = None
        self.modules = {}
        self.closed = False
        self.http_client = http_client
        self.owns_http_client = http_client is None
        self.worker = IOWorker() if background_io else None
        if self.owns_http_client:
            self.http_client = self.worker.client if self.worker is not None \
                else httpx.Client(follow_redirects=True)

    def check_host_thread(self):
        if self.worker is not None:
            self.worker.check_host_thread()

    def path(self, locator, scope):
        if not locator.startswith("file://"):
            raise ValueError(f"Unsupported resource locator: {locator}")
        path = Path(locator[7:] or ".").expanduser()
        if not path.is_absolute():
            directory = (
                scope.meta.get("source_dir") or self.source_dir or Path.cwd()
            )
            path = Path(directory) / path
        return path.resolve()

    def resource(self, target, *, scope):
        self.check_host_thread()
        if isinstance(target, Resource):
            return target
        options = {}
        if isinstance(target, PathLiteral):
            path = target.path
            if len(path.keys) != 1:
                raise ValueError("Expected one resource locator")
            if path.options is not None:
                options = make_dict(bind(path.options, scope), scope)
            target = path.keys[0]
        if not isinstance(target, str):
            raise TypeError("Expected a resource locator")
        if target.startswith(("http://", "https://")):
            return Resource(str(target), options)
        return Resource("file://" + str(self.path(target, scope)), options)

    def get(self, target, options=None, *, scope):
        resource = self.resource(target, scope=scope)
        config = {**resource.options, **(options or {})}
        if resource.locator.startswith(("http://", "https://")):
            return self.request("GET", resource.locator, config)
        path = self.path(resource.locator, scope)
        return read_file(path, config)

    def put(self, target, value, options=None, *, scope):
        resource = self.resource(target, scope=scope)
        config = {**resource.options, **(options or {})}
        if resource.locator.startswith(("http://", "https://")):
            return self.request("PUT", resource.locator, config, value)
        write_file(self.path(resource.locator, scope), value, config)

    def delete(self, target, options=None, *, scope):
        resource = self.resource(target, scope=scope)
        if resource.locator.startswith(("http://", "https://")):
            config = {**resource.options, **(options or {})}
            return self.request("DELETE", resource.locator, config)
        path = self.path(resource.locator, scope)
        path.unlink(missing_ok=True)

    def post(self, target, value, options=None, *, scope):
        resource = self.resource(target, scope=scope)
        if not resource.locator.startswith(("http://", "https://")):
            raise TypeError("POST requires an HTTP resource")
        config = {**resource.options, **(options or {})}
        return self.request("POST", resource.locator, config, value)

    def request(self, method, url, config, value=None):
        self.check_host_thread()
        if self.closed:
            raise RuntimeError("Resources are closed")
        prepared = prepare_http(method, config, value)
        if self.owns_http_client and self.worker is not None:
            return self.worker.submit(
                request_http, self.http_client, method, url, *prepared,
            ).result()
        options, mode, retries, backoff = prepared
        for attempt in range(retries + 1):
            try:
                response = self.http_client.request(
                    method, url, **options,
                )
                result = decode_http(response)
            except Exception as error:
                if attempt == retries:
                    raise http_failure(str(error), url, method) from error
                time.sleep(backoff * (2 ** attempt))
                continue
            break
        return http_result(response, result, url, method, mode)

    def submit(self, path, args, *, scope):
        self.check_host_thread()
        if self.closed:
            raise RuntimeError("Resources are closed")
        if self.worker is None:
            raise RuntimeError(
                "Background I/O is disabled (background_io=False)",
            )
        if not self.owns_http_client:
            raise TypeError(
                "Background HTTP requires the Runner-owned async client",
            )
        if len(path.keys) != 1:
            raise ValueError(
                "Background HTTP requires a locator without a query",
            )
        resource = self.resource(PathLiteral(path), scope=scope)
        if not resource.locator.startswith(("http://", "https://")):
            raise TypeError("Background resources currently support HTTP only")
        methods = {"get": "GET", "set": "PUT", "post": "POST",
                   "del": "DELETE"}
        if path.mode not in methods:
            raise TypeError("Expected a resource get/set/post/delete path")
        method = methods[path.mode]
        count = int(method in ("PUT", "POST"))
        if len(args) != count:
            raise TypeError(f"Background {method} requires {count} arguments")
        prepared = prepare_http(
            method, resource.options, args[0] if args else None,
        )
        return self.worker.submit(
            request_http, self.http_client, method, resource.locator,
            *prepared,
        )

    def import_module(self, target, *, scope):
        self.check_host_thread()
        if self.closed:
            raise RuntimeError("Resources are closed")
        if isinstance(target, Code):
            source_path = target.source_path
            key = source_path or ("code", id(target))
        else:
            target = self.resource(target, scope=scope)
            source_path = str(self.path(target.locator, scope)) \
                if target.locator.startswith("file://") else None
            key = source_path or target.locator
        ancestry = scope.meta.get("imports", ())
        if key in ancestry:
            raise RuntimeError(f"circular import: {key}")
        if key not in self.modules:
            exports = self.load_module(
                target, source_path, (*ancestry, key), scope,
            )
            self.modules[key] = target, exports
        _, exports = self.modules[key]
        return Scope(parent=exports)

    def load_module(self, target, source_path, ancestry, caller):
        self.check_host_thread()
        code = target if isinstance(target, Code) \
            else self.get(target, scope=caller)
        if source_path is None and isinstance(code, str):
            code = parse(code)
        if not isinstance(code, Code):
            raise TypeError("A module must contain SLIP Code")
        exports = Scope()
        frame = Scope(parent=self.root_scope, caller=caller)
        frame.bindings = exports
        frame.effects = caller.effects
        frame.meta["imports"] = ancestry
        frame.meta["source_path"] = source_path or getattr(
            target, "locator", "<module>",
        )
        frame.meta["source_dir"] = (
            str(Path(source_path).parent) if source_path
            else caller.meta.get("source_dir", self.source_dir)
        )
        try:
            execute(Code(code), frame)
        except Return:
            pass
        return exports

    def close(self):
        if self.worker is not None:
            self.worker.close()
        elif self.owns_http_client:
            self.http_client.close()
        self.closed = True


def prepare_http(method, config, value):
    mode = response_mode(config)
    retries = int(config.get("retries", 2))
    backoff = float(config.get("backoff", 0.2))
    if retries < 0 or backoff < 0:
        raise ValueError("HTTP retries and backoff must be non-negative")
    headers = httpx.Headers(config.get("headers", {}))
    content_type = config.get("content-type") or config.get("content_type")
    if content_type and method != "GET":
        headers["Content-Type"] = content_type
    body = None
    if method in ("PUT", "POST"):
        body = encode_http(value, content_type)
        headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    options = {"headers": headers,
               "params": httpx.QueryParams(config.get("params", {})),
               "content": body}
    if "timeout" in config:
        options["timeout"] = float(config["timeout"])
    return options, mode, retries, backoff


async def request_http(client, method, url, options, mode, retries, backoff):
    for attempt in range(retries + 1):
        try:
            response = await client.request(method, url, **options)
            result = decode_http(response)
        except Exception as error:
            if attempt == retries:
                raise http_failure(str(error), url, method) from error
            await asyncio.sleep(backoff * (2 ** attempt))
            continue
        break
    return http_result(response, result, url, method, mode)


def http_result(response, result, url, method, mode):
    headers = dict(response.headers.items())
    if mode == "full":
        return {"status": response.status_code, "value": result,
                "meta": {"headers": headers}}
    if not 200 <= response.status_code < 300:
        raise http_failure(
            f"HTTP {response.status_code} for {url}", url, method,
            status=response.status_code, data=result, headers=headers,
        )
    return result


def response_mode(config):
    if "full" in config or "lite" in config:
        raise ValueError(
            "Use response-mode: `full`, not legacy response flags",
        )
    mode = config.get("response-mode")
    if mode is None:
        return None
    if isinstance(mode, PathLiteral):
        mode = mode.path
    if (isinstance(mode, SlipPath) and mode.mode == "get"
            and len(mode.keys) == 1):
        mode = mode.keys[0]
    if isinstance(mode, str) and mode.strip().strip("`").lower() == "full":
        return "full"
    raise ValueError("HTTP response-mode only supports `full`")


def media_format(content_type):
    content_type = (content_type or "").lower()
    for name in ("json", "yaml", "toml", "xml"):
        if name in content_type:
            return name
    return "xml" if "html" in content_type else None


def decode_http(response):
    text = response.text
    format = media_format(response.headers.get("Content-Type"))
    if format is None:
        prefix = text.lstrip()[:1]
        format = "json" if prefix in ("{", "[") else \
            "xml" if prefix == "<" else None
    decoders = {"json": (json.loads, loads), "yaml": (loads,),
                "toml": (toml.loads,), "xml": (xmltodict.parse,)}
    for decode in decoders.get(format, ()):
        try:
            return decode(text)
        except Exception:
            # The reference's best-effort wire decoding falls back to text.
            pass
    return text


def encode_http(value, content_type):
    format = media_format(content_type)
    if format is None:
        if isinstance(value, bytearray):
            return bytes(value)
        return value if isinstance(value, (str, bytes)) \
            else str(value)
    try:
        data = plain_data(value)
        if format == "json":
            return json.dumps(data, ensure_ascii=False, indent=2)
        if format == "yaml":
            return dumps(data)
        if format == "toml":
            return toml.dumps(data)
        if isinstance(data, list):
            data = {"root": {"item": data}}
        elif not isinstance(data, dict):
            data = {"root": data}
        return xmltodict.unparse(data, pretty=True)
    except Exception:
        # Preserve the existing structured-payload text fallback explicitly.
        return str(value)


def http_failure(message, url, method, *, status=None, data=None,
                 headers=None):
    meta = {"url": url, "method": method}
    if headers is not None:
        meta["headers"] = headers
    return Failure({
        "kind": PathLiteral(SlipPath(["protocol"])),
        "code": PathLiteral(SlipPath(["http-error"])),
        "message": message, "data": data,
        "protocol": PathLiteral(SlipPath(["http"])),
        "protocol-status": status, "meta": meta,
    })


def read_file(path, config):
    if path.is_dir():
        return {child.name: child.read_bytes() for child in path.iterdir()
                if child.is_file()}
    encoding = config.get("encoding")
    if encoding:
        return path.read_text(encoding=encoding)
    suffix = path.suffix.lower()
    if suffix == ".slip":
        return load_code(path)
    if suffix in (".yaml", ".yml"):
        return load(path)
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix == ".toml":
        return toml.loads(text)
    return text


def write_file(path, value, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray)):
        path.write_bytes(value)
        return
    encoding = config.get("encoding")
    if encoding:
        path.write_text(str(value), encoding=encoding)
        return
    formats = {
        "application/json": ".json", "application/yaml": ".yaml",
        "application/x-yaml": ".yaml", "text/yaml": ".yaml",
        "application/toml": ".toml",
    }
    content_type = config.get("content-type", config.get("content_type"))
    suffix = formats.get(content_type, path.suffix.lower())
    if suffix in (".yaml", ".yml"):
        dump(value, path)
        return
    if suffix == ".json":
        text = json.dumps(value, indent=2)
    elif suffix == ".toml":
        text = toml.dumps(value)
    elif suffix == ".slip":
        text = format_source(value) + "\n"
    else:
        text = str(value)
    path.write_text(text, encoding="utf-8")
