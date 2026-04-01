# slip_runtime.py

import re
import asyncio
import inspect
import math
import time
import random
import copy
import textwrap
import collections.abc
import traceback
from collections import UserDict
from pathlib import Path
from typing import Any, List, Optional, Literal, Dict
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from koine import Parser
from slip.slip_transformer import SlipTransformer
from slip.slip_interpreter import Evaluator
from slip.slip_datatypes import (
    Scope,
    Code,
    Response,
    PathLiteral,
    Name,
    SetPath,
    GetPath,
    PathNotFound,
    Group,
    List as SlipList,
    ReturnSignal,
)

# Canonical PathLiteral status singletons (use these everywhere)
_OK_STATUS = PathLiteral(GetPath([Name("ok")]))
_ERR_STATUS = PathLiteral(GetPath([Name("err")]))

# ===================================================================
# 1. Core Data Structures & Global State
# ===================================================================


class SlipDict(UserDict):
    """A dictionary-like wrapper that supports weak references, enabling prototypal inheritance."""

    # Make SlipDicts hashable by identity, allowing them to be dict keys for prototyping.
    # This changes equality for SLIP dicts to be identity-based, like in JavaScript.
    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        # Enforce identity-based equality when comparing with another SlipDict.
        if isinstance(other, SlipDict):
            return self is other
        # For comparison with other dict-like objects, delegate to UserDict's
        # value-based comparison, which compares its internal `data` dict.
        return super().__eq__(other)

    def __repr__(self):
        from slip.slip_printer import Printer

        return Printer().pformat(self)

    def __getattr__(self, name: str):
        d = self.data
        if name in d:
            return d[name]
        raise AttributeError(name)


# Backward-compatibility alias
SlipObject = SlipDict


def slip_api_method(func):
    """A decorator to explicitly mark methods as safe for SLIP execution."""
    func._is_slip_api = True
    return func


class SLIPHost(ABC):
    """The required base class for any Python object exposed to the SLIP interpreter."""

    def __init__(self):
        self.active_slip_tasks: set = set()

    @abstractmethod
    def __getitem__(self, key):
        raise NotImplementedError

    @abstractmethod
    def __setitem__(self, key, value):
        raise NotImplementedError

    @abstractmethod
    def __delitem__(self, key):
        raise NotImplementedError

    @slip_api_method
    def cancel_tasks(self):
        count = len(self.active_slip_tasks)
        for task in list(self.active_slip_tasks):
            task.cancel()
        self.active_slip_tasks.clear()
        return count

    def _register_task(self, task: asyncio.Task):
        self.active_slip_tasks.add(task)

        def _done_cb(t: asyncio.Task):
            try:
                self.active_slip_tasks.discard(t)
            except Exception:
                pass

        task.add_done_callback(_done_cb)


class _EffectsView(collections.abc.Sequence):
    __slots__ = ("_backing", "_start", "_end")

    def __init__(self, backing, start, end):
        self._backing = backing
        self._start = int(start)
        self._end = int(end)

    def __len__(self):
        end = self._end
        start = self._start
        if end < start:
            return 0
        return end - start

    def __getitem__(self, idx):
        n = len(self)
        if isinstance(idx, slice):
            s_start, s_stop, s_step = idx.indices(n)
            base = self._start
            return [self._backing[base + k] for k in range(s_start, s_stop, s_step)]
        if idx < 0:
            idx += n
        if idx < 0 or idx >= n:
            raise IndexError
        return self._backing[self._start + idx]

    def __iter__(self):
        base = self._start
        for k in range(len(self)):
            yield self._backing[base + k]

    def __repr__(self):
        # Avoid going through list(self) to prevent accidental re-entrancy
        return repr(self._backing[self._start : self._end])


class _ResponseView:
    def __init__(self, evaluator):
        self._ev = evaluator

    @property
    def status(self):
        out = getattr(self._ev, "outcome", None)
        if out is None:
            return None
        return getattr(out, "status", None)

    @property
    def value(self):
        out = getattr(self._ev, "outcome", None)
        if out is None:
            return None
        return getattr(out, "value", None)

    @property
    def effects(self):
        # Always present; prefer outcome.effects if set, else fallback to evaluator.side_effects
        out = getattr(self._ev, "outcome", None)
        if out is not None and getattr(out, "effects", None) is not None:
            return out.effects
        return getattr(self._ev, "side_effects", [])

    @property
    def stacktrace(self):
        out = getattr(self._ev, "outcome", None)
        if out is None:
            return []
        return getattr(out, "stacktrace", []) or []


# ===================================================================
# 4. The Standard Library
# ===================================================================
class StdLib:
    """Contains Python implementations for all SLIP built-ins."""

    def __init__(self, evaluator):
        self.evaluator = evaluator
        # Provide a fallback core scope for bare Evaluator usage (outside ScriptRunner).
        # This binds stdlib functions into evaluator.core_scope so operators like '+'
        # resolve inside SlipFunction bodies in tests that construct StdLib(ev) directly.
        try:
            core = getattr(evaluator, "core_scope", None)
            if core is None:
                core = Scope()
                for name, member in inspect.getmembers(self):
                    if (
                        name.startswith("_")
                        and not name.startswith("__")
                        and callable(member)
                    ):
                        slip_name = name[1:].replace("_", "-")
                        core[slip_name] = member
                        # Also provide stable core- aliases
                        core[f"core-{slip_name}"] = member
                        # Expose predicate '-q' aliases as '?'
                        if slip_name.endswith("-q"):
                            q_alias = slip_name[:-2] + "?"
                            core[q_alias] = member
                            core[f"core-{q_alias}"] = member
                evaluator.core_scope = core
        except Exception:
            # Best-effort only; ScriptRunner will bind full root scope separately.
            pass

        # Bootstrap: ensure root.slip is evaluated into evaluator.core_scope so operator
        # aliases like '+' and '*' exist in bare Evaluator contexts (and for any code
        # that relies on evaluator.core_scope as a root environment).
        try:
            core = getattr(evaluator, "core_scope", None)
            if isinstance(core, Scope) and not bool(core.meta.get("_root_loaded")):
                # StdLib.__init__ is synchronous; ensure bootstrap happens deterministically.
                # If we're already inside a running event loop, we defer and rely on the
                # evaluator's own lazy loader to complete before evaluation.
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        return
                except Exception:
                    loop = None

                try:
                    asyncio.run(evaluator._ensure_core_loaded())
                except RuntimeError:
                    # If asyncio.run() is unavailable due to an active loop, defer.
                    pass
        except Exception:
            pass

    # --- Math and Logic ---
    def _add(self, a, b):
        # List-friendly addition with in-place mutation to support idioms like:
        # foreach {k} dict [ seen + k ]  -- mutates 'seen' list without assignment
        if isinstance(a, list):
            if isinstance(b, list):
                a.extend(b)
                return a
            a.append(b)
            return a
        return a + b

    def _sub(self, a, b):
        return a - b

    def _mul(self, a, b):
        return a * b

    def _div(self, a, b):
        return a / b

    def _pow(self, b, e):
        return b**e

    def _eq(self, a, b):
        res = a == b
        try:
            self.evaluator._dbg(
                "EQ", type(a).__name__, id(a), "==", type(b).__name__, id(b), "->", res
            )
        except Exception:
            pass
        return res

    def _neq(self, a, b):
        return a != b

    def _gt(self, a, b):
        return a > b

    def _gte(self, a, b):
        return a >= b

    def _lt(self, a, b):
        return a < b

    def _lte(self, a, b):
        return a <= b

    def _not(self, x):
        return not x

    def _exp(self, x):
        return math.exp(x)

    def _log(self, x):
        return math.log(x)

    def _log10(self, x):
        return math.log10(x)

    # --- String Utilities ---
    def _str_join(self, list_of_strings, separator):
        return separator.join(map(str, list_of_strings))

    # Backward compatibility for legacy callers/tests
    def _join(self, list_of_strings, separator):
        return self._str_join(list_of_strings, separator)

    async def _join_paths(self, first, *rest, scope: Scope):
        from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP

        # Accept either varargs (first, *rest) or a single list of path-like values
        all_args = (
            tuple(first) if isinstance(first, list) and not rest else (first,) + rest
        )
        segments = []
        for a in all_args:
            gp = self._to_getpath(a)
            if not isinstance(gp, _GP):
                raise TypeError("join on paths expects only path-like arguments")
            segments.extend(gp.segments)
        return _PL(_GP(segments))

    def _split(self, string, separator):
        return string.split(separator)

    def _find(self, haystack, needle, start=0):
        idx = haystack.find(needle, start)
        return idx if idx != -1 else None

    def _str_replace(self, string, old, new):
        return string.replace(old, new)

    # Back-compat for tests expecting _replace
    # def _replace(self, string, old, new): return self._str_replace(string, old, new)
    def _indent(self, string, prefix):
        return textwrap.indent(string, prefix)

    def _dedent(self, string):
        return textwrap.dedent(string)

    def _to_getpath(self, value):
        from slip.slip_datatypes import (
            PathLiteral as _PL,
            GetPath as _GP,
            Name as _Name,
            IString as _IStr,
        )

        # PathLiteral → inner (must be GetPath)
        if isinstance(value, _PL):
            inner = getattr(value, "inner", None)
            if isinstance(inner, _GP):
                return inner
            raise TypeError(
                "call expects a function path (get-path) when using a path-literal"
            )
        # Already a runtime GetPath (not accepted by call per spec, but used by helpers)
        if isinstance(value, _GP):
            return value
        # Strings → parse to GetPath (split on '.' and '/', but keep URL/special as one segment)
        if isinstance(value, (str, _IStr)):
            s = str(value).strip()
            if not s:
                raise ValueError("empty path string")
            if ("://" in s) or s.startswith(("/", "../", "./", "|", "~")):
                return _GP([_Name(s)])
            import re as _re

            parts = [p for p in _re.split(r"[./]", s) if p]
            if not parts:
                raise ValueError("invalid path string")
            return _GP([_Name(p) for p in parts])
        raise TypeError("expected a path-literal, get-path, or string")

    def _ref(self, p, *, scope: Scope):
        """Create a read-only reference to a get-path literal.

        Reading the Ref yields the current value at that path; there is no write-through.
        """
        from slip.slip_datatypes import Ref as _Ref, PathLiteral as _PL, GetPath as _GP

        if isinstance(p, _PL):
            inner = getattr(p, "inner", None)
            if not isinstance(inner, _GP):
                raise TypeError("ref expects a get-path literal")
            return _Ref(inner)
        if isinstance(p, _GP):
            return _Ref(p)
        raise TypeError("ref expects a get-path literal")

    def _cell(self, inputs, body: Code, *, scope: Scope):
        """Create a pure derived value (cell).

        Syntax:
          cell {x: <ref-or-path>, y: <ref-or-path>} [ ... ]

        `inputs` is a Sig literal; its typed keyword values are stored unevaluated and
        dereferenced when the cell is read.
        """
        from slip.slip_datatypes import Cell as _Cell, Sig as _Sig

        if not isinstance(inputs, _Sig):
            raise TypeError("cell expects a sig literal for inputs, e.g. {x: `a.b`}")
        if not isinstance(body, Code):
            raise TypeError("cell expects a code block")
        # Only typed keywords are meaningful for inputs; positional/rest are not supported.
        if (inputs.positional or []) or inputs.rest is not None:
            raise TypeError(
                "cell input sig must use typed kwargs only, e.g. {x: `a`, y: `b.c`}"
            )
        return _Cell(dict(inputs.keywords or {}), body, scope)

    async def _resource(self, path, *, scope: Scope):
        from slip.slip_datatypes import GetPath as _GP

        gp = self._to_getpath(path)
        if not isinstance(gp, _GP):
            raise TypeError("resource expects a path-like value")
        url = self.evaluator.path_resolver._extract_http_url(gp)
        if not url:
            raise TypeError("resource expects an http(s) URL path")
        r = Scope()
        r["url"] = url
        r["path"] = gp
        return r

    async def _normalize_resource(self, target, scope: Scope):
        from slip.slip_datatypes import (
            GetPath as _GP,
            PathLiteral as _PL,
            IString as _IStr,
            Scope as _Scope,
        )

        # Resource wrapper: Scope with 'url' and 'path' bindings
        match target:
            case _Scope() as s if "url" in getattr(
                s, "bindings", {}
            ) and "path" in getattr(s, "bindings", {}):
                gp = s.bindings["path"]
                url = s.bindings["url"]
                cfg = await self.evaluator.path_resolver._meta_to_dict(
                    getattr(gp, "meta", None), scope
                )
                from slip.slip_http import normalize_response_mode

                rm = normalize_response_mode(cfg)
                if rm is not None:
                    cfg["response-mode"] = rm
                return gp, url, cfg

            # Path literal wrapping a GetPath
            case _PL(inner=_GP() as gp):
                pass  # gp is bound by the pattern

            # Direct GetPath
            case _GP() as gp:
                pass

            # String/IString → parse to GetPath
            case str() | _IStr():
                gp = self._to_getpath(target)

            case _:
                raise TypeError("target expects an http(s) URL path")

        url = self.evaluator.path_resolver._extract_http_url(gp)
        if not url:
            raise TypeError("target expects an http(s) URL path")

        cfg = await self.evaluator.path_resolver._meta_to_dict(
            getattr(gp, "meta", None), scope
        )
        from slip.slip_http import normalize_response_mode

        rm = normalize_response_mode(cfg)
        if rm is not None:
            cfg["response-mode"] = rm
        return gp, url, cfg

    def _apply_content_type_header(self, cfg: dict):
        ctype = cfg.get("content-type") or cfg.get("content_type")
        if ctype:
            headers = dict(cfg.get("headers", {}))
            headers["Content-Type"] = ctype
            cfg["headers"] = headers

    def _prepare_payload(self, cfg: dict, data):
        from slip.slip_serialize import serialize as _ser, detect_format as _detect_fmt

        self._apply_content_type_header(cfg)
        ctype = cfg.get("content-type") or cfg.get("content_type")
        fmt = _detect_fmt(ctype)
        if fmt is not None:
            try:
                return _ser(data, fmt=fmt, pretty=True)
            except Exception:
                return str(data)
        return data if isinstance(data, (str, bytes, bytearray)) else str(data)

    def _bump_rev(self, s: Scope):
        try:
            s.meta["_rev"] = int(s.meta.get("_rev", 0)) + 1
            s.meta.pop("_family", None)
        except Exception:
            pass

    def _package_http_result(self, raw, mode: str | None):
        if mode in (None, "none"):
            return raw
        if isinstance(raw, tuple) and len(raw) == 3:
            status, value, headers = raw
            if mode == "lite":
                return [status, value]
            if mode == "full":
                # Normalize header keys to lowercase for consistent lookups
                norm_headers = headers
                try:
                    items = headers.items() if hasattr(headers, "items") else []
                    norm_headers = {str(k).lower(): v for k, v in items}
                except Exception:
                    pass
                return {
                    "status": status,
                    "value": value,
                    "meta": {"headers": norm_headers},
                }
        return raw

    async def _get(self, target, *, scope: Scope):
        from slip.slip_http import http_get

        _, url, cfg = await self._normalize_resource(target, scope)
        raw = await http_get(url, cfg)
        from slip.slip_http import normalize_response_mode

        return self._package_http_result(raw, normalize_response_mode(cfg))

    async def _put(self, target, data, *, scope: Scope):
        from slip.slip_http import http_put

        _, url, cfg = await self._normalize_resource(target, scope)
        payload = self._prepare_payload(cfg, data)
        raw = await http_put(url, payload, cfg)
        from slip.slip_http import normalize_response_mode

        return self._package_http_result(raw, normalize_response_mode(cfg))

    async def _post(self, target, data, *, scope: Scope):
        from slip.slip_http import http_post

        _, url, cfg = await self._normalize_resource(target, scope)
        payload = self._prepare_payload(cfg, data)
        raw = await http_post(url, payload, cfg)
        from slip.slip_http import normalize_response_mode

        return self._package_http_result(raw, normalize_response_mode(cfg))

    async def _del(self, target, *, scope: Scope):
        from slip.slip_http import http_delete

        _, url, cfg = await self._normalize_resource(target, scope)
        # Ensure DELETE carries configured content-type header (for servers that inspect it)
        self._apply_content_type_header(cfg)
        raw = await http_delete(url, cfg)
        from slip.slip_http import normalize_response_mode

        return self._package_http_result(raw, normalize_response_mode(cfg))

    # Optional compatibility alias; remove later if not needed
    async def _http_post(self, target, data, *, scope: Scope):
        return await self._post(target, data, scope=scope)

    async def _import(self, target, *, scope: Scope):
        """
        Load a SLIP module and return a *shadow* scope that inherits from the module exports.

        Accepted target forms:
          - PathLiteral wrapping a GetPath (e.g., import `file://./mod.slip`)
          - string / i-string locator (e.g., import "file://./mod.slip")
          - GetPath *value* (e.g., produced by `call` on a locator string, or a variable path like `gp`)
            If it is not itself a locator, it is resolved as a normal variable path and we retry.

        Caching:
          - file:// locators are cached by resolved absolute filesystem path (canonical file:// key)
          - http(s):// locators are cached by URL string
        """
        from slip.slip_datatypes import (
            PathLiteral as _PL,
            GetPath as _GP,
            IString as _IStr,
            Code as _Code,
        )

        ev = self.evaluator

        # ----------------------------
        # 0) Code import: import <Code> executes code as a module
        # ----------------------------
        if isinstance(target, _Code):
            cache = getattr(ev, "module_cache", None)
            if cache is None:
                cache = ev.module_cache = {}

            cache_key = (
                getattr(target, "source_path", None)
                or getattr(target, "source_locator", None)
                or id(target)
            )
            if cache_key in cache:
                return Scope(parent=cache[cache_key])

            module_dir = None
            try:
                import os

                sp = getattr(target, "source_path", None)
                if isinstance(sp, str) and sp:
                    module_dir = os.path.dirname(sp) or os.getcwd()
            except Exception:
                module_dir = None

            from slip.slip_runtime import ScriptRunner

            runner = ScriptRunner()
            if module_dir:
                runner.source_dir = module_dir

            await runner._initialize()
            before_bindings = dict(runner.root_scope.bindings)

            # Execute the code AST directly
            await runner.evaluator._eval(target.ast, runner.root_scope)

            after_bindings = runner.root_scope.bindings
            export_names = [
                name
                for name, val in after_bindings.items()
                if (name not in before_bindings)
                or (before_bindings.get(name) is not val)
            ]

            mod_scope = Scope(parent=runner.root_scope)
            for name in export_names:
                mod_scope[name] = after_bindings[name]

            cache[cache_key] = mod_scope
            return Scope(parent=mod_scope)

        # ----------------------------
        # 1) Normalize target -> locator
        # ----------------------------
        url: str | None = None
        file_loc: str | None = None

        if isinstance(target, _PL):
            inner = getattr(target, "inner", None)
            if not isinstance(inner, _GP):
                raise PathNotFound("import")

            # Preserve legacy safety rule: only parser-produced path literals (with .loc)
            # are accepted as direct locators. Runtime-constructed PathLiterals must be
            # passed as strings or as GetPath values.
            if not hasattr(inner, "loc") or inner.loc is None:
                raise PathNotFound("import")

            url = ev.path_resolver._extract_http_url(inner)
            file_loc = ev.path_resolver._extract_file_locator(inner)

        elif isinstance(target, (str, _IStr)):
            s = str(target).strip()
            if s.startswith("http://") or s.startswith("https://"):
                url = s
            elif s.startswith("file://"):
                file_loc = s
            else:
                raise PathNotFound("import")

        elif isinstance(target, _GP):
            # IMPORTANT: In the normal evaluator, passing `gp` (a variable) to `import`
            # evaluates `gp` first. If `gp` is a locator string, it will already be
            # a Python str here. If we get a GetPath here, it is either:
            #   1) a literal locator token produced by `call` on a locator string
            #      (e.g., GetPath([Name("file://...")])) — treat as locator, OR
            #   2) a variable path (e.g., GetPath([Name("gp")])) — resolve once and retry.
            #
            # We must NOT treat case (2) as a locator token, otherwise `import gp`
            # would try to import "gp" as a URL.
            segs = getattr(target, "segments", None) or []
            if len(segs) == 1 and isinstance(segs[0], Name):
                token = segs[0].text
                if isinstance(token, str) and (
                    token.startswith("file://")
                    or token.startswith("http://")
                    or token.startswith("https://")
                ):
                    if token.startswith("file://"):
                        file_loc = token
                    else:
                        url = token
                else:
                    # Resolve as a variable path and retry
                    try:
                        actual_target = await ev.path_resolver.get(target, scope)
                    except Exception:
                        raise PathNotFound("import")
                    return await self._import(actual_target, scope=scope)
            else:
                # Non-trivial paths are always treated as variable paths for import
                try:
                    actual_target = await ev.path_resolver.get(target, scope)
                except Exception:
                    raise PathNotFound("import")
                return await self._import(actual_target, scope=scope)

        else:
            raise PathNotFound("import")

        # ----------------------------
        # 2) Canonical cache key + load source
        # ----------------------------
        cache = getattr(ev, "module_cache", None)
        if cache is None:
            cache = ev.module_cache = {}

        source_text: str | None = None
        module_dir: str | None = None
        cache_key: str

        if file_loc:
            from slip.slip_file import _resolve_locator
            import os

            abs_path = _resolve_locator(file_loc, getattr(ev, "source_dir", None))
            cache_key = f"file://{abs_path}"

            if cache_key in cache:
                return Scope(parent=cache[cache_key])

            with open(abs_path, "r", encoding="utf-8") as f:
                source_text = f.read()
            module_dir = os.path.dirname(abs_path) or os.getcwd()

        elif url:
            cache_key = url

            if cache_key in cache:
                return Scope(parent=cache[cache_key])

            from slip.slip_http import http_request

            src = await http_request("GET", url, config={})
            if isinstance(src, (bytes, bytearray)):
                try:
                    source_text = src.decode("utf-8")
                except Exception:
                    source_text = src.decode("utf-8", errors="replace")
            elif isinstance(src, str):
                source_text = src
            else:
                source_text = str(src)

        else:
            raise PathNotFound("import")

        # ----------------------------
        # 3) Execute module in an isolated runner and export new/changed bindings
        # ----------------------------
        from slip.slip_runtime import ScriptRunner

        runner = ScriptRunner()
        if module_dir:
            runner.source_dir = module_dir

        await runner._initialize()
        before_bindings = dict(runner.root_scope.bindings)

        res = await runner.handle_script(source_text)
        if res.status != "ok":
            raise RuntimeError(res.error_message or "Failed to load module")

        after_bindings = runner.root_scope.bindings
        export_names = [
            name
            for name, val in after_bindings.items()
            if (name not in before_bindings) or (before_bindings.get(name) is not val)
        ]

        mod_scope = Scope(parent=runner.root_scope)
        for name in export_names:
            mod_scope[name] = after_bindings[name]

        cache[cache_key] = mod_scope
        return Scope(parent=mod_scope)

    # --- List and Sequence Utilities ---
    def _slice_from(self, data, start):
        return data[start:]

    def _slice_to(self, data, end):
        return data[:end]

    def _slice_range(self, data, start, end):
        return data[start:end]

    def _range(self, *args):
        return list(range(*args))

    def _sort(self, data):
        return sorted(data)

    # --- Dictionary and Scopeironment Utilities ---
    def _keys(self, d):
        return list(
            d.keys() if isinstance(d, collections.abc.Mapping) else d.bindings.keys()
        )

    def _values(self, d):
        return list(
            d.values()
            if isinstance(d, collections.abc.Mapping)
            else d.bindings.values()
        )

    def _items(self, d):
        if isinstance(d, collections.abc.Mapping):
            return [[k, v] for k, v in d.items()]
        # Scope-like fallback: iterate .bindings
        return [[k, v] for k, v in getattr(d, "bindings", {}).items()]

    def _has_key_q(self, obj, key):
        """
        Predicate: does obj have the given key?
        - For dict/mapping: `key in obj`
        - For Scope: lookup via find_owner(key)
        Accepts key as string or IString; other types are coerced to str.
        """
        from slip.slip_datatypes import Scope as _Scope, IString as _IStr

        k = key
        if isinstance(k, _IStr) or isinstance(k, str):
            k = str(k)
        else:
            try:
                k = str(k)
            except Exception:
                return False
        if isinstance(obj, collections.abc.Mapping):
            return k in obj
        if isinstance(obj, _Scope):
            try:
                return obj.find_owner(k) is not None
            except Exception:
                return False
        # For other objects, try attribute presence as a last resort
        try:
            return hasattr(obj, k)
        except Exception:
            return False

    # --- Object Model ---
    def _scope(self, config: dict):
        self.evaluator._dbg("scope()", "config_type", type(config).__name__)
        # Accept any mapping-like object (dict, SlipObject, etc.)
        is_mapping = isinstance(config, collections.abc.Mapping)
        if is_mapping and "meta" in config:
            raise ValueError("`scope` cannot be initialized with a 'meta' key.")
        s = Scope()
        if is_mapping:
            for k, v in config.items():
                s[k] = v
        return s

    def _resolver(self, config: dict):
        self.evaluator._dbg("resolver()", "config_type", type(config).__name__)
        # Accept any mapping-like object (dict, SlipObject, etc.)
        is_mapping = isinstance(config, collections.abc.Mapping)
        if is_mapping and "meta" in config:
            raise ValueError("`resolver` cannot be initialized with a 'meta' key.")
        s = Scope()
        if is_mapping:
            for k, v in config.items():
                s[k] = v
        s.meta["resolver"] = True
        return s

    def _inherit(self, obj: Scope, proto: Scope):
        self.evaluator._dbg(
            "inherit()",
            "target_is_scope",
            isinstance(obj, Scope),
            "proto_is_scope",
            isinstance(proto, Scope),
        )
        if not isinstance(obj, Scope) or not isinstance(proto, Scope):
            raise TypeError("inherit expects (scope, scope)")
        obj.inherit(proto)
        self._bump_rev(obj)
        return obj

    # --- System and Scopeironment ---
    async def _sleep(self, seconds):
        await asyncio.sleep(seconds)

    def _time(self):
        return time.time()

    def _current_scope(self, *, scope: Scope):
        return scope

    def _task(self, code: Code, *, scope: Scope):
        """
        Schedule a code block to run asynchronously.

        - Runs the block in a new child scope of the current lexical scope.
        - Sets evaluator.is_in_task_context = True for the duration to enable auto-yield in loops.
        - Registers the asyncio.Task with the current host object (if any) for lifecycle management.
        - Returns the asyncio.Task handle.
        """
        if not isinstance(code, Code):
            raise TypeError("task requires a code block")

        evaluator = self.evaluator
        parent_scope = scope

        async def _runner():
            child = Scope(parent=parent_scope)
            prev_flag = getattr(evaluator, "is_in_task_context", False)
            # Increment task-context counter and ensure the flag is on during this task
            evaluator.task_context_count = (
                getattr(evaluator, "task_context_count", 0) + 1
            )
            evaluator.is_in_task_context = True
            try:
                res = await evaluator._eval(code.ast, child)
                if isinstance(res, ReturnSignal):
                    return res.value
            finally:
                # Decrement; only restore the flag when the last task-context exits
                try:
                    evaluator.task_context_count -= 1
                except Exception:
                    evaluator.task_context_count = 0
                if evaluator.task_context_count <= 0:
                    evaluator.task_context_count = 0
                    evaluator.is_in_task_context = prev_flag
                # Ensure the task is removed from the host registry even if callbacks fail
                try:
                    host_ref = getattr(evaluator, "host_object", None)
                    if host_ref is not None and hasattr(host_ref, "active_slip_tasks"):
                        try:
                            cur_task = asyncio.current_task()
                        except Exception:
                            cur_task = None
                        if cur_task is not None:
                            try:
                                host_ref.active_slip_tasks.discard(cur_task)
                            except Exception:
                                pass
                        # Best-effort: also remove any completed tasks from the host tracking set
                        try:
                            for t in list(host_ref.active_slip_tasks):
                                try:
                                    if getattr(t, "done", None) and t.done():
                                        host_ref.active_slip_tasks.discard(t)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass

        t = asyncio.create_task(_runner())
        host = getattr(evaluator, "host_object", None)
        try:
            if host is not None and hasattr(host, "_register_task"):
                host._register_task(t)
            elif host is not None and hasattr(host, "active_slip_tasks"):
                # Fallback: directly add to the tracking set if present and use a watcher to remove reliably.
                host.active_slip_tasks.add(t)

                async def _watcher(task_obj: asyncio.Task):
                    try:
                        await task_obj
                    finally:
                        try:
                            host.active_slip_tasks.discard(task_obj)
                        except Exception:
                            pass

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.call_soon(asyncio.create_task, _watcher(t))
                    else:
                        # Fallback: attach done-callback if loop not running
                        t.add_done_callback(
                            lambda _t: host.active_slip_tasks.discard(_t)
                        )
                except Exception:
                    t.add_done_callback(lambda _t: host.active_slip_tasks.discard(_t))
        except Exception:
            # Registration is best-effort; continue even if unavailable
            pass
        return t

    def _random(self):
        return random.random()

    def _random_int(self, a, b):
        return random.randint(a, b)

    def _len(self, collection):
        return len(collection)

    # --- Side Effects and I/O ---
    def _emit(self, topic_or_topics, *message_parts):
        """Generates a side-effect event for the host application."""
        topics = (
            topic_or_topics if isinstance(topic_or_topics, list) else [topic_or_topics]
        )
        message = " ".join(map(str, message_parts))
        event = {"topics": topics, "message": message}
        if self.evaluator:
            self.evaluator.side_effects.append(event)
        return None

    # --- Language Primitives ---
    async def _if(self, args: list, *, scope: Scope):
        self.evaluator._dbg(
            "if()", "argc", len(args), "arg_types", [type(a).__name__ for a in args]
        )
        if len(args) < 2 or len(args) > 3:
            raise TypeError(f"if expects 2 or 3 arguments, got {len(args)}")

        cond, then_arg = args[0], args[1]
        else_arg = args[2] if len(args) == 3 else None

        # Evaluate condition; propagate control-exits (ReturnSignal or legacy Response(return ...))
        if isinstance(cond, Code):
            cond_val = await self.evaluator._eval(cond.ast, scope)
            if self._is_control_exit(cond_val):
                return cond_val
        else:  # It's already an evaluated value
            cond_val = cond

        async def _resolve_code_arg(arg):
            if arg is None:
                return None
            if isinstance(arg, Code):
                return arg
            # Allow passing a variable that holds a Code value (e.g., 'then-block')
            val = await self.evaluator._eval(arg, scope)
            if self._is_control_exit(val):
                return val
            if isinstance(val, Code):
                return val
            raise TypeError("branch of if must be a code block")

        if cond_val:
            then_code = await _resolve_code_arg(then_arg)
            if self._is_control_exit(then_code):
                return then_code
            return await self.evaluator._eval(then_code.ast, scope)
        elif else_arg is not None:
            else_code = await _resolve_code_arg(else_arg)
            if self._is_control_exit(else_code):
                return else_code
            return await self.evaluator._eval(else_code.ast, scope)
        return None

    async def _while(self, args: list, *, scope: Scope):
        # Assumes root.slip is loaded and provides operator aliases.
        if len(args) != 2:
            raise TypeError(
                f"while expects 2 arguments (condition, body), got {len(args)}"
            )
        cond_block, body_block = args
        # Condition must be a code block
        if not isinstance(cond_block, Code):
            raise TypeError("while requires code blocks for condition and body")

        # Body may be a code block literal or a reference to a code block
        if isinstance(body_block, Code):
            body_code = body_block
        else:
            body_val = await self.evaluator._eval(body_block, scope)
            if self._is_control_exit(body_val):
                return body_val
            if not isinstance(body_val, Code):
                raise TypeError("while requires code blocks for condition and body")
            body_code = body_val

        last = None
        iter_count = 0

        # Optional safety cap to prevent runaway loops; configurable via env.
        # Default is fairly high to avoid impacting normal scripts.
        try:
            import os as _os

            _max_iters_env = _os.environ.get("SLIP_MAX_LOOP_ITERS")
            max_iters = int(_max_iters_env) if _max_iters_env is not None else 100000
        except Exception:
            max_iters = 100000

        while True:
            # Cooperative yield at the start of each iteration in task contexts.
            if (
                getattr(self.evaluator, "is_in_task_context", False)
                or getattr(self.evaluator, "task_context_count", 0) > 0
            ):
                await asyncio.sleep(0)

            cond_val = await self.evaluator._eval(cond_block.ast, scope)
            if self._is_control_exit(cond_val):
                return cond_val
            if not cond_val:
                break

            body_res = await self.evaluator._eval(body_code.ast, scope)
            if self._is_control_exit(body_res):
                return body_res
            last = body_res

            iter_count += 1

            # Cooperative yield periodically to preserve fairness outside task contexts.
            if (iter_count % 100) == 0:
                await asyncio.sleep(0)

            # Guard against accidental infinite loops
            if max_iters is not None and iter_count >= max_iters:
                raise RuntimeError("while: iteration limit exceeded")
        return last

    async def _foreach(self, args: list, *, scope: Scope):
        # Assumes root.slip is loaded and provides operator aliases.
        self.evaluator._dbg(
            "foreach()", "argc", len(args), "types", [type(a).__name__ for a in args]
        )
        if len(args) != 3:
            raise TypeError(
                f"foreach expects 3 arguments (vars-sig, collection, body), got {len(args)}"
            )
        vars_spec, collection_expr, body_arg = args

        # Body may be a code literal or a variable holding Code
        if isinstance(body_arg, Code):
            body_code = body_arg
        else:
            body_val = await self.evaluator._eval(body_arg, scope)
            if self._is_control_exit(body_val):
                return body_val
            if not isinstance(body_val, Code):
                raise TypeError("foreach requires a code block for the body")
            body_code = body_val

        # Vars must be a sig literal with positional names
        from slip.slip_datatypes import Sig as _Sig

        if not isinstance(vars_spec, _Sig):
            raise TypeError(
                "foreach requires a sig literal for the variable pattern, e.g., {x} or {k, v}"
            )
        var_names = list(vars_spec.positional or [])
        if not var_names:
            raise TypeError("foreach variable sig must list at least one name")
        if "this" in var_names:
            raise SyntaxError("`this` is reserved and cannot be bound by foreach")

        # Evaluate the collection expression (or accept already-evaluated collections)
        if (
            isinstance(collection_expr, (list, dict))
            or isinstance(collection_expr, collections.abc.Mapping)
            or isinstance(collection_expr, Scope)
        ):
            collection = collection_expr
        else:
            collection = await self.evaluator._eval(collection_expr, scope)
            if self._is_control_exit(collection):
                return collection

        # Helper to run body and auto-yield in task context
        iter_count = 0

        async def _run_body():
            nonlocal iter_count
            # Cooperative yield at the start of each iteration in task contexts.
            if (
                getattr(self.evaluator, "is_in_task_context", False)
                or getattr(self.evaluator, "task_context_count", 0) > 0
            ):
                await asyncio.sleep(0)

            # Accumulator-style write-back only for infix updates: [ name <op> rhs... ]
            try:
                exprs = getattr(body_code, "ast", None)
                if (
                    isinstance(exprs, list)
                    and len(exprs) == 1
                    and isinstance(exprs[0], list)
                    and exprs[0]
                ):
                    expr = exprs[0]
                    head = expr[0]
                    # Require simple name head and at least 3 terms (name op rhs)
                    if (
                        isinstance(head, GetPath)
                        and len(getattr(head, "segments", []) or []) == 1
                        and isinstance(head.segments[0], Name)
                        and len(expr) >= 3
                    ):
                        # Verify second term resolves to a piped operator
                        is_op = False
                        try:
                            await self.evaluator._resolve_operator_to_func_path(
                                expr[1], scope
                            )
                            is_op = True
                        except Exception:
                            is_op = False
                        if is_op:
                            target = head.segments[0].text
                            val = await self.evaluator._eval_expr(expr, scope)
                            if self._is_control_exit(val):
                                return val
                            scope[target] = val
                            iter_count += 1
                            return None
            except Exception:
                # Fallback to plain evaluation
                pass
            res = await self.evaluator._eval(body_code.ast, scope)
            if self._is_control_exit(res):
                return res
            iter_count += 1
            return None

        # Mapping-like (dict) handling: {k} or {k, v}
        if isinstance(collection, collections.abc.Mapping):
            if len(var_names) == 1:
                # For mappings (including SlipDict), single-var iteration yields keys.
                for k in collection.keys():
                    scope[var_names[0]] = k
                    out = await _run_body()
                    if self._is_control_exit(out):
                        return out
            elif len(var_names) == 2:
                for k, v in collection.items():
                    scope[var_names[0]] = k
                    scope[var_names[1]] = v
                    out = await _run_body()
                    if self._is_control_exit(out):
                        return out
            else:
                raise TypeError(
                    "foreach over a mapping supports {k} or {k, v} variable patterns"
                )
            return None

        # Scope handling: iterate bindings as keys/items
        from slip.slip_datatypes import Scope as _Scope

        if isinstance(collection, _Scope):
            if len(var_names) == 1:
                for k in collection.bindings.keys():
                    scope[var_names[0]] = k
                    out = await _run_body()
                    if self._is_control_exit(out):
                        return out
            elif len(var_names) == 2:
                for k, v in collection.bindings.items():
                    scope[var_names[0]] = k
                    scope[var_names[1]] = v
                    out = await _run_body()
                    if self._is_control_exit(out):
                        return out
            else:
                raise TypeError(
                    "foreach over a scope supports {k} or {k, v} variable patterns"
                )
            return None

        # Sequence-like: {x} binds each element; {a, b, ...} destructures iterable elements
        it = collection
        if len(var_names) == 1:
            for item in it:
                scope[var_names[0]] = item
                out = await _run_body()
                if self._is_control_exit(out):
                    return out
            return None
        else:
            for item in it:
                try:
                    parts = list(item)
                except Exception:
                    raise TypeError(
                        "foreach destructuring requires items to be iterable"
                    )
                if len(parts) != len(var_names):
                    raise TypeError(
                        f"foreach destructuring arity mismatch: expected {len(var_names)}, got {len(parts)}"
                    )
                for nm, val in zip(var_names, parts):
                    scope[nm] = val
                out = await _run_body()
                if self._is_control_exit(out):
                    return out
            return None

    def _fn(self, args: list, *, scope: Scope):
        from slip.slip_datatypes import SlipFunction, Sig as SigType

        # Assumes root.slip is loaded and provides operator aliases.
        if len(args) != 2:
            raise TypeError(f"fn expects 2 arguments (args, body), got {len(args)}")
        arg_spec, body_block = args
        if not isinstance(body_block, Code):
            raise TypeError("Body of fn must be a code block")

        # Contract: `this` is reserved.
        # - It may not appear as a positional param.
        # - It may appear as a typed kwarg ONLY if it is the first declared param.
        if isinstance(arg_spec, SigType):
            # Contract: `this` is reserved.
            # - It may not appear as a positional param.
            # - It may appear as a typed kwarg ONLY if it is the first declared kwarg.
            #
            # IMPORTANT: In SLIP's sig syntax, untyped params are positional.
            # A committing signature uses `this: Type` (kw) followed by other
            # positional params (e.g. `{this: T, x}`), so positional params are allowed.
            if "this" in (arg_spec.positional or []):
                raise SyntaxError(
                    "`this` is reserved; use `this: Type` as the first parameter for transactions"
                )

            if "this" in (arg_spec.keywords or {}):
                # `this` is allowed only as the first typed parameter.
                # NOTE: other untyped positional params may follow in source, e.g. `{this: T, x}`.
                first_kw = next(iter(arg_spec.keywords.keys()), None)
                if first_kw != "this":
                    raise SyntaxError(
                        "`this` is reserved and must be the first parameter when used (as `this: Type`)"
                    )
        elif isinstance(arg_spec, Code):
            # Legacy/Untyped: check for 'this' in the parameter list
            for node in arg_spec.nodes:
                # nodes are lists of terms
                if isinstance(node, list) and len(node) == 1:
                    term = node[0]
                    if (
                        isinstance(term, GetPath)
                        and len(term.segments) == 1
                        and isinstance(term.segments[0], Name)
                    ):
                        if term.segments[0].text == "this":
                            raise SyntaxError(
                                "`this` is reserved and cannot be used as an untyped parameter"
                            )

        fn = SlipFunction(arg_spec, body_block, scope)
        if isinstance(arg_spec, SigType):
            fn.meta["type"] = arg_spec
            if arg_spec.where:
                fn.meta.setdefault("guards", []).append(arg_spec.where)
        elif not isinstance(arg_spec, Code):
            raise TypeError("Arguments to fn must be a code block or a sig literal")
        return fn

    # --- Container Constructors ---
    def _list(self, code: Code, *, scope: Scope):
        ev = getattr(self, "evaluator", None)
        # Test-path: mock evaluator provides .run (synchronous)
        if hasattr(ev, "run"):
            res = [ev.run(expr, scope) for expr in code.ast]
            for item in res:
                if getattr(item, "_is_this_capability", False):
                    raise PermissionError(
                        "`this` capability token cannot be stored in a list"
                    )
            return res

        # Runtime-path: return a coroutine the evaluator can await
        async def _async_impl():
            results = []
            for expr in code.ast:
                val = await ev._eval_expr(expr, scope)
                if getattr(val, "_is_this_capability", False):
                    raise PermissionError(
                        "`this` capability token cannot be stored in a list"
                    )
                results.append(val)
            return results

        return _async_impl()

    def _dict(self, code: Code, *, scope: Scope):
        ev = getattr(self, "evaluator", None)
        # Test-path: mock evaluator provides .run (synchronous) over the entire code block
        if hasattr(ev, "run"):
            # Test-path: create an unlinked, fresh scope (no parent) per test expectations.
            temp_scope = Scope()
            ev.run(code.ast, temp_scope)
            out = SlipDict()
            for k, v in temp_scope.bindings.items():
                out[k] = v
            return out

        # Runtime-path: return a coroutine the evaluator can await
        async def _async_impl():
            # Use a child scope linked to the current lexical scope so lookups (e.g., '+') resolve.
            temp_scope = Scope(parent=scope)
            for expr in code.ast:
                await ev._eval_expr(expr, temp_scope)
            out = SlipDict()
            for k, v in temp_scope.bindings.items():
                out[k] = v
            return out

        return _async_impl()

    async def _run(self, code: Code, *, scope: Scope):
        # Hermetic sandbox: parent is the root scope; expands inject/splice only if the Code was not previously expanded; uses caller’s scope for expansion.
        ev = self.evaluator
        # Hermetic sandbox:
        # - writes must not leak into the caller
        # - but the language environment (root.slip bindings like '+') must remain available
        root = getattr(ev, "root_scope", None) or scope
        sandbox = Scope(parent=root)

        last = None
        exprs = code.ast
        if not getattr(code, "_expanded", False):
            exprs = await ev._expand_code_literal(
                code, scope
            )  # expand against caller’s scope
        for expr in exprs:
            last = await ev._eval_expr(expr, sandbox)
        return last

    async def _run_with(self, code: Code, target_scope: Scope, *, scope: Scope):
        """
        Execute code within target_scope for writes, but resolve inject/splice from the caller’s scope.
        """
        exprs = code.ast
        if not getattr(code, "_expanded", False):
            exprs = await self.evaluator._expand_code_literal(
                code, scope
            )  # expand against caller’s scope

        # Allow passing a zero‑arity callable (e.g., current-scope) as the target scope
        if not isinstance(target_scope, Scope) and callable(target_scope):
            try:
                sig = inspect.signature(target_scope)
                if (
                    "scope" in sig.parameters
                    and sig.parameters["scope"].kind == inspect.Parameter.KEYWORD_ONLY
                ):
                    maybe = target_scope(scope=scope)
                    if inspect.isawaitable(maybe):
                        maybe = await maybe
                    if isinstance(maybe, Scope):
                        target_scope = maybe
            except Exception:
                pass

        # Temporarily link target scope to caller scope for name lookups (fn, +, *, etc.).
        # This makes run-with: "writes go to target, reads come from caller env".
        same_scope = target_scope is scope
        prev_parent = target_scope.meta.get("parent") if not same_scope else None

        # Ensure writes prefer the target scope, not its owner/parent chain, during run-with.
        prev_bind_pref = getattr(self.evaluator, "bind_locals_prefer_container", False)
        self.evaluator.bind_locals_prefer_container = True
        try:
            if not same_scope and prev_parent is None:
                target_scope.meta["parent"] = scope

            last = None
            for expr in exprs:
                last = await self.evaluator._eval_expr(expr, target_scope)
            return last
        finally:
            self.evaluator.bind_locals_prefer_container = prev_bind_pref
            if not same_scope and prev_parent is None:
                # Keep the language environment available for closures created during run-with.
                root = getattr(self.evaluator, "root_scope", None)
                target_scope.meta["parent"] = root if isinstance(root, Scope) else None

    def _response(self, status: PathLiteral, value: Any):
        return Response(status, value)

    def _respond(self, status: PathLiteral, value: Any):
        # Mirror status/value into the unified outcome object and clear stacktrace
        try:
            out = getattr(self.evaluator, "outcome", None)
            if isinstance(out, Outcome):
                out.status = status
                out.value = value
                out.stacktrace = []
                out.error = None
        except Exception:
            pass
        # Emit stderr side-effect for non-ok statuses (existing behavior)
        try:
            inner = getattr(status, "inner", None)
            if (
                isinstance(inner, GetPath)
                and len(inner.segments) == 1
                and isinstance(inner.segments[0], Name)
                and inner.segments[0].text != "ok"
            ):
                self.evaluator.side_effects.append(
                    {"topics": ["stderr"], "message": str(value)}
                )
        except Exception:
            pass
        # Non-local exit: signal an early return carrying a Response(status, value)
        return ReturnSignal(Response(status, value))

    def _status(self, value):
        """Minimal status helper exposed as `status` in SLIP.

        - If `value` is a Response, return its .status (a PathLiteral).
        - Otherwise return the canonical `ok` PathLiteral singleton.
        """
        from slip.slip_datatypes import Response as _Resp

        if isinstance(value, _Resp):
            return value.status
        return _OK_STATUS

    def _is_control_exit(self, val):
        """Return True if val is a non-local control exit produced by evaluation.

        Accepts:
          - ReturnSignal (new dedicated control-flow type)
          - Response with a PathLiteral status whose single segment is the name "return"
            (legacy sentinel; kept for backward compatibility)
        """
        from slip.slip_datatypes import (
            ReturnSignal as _RS,
            Response as _Resp,
            PathLiteral as _PL,
            GetPath as _GP,
            Name as _Name,
        )

        if isinstance(val, _RS):
            return True
        if isinstance(val, _Resp):
            st = getattr(val, "status", None)
            if isinstance(st, _PL):
                inner = getattr(st, "inner", None)
                if (
                    isinstance(inner, _GP)
                    and len(inner.segments) == 1
                    and isinstance(inner.segments[0], _Name)
                ):
                    return inner.segments[0].text == "return"
        return False

    def _return(self, value: Any = None):
        try:
            out = getattr(self.evaluator, "outcome", None)
            if isinstance(out, Outcome):
                out.status = _OK_STATUS
                out.value = value
                out.stacktrace = []
                out.error = None
        except Exception:
            pass
        return ReturnSignal(value)

    async def _do(self, code, *, scope: Scope):
        from slip.slip_datatypes import (
            Code as _Code,
            Response as _Resp,
            PathLiteral as _PL,
            GetPath as _GP,
            Name as _Name,
        )
        from slip.slip_runtime import SlipDict as _SlipDict

        ev = self.evaluator

        # Resolve argument to a Code block (allow variable that holds Code)
        if not isinstance(code, _Code):
            val = await ev._eval(code, scope)
            if isinstance(val, _Resp):
                # Propagate control-flow (e.g., return) upward
                return val
            if not isinstance(val, _Code):
                raise TypeError("do requires a code block")
            code = val

        start = len(ev.side_effects)
        try:
            result = await ev._eval(code.ast, scope)
        except Exception as e:
            outcome = _Resp(_ERR_STATUS, str(e))
        else:
            # Normalize to a Response, handling internal ReturnSignal control flow.
            from slip.slip_datatypes import ReturnSignal as _RS

            if isinstance(result, _Resp):
                outcome = result
            elif isinstance(result, _RS):
                # ReturnSignal(value) => unwrap: if the carried value is a Response use it,
                # otherwise wrap as an ok Response.
                inner = result.value
                if isinstance(inner, _Resp):
                    outcome = inner
                else:
                    outcome = _Resp(_OK_STATUS, inner)
            else:
                outcome = _Resp(_OK_STATUS, result)

        end = len(ev.side_effects)
        out = _SlipDict()
        out["outcome"] = outcome
        out["effects"] = _EffectsView(ev.side_effects, start, end)
        return out

    # --- Type and Conversion ---
    def _to_str(self, value):
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.decode("utf-8", errors="replace")
        return str(value)

    def _to_int(self, value):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _to_float(self, value):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _to_bool(self, value):
        return bool(value)

    def _copy(self, value):
        return copy.copy(value)

    def _clone(self, value):
        # Safe deep copy that avoids recursion issues with complex objects.
        from slip.slip_runtime import SlipDict as _SlipDict

        if isinstance(value, list):
            return [self._clone(v) for v in value]
        if isinstance(value, dict):
            return {k: self._clone(v) for k, v in value.items()}
        if isinstance(value, _SlipDict):
            out = _SlipDict()
            for k, v in value.items():
                out[k] = self._clone(v)
            return out
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    async def _rehydrate_slip_value(
        self, value, *, scope: Scope, source: str, memo=None
    ):
        if memo is None:
            memo = {}

        def _memo_key(node):
            uid = getattr(node, "uid", None)
            if uid is not None:
                return (type(node).__name__, uid)
            return id(node)

        async def _rehydrate(node):
            if isinstance(node, collections.abc.Sequence) and not isinstance(
                node, (str, bytes, bytearray, collections.abc.Mapping)
            ):
                node_key = _memo_key(node)
                if node_key in memo:
                    return memo[node_key]
                out = []
                memo[node_key] = out
                out.extend([await _rehydrate(v) for v in node])
                return out

            if not isinstance(node, collections.abc.Mapping):
                return node

            node_key = _memo_key(node)
            if node_key in memo:
                return memo[node_key]

            marker = node.get("__slip__")
            if marker is None:
                out = {}
                memo[node_key] = out
                for k, v in node.items():
                    out[k] = await _rehydrate(v)
                return out

            if not isinstance(marker, collections.abc.Mapping):
                raise TypeError(f"{source}: __slip__ must be a mapping")

            slip_type = marker.get("type")
            if slip_type != "scope":
                raise TypeError(f"{source}: unsupported __slip__.type {slip_type!r}")

            out = Scope()
            memo[node_key] = out
            prototype_name = marker.get("prototype")
            if prototype_name is not None:
                try:
                    proto_path = self._to_getpath(prototype_name)
                    prototype = await self.evaluator.path_resolver.get(
                        proto_path, scope
                    )
                except Exception as e:
                    raise PathNotFound(f"{source} prototype: {prototype_name}") from e
                if not isinstance(prototype, Scope):
                    raise TypeError(f"{source}: prototype must resolve to a scope")
                out.inherit(prototype)

            for k, v in node.items():
                if k == "__slip__":
                    continue
                out[k] = await _rehydrate(v)
            return out

        return await _rehydrate(value)

    async def _as_slip(self, value, *, scope: Scope):
        return await self._rehydrate_slip_value(value, scope=scope, source="as-slip")

    def _resolve_host_data_loader(self):
        loader = getattr(self.evaluator, "host_data_loader", None)
        if loader is None:
            raise PathNotFound("host-data")
        return loader

    async def _host_data(self, object_id, *, scope: Scope):
        loader = self._resolve_host_data_loader()
        if inspect.iscoroutinefunction(loader):
            return await loader(object_id)
        value = loader(object_id)
        if inspect.isawaitable(value):
            return await value
        return value

    async def _host_object(self, object_id, *, scope: Scope):
        cache = getattr(self.evaluator, "host_object_cache", None)
        if cache is None:
            cache = {}
            self.evaluator.host_object_cache = cache
        if object_id in cache:
            return cache[object_id]
        raw = await self._host_data(object_id, scope=scope)
        rehydrate_cache = getattr(self.evaluator, "host_rehydrate_cache", None)
        if rehydrate_cache is None:
            rehydrate_cache = {}
            self.evaluator.host_rehydrate_cache = rehydrate_cache
        value = await self._rehydrate_slip_value(
            raw, scope=scope, source="host-object", memo=rehydrate_cache
        )
        cache[object_id] = value
        return value

    def _type_of(self, value):
        from slip.slip_datatypes import (
            Scope,
            Code,
            IString,
            SlipFunction,
            GenericFunction,
            GetPath,
            SetPath,
            DelPath,
            PipedPath,
            PathLiteral,
            MultiSetPath,
            Name,
        )
        from slip.slip_runtime import SlipDict

        def lit(name: str):
            if name == "ok":
                return _OK_STATUS
            if name == "err":
                return _ERR_STATUS
            return PathLiteral(GetPath([Name(name)]))

        if value is None:
            return lit("none")
        if isinstance(value, bool):
            return lit("boolean")
        # bool is a subclass of int, so check it before int
        if isinstance(value, int) and not isinstance(value, bool):
            return lit("int")
        if isinstance(value, float):
            return lit("float")
        if isinstance(value, Code):
            return lit("code")
        if isinstance(value, IString):
            return lit("i-string")
        if isinstance(value, str):
            return lit("string")
        # Internal list-like selections (filtered views) should present as `list`.
        try:
            if hasattr(value, "realize") and callable(getattr(value, "realize")):
                return lit("list")
        except Exception:
            pass
        if isinstance(value, collections.abc.Sequence) and not isinstance(
            value, (str, bytes, bytearray, collections.abc.Mapping)
        ):
            return lit("list")
        if isinstance(value, (dict, SlipDict)):
            return lit("dict")
        if isinstance(value, Scope):
            try:
                if bool(getattr(value, "meta", {}).get("resolver")):
                    return lit("resolver")
            except Exception:
                pass
            return lit("scope")
        if isinstance(
            value, (GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath)
        ):
            return lit("path")
        if isinstance(value, (SlipFunction, GenericFunction)) or callable(value):
            return lit("function")
        # Fallback: treat as string type
        return lit("string")

    def _example(self, func, example_sig, *, scope: Scope = None):
        from slip.slip_datatypes import Sig, SlipFunction, GenericFunction

        if not isinstance(example_sig, Sig):
            raise TypeError("example expects a sig literal as the second argument")
        if not isinstance(func, (SlipFunction, GenericFunction)):
            raise TypeError(
                "example expects a function or generic function as the first argument"
            )
        meta = getattr(func, "meta", None)
        if meta is None:
            try:
                func.meta = {}
                meta = func.meta
            except Exception:
                raise TypeError("target function does not support metadata")
        examples = meta.setdefault("examples", [])
        examples.append(example_sig)
        return func  # allow chaining and keep assignment value as the function

    def _where(self, func, cond, *, scope: Scope):
        from slip.slip_datatypes import (
            SlipFunction as _SF,
            GenericFunction as _GF,
            Code as _Code,
        )

        if not isinstance(func, (_SF, _GF)):
            raise TypeError("where expects a function or generic function")
        if not isinstance(cond, _Code):
            raise TypeError("where expects a code block")
        meta = getattr(func, "meta", None)
        if meta is None:
            try:
                func.meta = {}
                meta = func.meta
            except Exception:
                raise TypeError("target function does not support metadata")
        guards = meta.setdefault("guards", [])
        guards.append(cond)
        return func

    def _get_body(self, func, sig, *, scope: Scope):
        from slip.slip_datatypes import (
            SlipFunction as _SF,
            GenericFunction as _GF,
            Sig as _Sig,
        )

        if isinstance(func, _SF):
            return func.body
        if isinstance(func, _GF):
            if not isinstance(sig, _Sig):
                raise TypeError("get-body expects a sig literal as the second argument")
            for m in func.methods:
                s = getattr(m, "meta", {}).get("type")
                if s == sig:
                    return m.body
            # No matching method found
            raise PathNotFound("get-body")
        raise TypeError("get-body expects a function or generic function")

    async def _test(self, func, *, scope: Scope):
        from slip.slip_datatypes import (
            Sig,
            SlipFunction,
            GenericFunction,
            GetPath,
            Code,
            GetPath as _GP,
            SetPath as _SP,
            DelPath as _DP,
            PipedPath as _PP,
            PathLiteral as _PL,
            MultiSetPath as _MSP,
        )

        if not isinstance(func, (SlipFunction, GenericFunction)):
            raise TypeError("test expects a function or generic function")

        def _status(name: str):
            # Prefer canonical singletons for ok/err; fall back to constructed PathLiteral.
            if name == "ok":
                return _OK_STATUS
            if name == "err":
                return _ERR_STATUS
            from slip.slip_datatypes import (
                PathLiteral as _PL,
                GetPath as _GP,
                Name as _Name,
            )

            return _PL(_GP([_Name(name)]))

        # Collect examples from the container and each method (to support inline chaining after fn)
        examples = []
        meta = getattr(func, "meta", {}) or {}
        examples.extend(meta.get("examples") or [])
        if isinstance(func, GenericFunction):
            for m in func.methods:
                exs = getattr(m, "meta", {}).get("examples") or []
                examples.extend(exs)

        async def _resolve(v):
            # Evaluate GetPath/Code; pass through literals
            if isinstance(v, GetPath):
                return await self.evaluator._eval(v, scope)
            if isinstance(v, Code):
                return await self.evaluator._eval(v.ast, scope)
            return v

        # Helper: iterate candidate value sources in priority order
        def _iter_value_sources():
            # Start from the caller scope so positional fallbacks use the current scope's
            # bindings in insertion order (a, b, want, ...), then fall back to closures.
            yield scope
            if isinstance(func, SlipFunction):
                cl = getattr(func, "closure", None)
                if isinstance(cl, Scope):
                    yield cl
            elif isinstance(func, GenericFunction):
                for m in func.methods:
                    cl = getattr(m, "closure", None)
                    if isinstance(cl, Scope):
                        yield cl

        # Helper: collect the first N non-function, non-path values from sources
        def _collect_fallback_args(n: int):
            """
            Collect candidate argument values from available sources, preferring
            the most recently-bound user values over core/library bindings.

            Filters out:
              - functions and generic function containers,
              - any path-like placeholders (operators, path literals, etc.),
              - signature objects (Sig), which are metadata/type aliases.
            """
            from slip.slip_runtime import _ResponseView as _RV

            args_out: list = []
            seen: set = set()
            for src in _iter_value_sources():
                if not isinstance(src, Scope):
                    continue
                # Use insertion order (caller code order)
                items = list(src.bindings.items())
                for k, v in items:
                    # Skip callables and function containers
                    if isinstance(v, (SlipFunction, GenericFunction)) or callable(v):
                        continue
                    # Skip the live response-view object
                    if isinstance(v, _RV):
                        continue
                    # Skip path-like placeholders (operators, path literals, etc.)
                    if isinstance(v, (_GP, _SP, _DP, _PP, _PL, _MSP)):
                        continue
                    # Skip signature objects used for typing/aliases
                    if isinstance(v, Sig):
                        continue
                    # Skip scopes and mapping-like values (prototypes, dicts, module scopes, etc.)
                    if isinstance(v, (Scope, collections.abc.Mapping)):
                        continue
                    # Avoid duplicates by identity
                    if id(v) in seen:
                        continue
                    seen.add(id(v))
                    args_out.append(v)
                    if len(args_out) >= n:
                        return args_out
            return args_out

        passed = 0
        failures = []
        for i, ex in enumerate(examples):
            if not isinstance(ex, Sig):
                continue

            # Build args: prefer keyword declaration order; else positional fallback
            args = []
            if ex.keywords:
                for k in ex.keywords.keys():
                    val_spec = ex.keywords[k]
                    args.append(await _resolve(val_spec))
            elif ex.positional:
                # Try to resolve each positional name from the caller scope
                resolved = []
                failed = False
                for pname in ex.positional:
                    try:
                        val = await self.evaluator._eval(GetPath([Name(pname)]), scope)
                        resolved.append(val)
                    except Exception:
                        failed = True
                        break
                if failed:
                    # Fallback: draw values from function closures first, then caller scope.
                    resolved = _collect_fallback_args(len(ex.positional))
                args.extend(resolved)

            expected = await _resolve(ex.return_annotation)

            try:
                actual = await self.evaluator.call(func, args, scope)
            except Exception as e:
                failures.append({"index": i, "err": str(e)})
                continue

            if actual == expected:
                passed += 1
            else:
                failures.append({"index": i, "expected": expected, "actual": actual})

        if failures:
            return Response(_status("err"), failures)
        return Response(_status("ok"), passed)

    async def _test_all(self, *targets, scope: Scope):
        from slip.slip_datatypes import SlipFunction, GenericFunction

        def _status(name: str):
            if name == "ok":
                return _OK_STATUS
            if name == "err":
                return _ERR_STATUS
            from slip.slip_datatypes import (
                PathLiteral as _PL,
                GetPath as _GP,
                Name as _Name,
            )

            return _PL(_GP([_Name(name)]))

        # Determine scopes to scan; default to current lexical scope
        scopes = [s for s in targets if isinstance(s, Scope)] or [scope]

        scanned = []
        for s in scopes:
            # Scan only the current scope’s own bindings (no parent chain)
            for name, val in s.bindings.items():
                if isinstance(val, (SlipFunction, GenericFunction)):
                    scanned.append((name, val))

        total_with_examples = 0
        passed_count = 0
        failed_details = []

        for name, fn in scanned:
            meta = getattr(fn, "meta", {}) or {}
            has_examples = bool(meta.get("examples"))
            if isinstance(fn, GenericFunction) and not has_examples:
                has_examples = any(
                    getattr(m, "meta", {}).get("examples") for m in fn.methods
                )
            if not has_examples:
                continue

            total_with_examples += 1
            try:
                res = await self._test(fn, scope=scope)
            except Exception as e:
                failed_details.append({"name": name, "err": str(e)})
                continue
            if res.status == _status("ok"):
                passed_count += 1
            else:
                failed_details.append({"name": name, "failures": res.value})

        summary = {
            "scanned": len(scanned),
            "with-examples": total_with_examples,
            "passed": passed_count,
            "failed": len(failed_details),
            "details": failed_details,
        }
        status = _OK_STATUS if not failed_details else _ERR_STATUS
        return Response(status, summary)

    async def _call(self, target, args_list=None, *, scope: Scope):
        """
        call <path-literal|string|path> #[args...]
        - If target is a string, it is parsed into a path.
        - If the path is a SetPath (`y:`), performs assignment of args_list[0].
        - If the path is a DelPath (`~y`), performs deletion.
        - If the path is a GetPath, it is resolved. If the result is callable, it is invoked.
        """
        from slip.slip_datatypes import (
            PathLiteral as _PL,
            GetPath as _GP,
            SetPath as _SP,
            DelPath as _DP,
            IString as _IStr,
            SlipFunction as _SF,
            GenericFunction as _GF,
        )

        # 1. Normalize target to a path object (GetPath, SetPath, or DelPath)
        path_obj = target
        if isinstance(target, _PL):
            path_obj = target.inner
        elif isinstance(target, (str, _IStr)):
            s = str(target).strip()
            if s.startswith("~"):
                path_obj = _DP(self._to_getpath(s[1:]))
            elif s.endswith(":"):
                inner_gp = self._to_getpath(s[:-1])
                path_obj = _SP(inner_gp.segments, getattr(inner_gp, "meta", None))
            else:
                path_obj = self._to_getpath(s)

        # 2. Handle the path object semantics
        args = args_list if args_list is not None else []

        match path_obj:
            case _SP():
                if args_list is None:
                    return path_obj
                if len(args) != 1:
                    raise TypeError("call on a set-path requires exactly one argument")
                await self.evaluator.path_resolver.set(path_obj, args[0], scope)
                return args[0]

            case _DP():
                if args and len(args) != 0:
                    raise TypeError("call on a del-path does not take arguments")
                await self.evaluator.path_resolver.delete(path_obj, scope)
                return None

            case _GP():
                try:
                    val = await self.evaluator.path_resolver.get(path_obj, scope)
                except Exception:
                    return _PL(path_obj) if not isinstance(target, _PL) else target

                if isinstance(val, (_SF, _GF)) or callable(val):
                    return await self.evaluator.call(val, args, scope)

                if not args:
                    return val
                raise TypeError(
                    f"Path {path_obj.to_str_repr()} resolved to non-callable {type(val).__name__}"
                )

            case _:
                # If it's already a callable value, just call it
                if isinstance(target, (_SF, _GF)) or callable(target):
                    return await self.evaluator.call(target, args, scope)
                raise TypeError(
                    f"call expects a path or callable, got {type(target).__name__}"
                )


# ===================================================================
# 5. Script Execution
# ===================================================================

Token = Dict[str, Any]

from typing import Any, Optional, List, Dict


@dataclass
class Outcome:
    """
    Unified script outcome object visible to both the host (ExecutionResult)
    and to running scripts via `outcome` in the root scope.
    Fields:
      - status: a PathLiteral (e.g., `ok`/`err`) or None
      - value: payload (any)
      - effects: a reference to evaluator.side_effects (list)
      - error: optional dict { 'message': str, 'token': dict | None }
      - stacktrace: structured stack frames (list)
    """

    status: Any = None
    value: Any = None
    effects: List[Dict] = field(default_factory=list)
    error: Optional[Dict] = None
    stacktrace: List[Dict] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """The structured result of a script execution.

    Spec:
      - slip_status is the round-trippable SLIP status marker string (e.g. "`ok`", "`err`")
      - status is the plain host string derived from slip_status ("ok"/"err")
      - value is host-normalized output (may include backticks for PathLiteral round-trip)
      - slip_result retains the un-normalized SLIP result value (may contain SLIP datatypes)
    """

    slip_status: str
    value: Any = None
    error_message: Optional[str] = None
    error_token: Optional[Token] = None
    side_effects: List[Dict] = field(default_factory=list)

    # Original, un-normalized SLIP result value (may contain SLIP datatypes).
    slip_result: Any = None

    @property
    def status(self) -> Literal["ok", "err"]:
        s = (self.slip_status or "").strip()
        if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
            s = s[1:-1].strip()
        return "err" if s == "err" else "ok"

    def format_error(self) -> str:
        """Formats an error message with line and column if available."""
        if self.status != "err":
            return ""
        msg = str(self.error_message or "Unknown error")

        # Add a location prefix when we have a token; avoid duplicating the same prefix
        if self.error_token and "line" in self.error_token:
            line = self.error_token.get("line")
            col = self.error_token.get("col")
            if not msg.startswith("Error on line "):
                col_info = f", col {col}" if col is not None else ""
                return f"Error on line {line}{col_info}: {msg}"
        return msg


class ScriptRunner:
    """Parses, transforms, and executes SLIP code."""

    def _host_normalize(self, v: Any) -> Any:
        """Convert SLIP runtime datatypes into plain Python datatypes for host results."""
        from slip.slip_datatypes import (
            PathLiteral as _PL,
            GetPath as _GP,
            Name as _Name,
            Response as _Resp,
        )
        from slip.slip_runtime import SlipDict as _SlipDict

        # Realize internal lazy selections/views at the host boundary.
        try:
            if hasattr(v, "realize") and callable(getattr(v, "realize")):
                v = v.realize()
        except Exception:
            pass

        # Realize internal lazy selections/views at the host boundary.
        try:
            if hasattr(v, "realize") and callable(getattr(v, "realize")):
                v = v.realize()
        except Exception:
            pass

        # Responses are SLIP datatypes; normalize to a plain dict for host usage.
        # Host contract: response.status is a plain string ("ok"/"err"/...), not a backticked PathLiteral string.
        if isinstance(v, _Resp):
            st = self._host_normalize(v.status)
            if isinstance(st, str) and len(st) >= 2 and st[0] == "`" and st[-1] == "`":
                st = st[1:-1]
            return {
                "status": st,
                "value": self._host_normalize(v.value),
            }

        # PathLiteral -> string form.
        # IMPORTANT: preserve full SLIP source-ish representation so it can round-trip
        # (including backticks + meta), e.g. `a#(flag: true)`.
        #
        # No special-casing here; host conveniences should live on ExecutionResult.
        if isinstance(v, _PL):
            try:
                return v.to_str_repr()
            except Exception:
                return str(v)

        # SlipDict -> plain dict
        if isinstance(v, _SlipDict):
            return {str(k): self._host_normalize(val) for k, val in v.items()}

        # Scope -> plain dict of current bindings
        try:
            from slip.slip_datatypes import Scope as _Scope

            if isinstance(v, _Scope):
                return {
                    str(k): self._host_normalize(val) for k, val in v.bindings.items()
                }
        except Exception:
            pass

        if isinstance(v, list):
            return [self._host_normalize(x) for x in v]
        if isinstance(v, tuple):
            return tuple(self._host_normalize(x) for x in v)
        if isinstance(v, dict):
            return {str(k): self._host_normalize(val) for k, val in v.items()}

        return v

    _parser: Optional[Parser] = None
    _transformer: Optional[SlipTransformer] = None
    _core_loaded_ast: Optional[Code] = None
    _core_source: Optional[str] = None

    def _format_parse_error(self, parse_out, source: str) -> str:
        node = (parse_out or {}).get("error_node") or {}
        base = (parse_out or {}).get("error_message") or str(parse_out)
        line = node.get("line")
        col = node.get("col")
        if line is not None and col is not None:
            return f"ParseError: {base} (line {line}, col {col})\n{self._source_context(source, line, col)}"
        return f"ParseError: {base}"

    def _format_runtime_error(self, e, source: str, node) -> tuple[str, Optional[dict]]:
        is_syntax = False
        match e:
            case SyntaxError():
                is_syntax = True
                msg = f"SyntaxError: {str(e)}"
            case PathNotFound() as pn:
                msg = f"PathNotFound: {pn.key}"
            case KeyError(inner):
                if isinstance(inner, str):
                    stripped = inner
                    if len(stripped) >= 2 and (
                        (stripped[0] == stripped[-1] == "'")
                        or (stripped[0] == stripped[-1] == '"')
                    ):
                        stripped = stripped[1:-1]
                    detail = stripped
                else:
                    detail = str(inner)
                msg = f"PathNotFound: {detail}"
            case TypeError() | AttributeError():
                call_name = None
                try:
                    if getattr(self.evaluator, "call_stack", None):
                        call_name = self.evaluator.call_stack[-1].get("name")
                except Exception:
                    call_name = None
                safe_name = None
                if isinstance(call_name, str) and call_name not in ("return", "<call>"):
                    safe_name = call_name.lstrip("_").replace("_", "-")
                msg = "TypeError: invalid-args" + (
                    f" in ({safe_name})" if safe_name else ""
                )
                # NEW: append dispatch detail if provided by the exception
                detail = getattr(e, "slip_detail", None)
                if isinstance(detail, str) and detail:
                    msg = f"{msg}\n{detail}"
            case _:
                # Preserve the underlying exception type to make errors self-teaching.
                msg = f"{type(e).__name__}: {str(e)}"

        # Pretty-print an attached SLIP object (prefer offender term, if provided)
        slip_obj = getattr(e, "slip_obj", None)
        if slip_obj is not None:
            try:
                from slip.slip_printer import Printer

                rendered = Printer().pformat(slip_obj)
            except Exception:
                rendered = repr(slip_obj)
            # Avoid multiple colons; include a label only for syntax errors
            if is_syntax:
                msg = f"{msg}\nOffending {rendered}"
            else:
                msg = f"{msg}\n{rendered}"

        token = None
        try:
            # Prefer the offending object's loc if present; fallback to current node
            offender = slip_obj if slip_obj is not None else node
            loc = getattr(offender, "loc", None) if offender is not None else None

            # Fallback: use the last call frame's call-site location (best-effort).
            if not (loc and isinstance(loc, dict)):
                try:
                    stack = getattr(self.evaluator, "call_stack", None) or []
                    if stack:
                        loc = stack[-1].get("call_site")
                except Exception:
                    loc = None

            if loc and isinstance(loc, dict):
                line = loc.get("line")
                col = loc.get("col")
                token = {
                    "line": line,
                    "col": col,
                    "tag": loc.get("tag"),
                    "text": loc.get("text"),
                }

                if line is not None:
                    # Preserve prior tests expecting a caret context marker (^)
                    # by including the multi-line source context with caret when column is known,
                    # and also include the exact source line as a compact snippet.
                    msg = f"{msg} in line {line}"
                    src_line = self._source_line(source, line)
                    if src_line:
                        msg = f"{msg}\n---\n{src_line}"
                    if col is not None:
                        msg = f"{msg}\n{self._source_context(source, line, col)}"
        except Exception:
            pass

        # Append SLIP stacktrace if available
        st = self._format_stacktrace()
        if st:
            msg += "\n" + st

        return msg, token

    def _source_context(
        self, source: str, line: int, col: Optional[int], radius: int = 2
    ) -> str:
        lines = source.splitlines()
        if not line or line < 1 or line > len(lines):
            return ""
        start = max(1, line - radius)
        end = min(len(lines), line + radius)
        width = len(str(end))
        out = []
        for i in range(start, end + 1):
            prefix = ">" if i == line else " "
            ln = str(i).rjust(width)
            content = lines[i - 1]
            out.append(f"{prefix} {ln} | {content}")
            if i == line and col is not None:
                caret = " " * max(col - 1, 0)
                out.append(f"  {' ' * width} | {caret}^")
        return "\n".join(out)

    def _source_line(self, source: str, line: int) -> str:
        lines = source.splitlines()
        if not line or line < 1 or line > len(lines):
            return ""
        return lines[line - 1]

    def _source_line(self, source: str, line: int) -> str:
        lines = source.splitlines()
        if not line or line < 1 or line > len(lines):
            return ""
        return lines[line - 1]

    def _format_stacktrace(self) -> str:
        stack = getattr(self.evaluator, "call_stack", None) or []
        if not stack:
            return ""
        try:
            from slip.slip_printer import Printer

            pf = Printer().pformat
        except Exception:
            pf = repr

        import inspect

        try:
            from slip.slip_datatypes import (
                Code as _Code,
                SlipFunction as _SlipFn,
                Sig as _Sig,
            )
        except Exception:
            _Code = tuple()
            _SlipFn = tuple()
            _Sig = tuple()

        def friendly_callable_name(fn):
            try:
                if (
                    inspect.ismethod(fn)
                    and getattr(fn.__self__, "__class__", None).__name__ == "StdLib"
                ):
                    n = getattr(fn, "__name__", "") or ""
                    return n.lstrip("_").replace("_", "-")
                n = getattr(fn, "__name__", None)
                if isinstance(n, str) and n:
                    return n
            except Exception:
                pass
            return "<callable>"

        def fmt(arg):
            try:
                match arg:
                    case None:
                        return "none"
                    case bool() | int() | float() | str():
                        return pf(arg) if callable(pf) else repr(arg)

                # Prefer printing runtime path datatypes (GetPath/PipedPath/etc.) verbatim so
                # stack traces preserve surface syntax like `|div`.
                #
                # This fixes cases where a piped operator was previously formatted as just its
                # underlying name (e.g., `div`), losing the pipe marker.
                from slip.slip_datatypes import (
                    GetPath as _GP,
                    SetPath as _SP,
                    DelPath as _DP,
                    PipedPath as _PP,
                    PathLiteral as _PL,
                    PostPath as _PostP,
                    MultiSetPath as _MSP,
                )

                if isinstance(arg, (_GP, _SP, _DP, _PP, _PL, _PostP, _MSP)):
                    return pf(arg)

                # Runtime datatypes that require isinstance checks
                if _Code and isinstance(arg, _Code):
                    return "[]"
                if _SlipFn and isinstance(arg, _SlipFn):
                    return "fn"
                if _Sig and isinstance(arg, _Sig):
                    return "Sig"
                if inspect.ismethod(arg) or inspect.isfunction(arg) or callable(arg):
                    return friendly_callable_name(arg)
                match arg:
                    case list():
                        return f"#[{len(arg)}]"
                    case dict():
                        return "#{...}"
                    case _:
                        return pf(arg)
            except Exception:
                return repr(arg)

        frames = []
        for frame in stack:
            surface = frame.get("surface")
            if isinstance(surface, str) and surface.strip():
                frames.append(surface.strip())
                continue

            # Next-best: raw call-site token text from the parser/transformer.
            call_site = frame.get("call_site") or {}
            call_text = call_site.get("text") if isinstance(call_site, dict) else None
            if isinstance(call_text, str) and call_text.strip():
                frames.append(call_text.strip())
                continue

            # Last resort: name only (still not a value/IR rendering with args)
            name = frame.get("name") or "<call>"
            frames.append(str(name))

        return "SLIP stacktrace: " + " ".join(frames)

    def __init__(
        self,
        host_object: Optional["SLIPHost"] = None,
        host_data=None,
        load_core: bool = True,
    ):
        self.host_object = host_object
        self.host_data = host_data
        self._initialized = False
        self.root_scope = Scope()
        self._load_core = load_core
        self.source_dir = None  # directory of the current source file, if known

        if ScriptRunner._parser is None:
            # TODO: This path is brittle. A package resource approach would be better.
            grammar_path = (
                Path(__file__).parent.parent / "grammar" / "slip_grammar.yaml"
            )
            ScriptRunner._parser = Parser.from_file(str(grammar_path))

        if ScriptRunner._transformer is None:
            ScriptRunner._transformer = SlipTransformer()

        self.parser = ScriptRunner._parser
        self.transformer = ScriptRunner._transformer

        self.evaluator = Evaluator()  # Each runner has its own evaluator/side_effects
        # Make the runner root scope discoverable to stdlib helpers like `run`,
        # so sandboxed execution still sees root.slip bindings (e.g. '+').
        self.evaluator.root_scope = self.root_scope
        # The evaluator needs access to the host object to correctly implement `task`
        if host_object:
            self.evaluator.host_object = host_object
        self.evaluator.host_data_loader = host_data
        self.evaluator.host_object_cache = {}
        self.evaluator.host_rehydrate_cache = {}

        # Load stdlib
        stdlib = StdLib(self.evaluator)
        # Make stdlib discoverable to interpreter helpers (e.g. cell input resolution).
        self.evaluator.stdlib = stdlib
        for name, member in inspect.getmembers(stdlib):
            if name.startswith("_") and not name.startswith("__") and callable(member):
                slip_name = name[1:].replace("_", "-")
                self.root_scope[slip_name] = member
                # Provide stable core- aliases for operators to avoid shadowing by user-defined functions
                core_name = f"core-{slip_name}"
                self.root_scope[core_name] = member
                # Also expose predicate aliases ending with '-q' as '?' (e.g., has-key?).
                if slip_name.endswith("-q"):
                    q_alias = slip_name[:-2] + "?"
                    self.root_scope[q_alias] = member
                    self.root_scope[f"core-{q_alias}"] = member

        # Bind a live, read-only response view for scripts
        self.root_scope["outcome"] = _ResponseView(self.evaluator)
        # Track which host API names we have bound into the root scope
        self._host_api_names: set[str] = set()

    async def _initialize(self):
        """Loads core.slip into the root scope if not already loaded."""
        if self._initialized or not self._load_core:
            self._initialized = True
            return

        # AST is parsed once and cached on the class
        if ScriptRunner._core_loaded_ast is None:
            core_slip_path = Path(__file__).parent / "root.slip"
            if core_slip_path.exists():
                try:
                    core_source = core_slip_path.read_text()
                    ScriptRunner._core_source = core_source
                    parse_out = self.parser.parse(core_source)
                    # Normalize external parser vocabulary to unified 'ok'/'err'
                    if isinstance(parse_out, dict) and "status" in parse_out:
                        st = parse_out.get("status")
                        if st == "success":
                            parse_out["status"] = "ok"
                        elif st == "error":
                            parse_out["status"] = "err"
                    if isinstance(parse_out, dict) and "status" in parse_out:
                        if parse_out.get("status") != "ok":
                            err = self._format_parse_error(parse_out, core_source)
                            raise RuntimeError(f"Failed to parse root.slip:\n{err}")
                        ast_node = parse_out["ast"]
                    else:
                        ast_node = parse_out
                    ScriptRunner._core_loaded_ast = self.transformer.transform(ast_node)
                except RuntimeError:
                    # Re-raise our own formatted parse error without re-wrapping.
                    raise
                except Exception as e:
                    # Re-raise other exceptions with context for upstream error reporting
                    raise RuntimeError(f"Error loading root.slip: {e}") from e

        # Evaluation happens for each instance
        if ScriptRunner._core_loaded_ast:
            # Prevent Evaluator._ensure_core_loaded from loading root.slip into core_scope
            # before we evaluate root.slip into the real root_scope.
            self.evaluator._core_loaded = True
            prev_src = self.evaluator.current_source
            self.evaluator.current_source = "core"
            try:
                await self.evaluator.eval(
                    ScriptRunner._core_loaded_ast.nodes, self.root_scope
                )
            finally:
                self.evaluator.current_source = prev_src
            # Optional: annotate root scope to indicate core was loaded
            try:
                self.root_scope.meta["_root_loaded"] = True
            except Exception:
                pass

        self._initialized = True

    def _bind_host_api_methods(self):
        """Bind @slip_api_method methods of the host into the root scope (kebab-case)."""
        # Remove any previously bound host API names to refresh cleanly
        for n in list(getattr(self, "_host_api_names", set())):
            try:
                del self.root_scope[n]
            except Exception:
                pass
        self._host_api_names = set()

        host = self.host_object
        if not host:
            return

        import inspect

        for name, member in inspect.getmembers(host):
            if not callable(member):
                continue
            # Decorator may mark the bound method or the underlying function
            is_api = getattr(member, "_is_slip_api", False)
            if not is_api:
                func = getattr(member, "__func__", None)
                if func is not None:
                    is_api = getattr(func, "_is_slip_api", False)
            if not is_api:
                continue
            slip_name = name.replace("_", "-")
            self.root_scope[slip_name] = member
            self._host_api_names.add(slip_name)

    async def handle_script(self, source_code: str) -> "ExecutionResult":
        """The main entry point to execute a script."""
        try:
            # Clear side effects for each run
            self.evaluator.side_effects.clear()
            self.evaluator.call_stack.clear()
            self._current_script_source = source_code
            self.evaluator.current_source = "script"
            # Ensure evaluator has the current host for task registration each run
            self.evaluator.host_object = self.host_object
            self.evaluator.host_data_loader = self.host_data
            self.evaluator.host_object_cache = {}
            self.evaluator.host_rehydrate_cache = {}
            # Make source_dir available for file:// resolution; default to CWD when unknown
            import os as _os

            self.evaluator.source_dir = self.source_dir or _os.getcwd()
            # Initialize per-run unified Outcome object
            init_status = _OK_STATUS
            # Ensure side_effects list is used as the effects reference
            self.evaluator.outcome = Outcome(
                status=init_status,
                value=None,
                effects=self.evaluator.side_effects,
                error=None,
                stacktrace=[],
            )
            await self._initialize()
            # Bind host API methods after core is loaded so host > root.slip > native
            self._bind_host_api_methods()
            # 1. Parse
            try:
                parse_out = self.parser.parse(source_code)
                # Normalize external parser vocabulary to unified 'ok'/'err'
                if isinstance(parse_out, dict) and "status" in parse_out:
                    st = parse_out.get("status")
                    if st == "success":
                        parse_out["status"] = "ok"
                    elif st == "error":
                        parse_out["status"] = "err"
            except Exception:
                msg = "ParseError: parse failed"
                self.evaluator.side_effects.append(
                    {"topics": ["stderr"], "message": msg}
                )
                return ExecutionResult(
                    slip_status="`err`",
                    error_message=msg,
                    side_effects=self.evaluator.side_effects,
                    slip_result=None,
                )

            if isinstance(parse_out, dict) and "status" in parse_out:
                if parse_out.get("status") != "ok":
                    msg = self._format_parse_error(parse_out, source_code)
                    self.evaluator.side_effects.append(
                        {"topics": ["stderr"], "message": msg}
                    )
                    return ExecutionResult(
                        slip_status="`err`",
                        error_message=msg,
                        error_token=parse_out.get("error_node"),
                        side_effects=self.evaluator.side_effects,
                        slip_result=None,
                    )
                # success
                ast_node = parse_out.get("ast")
                if ast_node is None:
                    # Defensive: if a success wrapper comes without ast, treat as fatal parse anomaly
                    msg = "Parse error: missing AST in parser result"
                    self.evaluator.side_effects.append(
                        {"topics": ["stderr"], "message": msg}
                    )
                    return ExecutionResult(
                        slip_status="`err`",
                        error_message=msg,
                        side_effects=self.evaluator.side_effects,
                        slip_result=None,
                    )
            else:
                ast_node = parse_out

            # 2. Transform
            try:
                transformed_ast = self.transformer.transform(ast_node)
            except SyntaxError as e:
                # Preserve contract-level syntax errors thrown by the transformer
                msg, tok = self._format_runtime_error(
                    e, source_code, getattr(self.evaluator, "current_node", None)
                )
                self.evaluator.side_effects.append(
                    {"topics": ["stderr"], "message": msg}
                )
                return ExecutionResult(
                    slip_status="`err`",
                    error_message=msg,
                    error_token=tok,
                    side_effects=self.evaluator.side_effects,
                    slip_result=None,
                )
            except Exception:
                msg = "InternalError: transform failed"
                self.evaluator.side_effects.append(
                    {"topics": ["stderr"], "message": msg}
                )
                return ExecutionResult(
                    slip_status="`err`",
                    error_message=msg,
                    side_effects=self.evaluator.side_effects,
                    slip_result=None,
                )

            # 3. Evaluate
            # We call the internal _eval to prevent 'return' responses from being unwrapped.
            result = await self.evaluator._eval(transformed_ast.nodes, self.root_scope)

            # If the script returned an asyncio.Task (from 'task [ ... ]'),
            # ensure it is registered with the current host for lifecycle management.
            try:
                if isinstance(result, asyncio.Task):
                    host = self.host_object
                    if host is not None and hasattr(host, "_register_task"):
                        host._register_task(result)
                    elif host is not None and hasattr(host, "active_slip_tasks"):
                        host.active_slip_tasks.add(result)
                        try:
                            loop = asyncio.get_event_loop()
                        except Exception:
                            loop = None

                        def _done_cb_host(_t: asyncio.Task):
                            try:
                                if loop is not None and loop.is_running():
                                    loop.call_soon_threadsafe(
                                        host.active_slip_tasks.discard, _t
                                    )
                                else:
                                    host.active_slip_tasks.discard(_t)
                            except Exception:
                                try:
                                    host.active_slip_tasks.discard(_t)
                                except Exception:
                                    pass

                        result.add_done_callback(_done_cb_host)
            except Exception:
                pass

            # Best-effort pruning of completed tasks from host tracker to avoid races
            try:
                host = getattr(self, "host_object", None)
                if host is not None and hasattr(host, "active_slip_tasks"):
                    for t in list(host.active_slip_tasks):
                        try:
                            if getattr(t, "done", None) and t.done():
                                host.active_slip_tasks.discard(t)
                        except Exception:
                            pass
            except Exception:
                pass

            # Mirror final result into the unified outcome object (status ok, value = final value)
            # If execution signaled a ReturnSignal, use its payload as the final value.
            # Responses are data; other values are treated as final value.
            if isinstance(result, ReturnSignal):
                final_val = result.value
            elif isinstance(result, Response):
                final_val = result
            else:
                final_val = result
            try:
                out = getattr(self.evaluator, "outcome", None)
                if isinstance(out, Outcome):
                    out.status = _OK_STATUS
                    out.value = final_val
                    out.stacktrace = []
                    out.error = None
            except Exception:
                pass

            # If evaluation produced a ReturnSignal, treat it as an early-exit and
            # return its payload as the host-level successful result.
            if isinstance(result, ReturnSignal):
                return ExecutionResult(
                    slip_status="`ok`",
                    value=self._host_normalize(result.value),
                    side_effects=self.evaluator.side_effects,
                    slip_result=result.value,
                )

            # Responses are returned as data values; normal final value otherwise.
            if isinstance(result, Response):
                return ExecutionResult(
                    slip_status="`ok`",
                    value=self._host_normalize(result),
                    side_effects=self.evaluator.side_effects,
                    slip_result=result,
                )

            return ExecutionResult(
                slip_status="`ok`",
                value=self._host_normalize(result),
                side_effects=self.evaluator.side_effects,
                slip_result=result,
            )

        except Exception as e:
            node = getattr(self.evaluator, "current_node", None)
            err_msg, err_token = self._format_runtime_error(e, source_code, node)
            # Emit consolidated stderr side-effect
            self.evaluator.side_effects.append(
                {"topics": ["stderr"], "message": err_msg}
            )
            # Mirror error into the unified outcome object (status err, include error details)
            try:
                out = getattr(self.evaluator, "outcome", None)
                if isinstance(out, Outcome):
                    out.status = _ERR_STATUS
                    out.value = err_msg
                    out.stacktrace = []
                    out.error = {"message": err_msg, "token": err_token}
            except Exception:
                pass
            return ExecutionResult(
                slip_status="`err`",
                error_message=err_msg,
                error_token=err_token,
                side_effects=self.evaluator.side_effects,
                slip_result=None,
            )
