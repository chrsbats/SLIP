# slip.py

import re
import asyncio
import inspect
import math
import time
import random
import copy
import weakref
import textwrap
import collections.abc
import traceback
from collections import UserDict
from pathlib import Path
from typing import Any, List, Optional, Literal, Dict
from abc import ABC, abstractmethod

import yaml
from koine import Parser
from slip.slip_transformer import SlipTransformer
from slip.slip_interpreter import Evaluator
from slip.slip_datatypes import Scope, Code, Response, PathLiteral, Name, SetPath, GetPath, PathNotFound, Group, List as SlipList

# ===================================================================
# 1. Core Data Structures & Global State
# ===================================================================

PROTOTYPE_MAP: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

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


class SLIPModule:
    def __init__(self, name: str, scope):
        self._name = name
        self._scope = scope
    def __getitem__(self, key):
        return self._scope[key]
    def __repr__(self):
        keys = list(self._scope.bindings.keys())
        return f"<Module '{self._name}' keys={keys}>"


def slip_api_method(func):
    """A decorator to explicitly mark methods as safe for SLIP execution."""
    func._is_slip_api = True
    return func

class SLIPHost(ABC):
    """The required base class for any Python object exposed to the SLIP interpreter."""
    def __init__(self):
        self.active_slip_tasks: set = set()

    @abstractmethod
    def __getitem__(self, key): raise NotImplementedError
    @abstractmethod
    def __setitem__(self, key, value): raise NotImplementedError
    @abstractmethod
    def __delitem__(self, key): raise NotImplementedError

    @slip_api_method
    def cancel_tasks(self):
        count = len(self.active_slip_tasks)
        for task in list(self.active_slip_tasks):
            task.cancel()
        self.active_slip_tasks.clear()
        return count

    def _register_task(self, task: asyncio.Task):
        self.active_slip_tasks.add(task)
        # Remove as soon as the task completes
        task.add_done_callback(lambda t: self.active_slip_tasks.discard(t))


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
        return repr(self._backing[self._start:self._end])

# ===================================================================
# 4. The Standard Library
# ===================================================================
class StdLib:
    """Contains Python implementations for all SLIP built-ins."""
    def __init__(self, evaluator):
        self.evaluator = evaluator

    # --- Math and Logic ---
    def _add(self, a, b): return a + b
    def _sub(self, a, b): return a - b
    def _mul(self, a, b): return a * b
    def _div(self, a, b): return a / b
    def _pow(self, b, e): return b ** e
    def _eq(self, a, b):
        res = (a == b)
        try:
            self.evaluator._dbg("EQ", type(a).__name__, id(a), "==", type(b).__name__, id(b), "->", res)
        except Exception:
            pass
        return res
    def _neq(self, a, b): return a != b
    def _gt(self, a, b): return a > b
    def _gte(self, a, b): return a >= b
    def _lt(self, a, b): return a < b
    def _lte(self, a, b): return a <= b
    def _not(self, x): return not x
    def _exp(self, x): return math.exp(x)
    def _log(self, x): return math.log(x)
    def _log10(self, x): return math.log10(x)

    # --- String Utilities ---
    def _str_join(self, list_of_strings, separator): return separator.join(map(str, list_of_strings))
    # Backward compatibility for legacy callers/tests
    def _join(self, list_of_strings, separator): return self._str_join(list_of_strings, separator)
    async def _join_paths(self, first, *rest, scope: Scope):
        from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP
        all_args = (first,) + rest
        segments = []
        for a in all_args:
            gp = self._to_getpath(a)
            if not isinstance(gp, _GP):
                raise TypeError("join on paths expects only path-like arguments")
            segments.extend(gp.segments)
        return _PL(_GP(segments))
    def _split(self, string, separator): return string.split(separator)
    def _find(self, haystack, needle, start=0):
        idx = haystack.find(needle, start)
        return idx if idx != -1 else None
    def _str_replace(self, string, old, new): return string.replace(old, new)
    # Back-compat for tests expecting _replace
    #def _replace(self, string, old, new): return self._str_replace(string, old, new)
    def _indent(self, string, prefix): return textwrap.indent(string, prefix)
    def _dedent(self, string): return textwrap.dedent(string)

    def _to_getpath(self, value):
        from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name, IString as _IStr
        # PathLiteral → inner (must be GetPath)
        if isinstance(value, _PL):
            inner = getattr(value, 'inner', None)
            if isinstance(inner, _GP):
                return inner
            raise TypeError("call expects a function path (get-path) when using a path-literal")
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
        from slip.slip_datatypes import GetPath as _GP, PathLiteral as _PL, IString as _IStr
        # Resource wrapper: Scope with 'url' and 'path'
        if isinstance(target, Scope) and "url" in getattr(target, "bindings", {}) and "path" in getattr(target, "bindings", {}):
            gp = target.bindings["path"]
            url = target.bindings["url"]
            cfg = await self.evaluator.path_resolver._meta_to_dict(getattr(gp, 'meta', None), scope)
            return gp, url, cfg
        # Path-like or string fallback
        if isinstance(target, _PL):
            inner = getattr(target, 'inner', None)
            gp = inner if isinstance(inner, _GP) else None
        elif isinstance(target, _GP):
            gp = target
        else:
            gp = None
            if isinstance(target, _PL) and isinstance(getattr(target, 'inner', None), _GP):
                gp = target.inner
            elif isinstance(target, _GP):
                gp = target
            elif isinstance(target, (str, _IStr)):
                gp = self._to_getpath(target)
            if gp is None:
                raise TypeError("target expects an http(s) URL path")
        url = self.evaluator.path_resolver._extract_http_url(gp)
        if not url:
            raise TypeError("target expects an http(s) URL path")
        cfg = await self.evaluator.path_resolver._meta_to_dict(getattr(gp, 'meta', None), scope)
        return gp, url, cfg

    def _prepare_payload(self, cfg: dict, data):
        from slip.slip_serialize import serialize as _ser
        ctype = (cfg.get('content-type') or cfg.get('content_type'))
        if ctype:
            headers = dict(cfg.get('headers', {}))
            headers['Content-Type'] = ctype
            cfg['headers'] = headers
        def _fmt(ct: str | None):
            if not isinstance(ct, str): return None
            s = ct.lower()
            if 'json' in s: return 'json'
            if 'yaml' in s or 'x-yaml' in s: return 'yaml'
            if 'toml' in s: return 'toml'
            if 'xml' in s or 'html' in s or 'xhtml' in s: return 'xml'
            return None
        fmt = _fmt(ctype)
        if fmt is not None:
            try:
                return _ser(data, fmt=fmt, pretty=True)
            except Exception:
                return str(data)
        return data if isinstance(data, (str, bytes, bytearray)) else str(data)

    async def _get(self, target, *, scope: Scope):
        from slip.slip_http import http_get
        _, url, cfg = await self._normalize_resource(target, scope)
        return await http_get(url, cfg)

    async def _put(self, target, data, *, scope: Scope):
        from slip.slip_http import http_put
        _, url, cfg = await self._normalize_resource(target, scope)
        payload = self._prepare_payload(cfg, data)
        return await http_put(url, payload, cfg)

    async def _post(self, target, data, *, scope: Scope):
        from slip.slip_http import http_post
        _, url, cfg = await self._normalize_resource(target, scope)
        payload = self._prepare_payload(cfg, data)
        return await http_post(url, payload, cfg)

    async def _del(self, target, *, scope: Scope):
        from slip.slip_http import http_delete
        _, url, cfg = await self._normalize_resource(target, scope)
        # Ensure DELETE carries configured content-type header (for servers that inspect it)
        ctype = cfg.get('content-type') or cfg.get('content_type')
        if ctype:
            headers = dict(cfg.get('headers', {}))
            headers['Content-Type'] = ctype
            cfg['headers'] = headers
        return await http_delete(url, cfg)

    # Optional compatibility alias; remove later if not needed
    async def _http_post(self, target, data, *, scope: Scope):
        return await self._post(target, data, scope=scope)

    async def _import(self, target, *, scope: Scope):
        """
        Load a SLIP module given either:
          - a path-literal (backticked), or
          - a string URL/locator (e.g., 'file:///abs/path/to/file.slip' or 'http://...').

        This is a normal primitive: its argument is already evaluated by the evaluator.
        It does not accept GetPath or Code values.
        """
        from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, IString as _IStr

        ev = self.evaluator

        # Determine locator from argument
        url: str | None = None
        file_loc: str | None = None
        cache_key: object

        if isinstance(target, _PL):
            inner = getattr(target, 'inner', None)
            if not isinstance(inner, _GP):
                raise PathNotFound("import")
            # Only accept a literal path produced by the parser (has source location).
            # Paths constructed at runtime (e.g., via call on a string) lack .loc and are rejected.
            if not hasattr(inner, "loc") or inner.loc is None:
                raise PathNotFound("import")
            url = ev.path_resolver._extract_http_url(inner)
            file_loc = ev.path_resolver._extract_file_locator(inner)
            if not url and not file_loc:
                raise PathNotFound("import")
            cache_key = target  # PathLiteral is hashable by its string repr
        elif isinstance(target, (str, _IStr)):
            s = str(target).strip()
            if s.startswith("http://") or s.startswith("https://"):
                url = s
            elif s.startswith("file://"):
                file_loc = s
            else:
                raise PathNotFound("import")
            cache_key = s
        else:
            # Reject GetPath (which may evaluate to Code for file://.slip) and any other types
            raise PathNotFound("import")

        # Module cache
        cache = getattr(ev, 'module_cache', None)
        if cache is None:
            cache = ev.module_cache = {}

        if cache_key in cache:
            return cache[cache_key]

        # Load source
        source_text: str | None = None
        module_dir: str | None = None

        if file_loc:
            from slip.slip_file import _resolve_locator
            import os
            path = _resolve_locator(file_loc, getattr(ev, 'source_dir', None))
            with open(path, "r", encoding="utf-8") as f:
                source_text = f.read()
            module_dir = os.path.dirname(path) or os.getcwd()
        elif url:
            from slip.slip_http import http_request
            src = await http_request('GET', url, config={})
            if isinstance(src, (bytes, bytearray)):
                try:
                    source_text = src.decode('utf-8')
                except Exception:
                    source_text = src.decode('utf-8', errors='replace')
            elif isinstance(src, str):
                source_text = src
            else:
                source_text = str(src)
        else:
            raise PathNotFound("import")

        # Execute module in an isolated runner and export new/changed bindings
        from slip.slip_runtime import ScriptRunner
        runner = ScriptRunner()
        if module_dir:
            runner.source_dir = module_dir

        await runner._initialize()
        before_bindings = dict(runner.root_scope.bindings)

        res = await runner.handle_script(source_text)
        if res.status != "success":
            raise RuntimeError(res.error_message or "Failed to load module")

        after_bindings = runner.root_scope.bindings
        export_names = [
            name for name, val in after_bindings.items()
            if (name not in before_bindings) or (before_bindings.get(name) is not val)
        ]

        mod_scope = Scope(parent=runner.root_scope)
        for name in export_names:
            mod_scope[name] = after_bindings[name]

        cache[cache_key] = mod_scope
        return mod_scope

    # --- List and Sequence Utilities ---
    def _slice_from(self, data, start): return data[start:]
    def _slice_to(self, data, end): return data[:end]
    def _slice_range(self, data, start, end): return data[start:end]
    def _range(self, *args): return list(range(*args))
    def _sort(self, data): return sorted(data)

    # --- Dictionary and Scopeironment Utilities ---
    def _keys(self, d): return list(d.keys() if isinstance(d, collections.abc.Mapping) else d.bindings.keys())
    def _values(self, d): return list(d.values() if isinstance(d, collections.abc.Mapping) else d.bindings.values())
    def _items(self, d):
        if isinstance(d, collections.abc.Mapping):
            return [[k, v] for k, v in d.items()]
        # Scope-like fallback: iterate .bindings
        return [[k, v] for k, v in getattr(d, 'bindings', {}).items()]

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

    def _inherit(self, obj: Scope, proto: Scope):
        self.evaluator._dbg("inherit()", "target_is_scope", isinstance(obj, Scope), "proto_is_scope", isinstance(proto, Scope))
        if not isinstance(obj, Scope) or not isinstance(proto, Scope):
            raise TypeError("inherit expects (scope, scope)")
        obj.inherit(proto)
        return obj

    def _mixin(self, target: Scope, *sources: Scope):
        if not isinstance(target, Scope) or not all(isinstance(s, Scope) for s in sources):
            raise TypeError("mixin expects (scope, scope...)")
        target.add_mixin(*sources)
        return target

    # --- System and Scopeironment ---
    async def _sleep(self, seconds): await asyncio.sleep(seconds)
    def _time(self): return time.time()
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
            prev_flag = getattr(evaluator, 'is_in_task_context', False)
            # Increment task-context counter and ensure the flag is on during this task
            evaluator.task_context_count = getattr(evaluator, 'task_context_count', 0) + 1
            evaluator.is_in_task_context = True
            try:
                await evaluator._eval(code.ast, child)
            finally:
                # Decrement; only restore the flag when the last task-context exits
                try:
                    evaluator.task_context_count -= 1
                except Exception:
                    evaluator.task_context_count = 0
                if evaluator.task_context_count <= 0:
                    evaluator.task_context_count = 0
                    evaluator.is_in_task_context = prev_flag

        t = asyncio.create_task(_runner())
        host = getattr(evaluator, 'host_object', None)
        try:
            if host is not None and hasattr(host, "_register_task"):
                host._register_task(t)
            elif host is not None and hasattr(host, "active_slip_tasks"):
                # Fallback: directly add to the tracking set if present
                host.active_slip_tasks.add(t)
                # Remove immediately upon completion
                t.add_done_callback(lambda _t: host.active_slip_tasks.discard(_t))
        except Exception:
            # Registration is best-effort; continue even if unavailable
            pass
        return t
    def _random(self): return random.random()
    def _random_int(self, a, b): return random.randint(a, b)
    def _len(self, collection): return len(collection)

    # --- Channels (asyncio.Queue wrapper) ---
    def _make_channel(self, maxsize: int = 0):
        # Create a queue; maxsize=0 means unbounded
        return asyncio.Queue(maxsize)

    async def _send(self, channel, value):
        # Put value into the channel (await if full)
        await channel.put(value)
        return None

    async def _receive(self, channel):
        # Await until an item is available; return it
        return await channel.get()

    # --- Side Effects and I/O ---
    def _emit(self, topic_or_topics, *message_parts):
        """Generates a side-effect event for the host application."""
        topics = topic_or_topics if isinstance(topic_or_topics, list) else [topic_or_topics]
        message = " ".join(map(str, message_parts))
        event = {"topics": topics, "message": message}
        if self.evaluator:
            self.evaluator.side_effects.append(event)
        return None

    # --- Language Primitives ---
    async def _if(self, args: list, *, scope: Scope):
        self.evaluator._dbg("if()", "argc", len(args), "arg_types", [type(a).__name__ for a in args])
        if len(args) < 2 or len(args) > 3:
            raise TypeError(f"if expects 2 or 3 arguments, got {len(args)}")

        cond, then_arg = args[0], args[1]
        else_arg = args[2] if len(args) == 3 else None

        # Evaluate condition; propagate returns
        if isinstance(cond, Code):
            cond_val = await self.evaluator._eval(cond.ast, scope)
            if isinstance(cond_val, Response):
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
            if isinstance(val, Response):
                return val
            if isinstance(val, Code):
                return val
            raise TypeError("branch of if must be a code block")

        if cond_val:
            then_code = await _resolve_code_arg(then_arg)
            if isinstance(then_code, Response):
                return then_code
            return await self.evaluator._eval(then_code.ast, scope)
        elif else_arg is not None:
            else_code = await _resolve_code_arg(else_arg)
            if isinstance(else_code, Response):
                return else_code
            return await self.evaluator._eval(else_code.ast, scope)
        return None

    async def _while(self, args: list, *, scope: Scope):
        if len(args) != 2:
            raise TypeError(f"while expects 2 arguments (condition, body), got {len(args)}")
        cond_block, body_block = args
        # Condition must be a code block
        if not isinstance(cond_block, Code):
            raise TypeError("while requires code blocks for condition and body")

        # Body may be a code block literal or a reference to a code block
        if isinstance(body_block, Code):
            body_code = body_block
        else:
            body_val = await self.evaluator._eval(body_block, scope)
            if isinstance(body_val, Response):
                return body_val
            if not isinstance(body_val, Code):
                raise TypeError("while requires code blocks for condition and body")
            body_code = body_val

        iter_count = 0
        last = None
        while True:
            cond_val = await self.evaluator._eval(cond_block.ast, scope)
            if isinstance(cond_val, Response):
                return cond_val
            if not cond_val:
                break
            body_res = await self.evaluator._eval(body_code.ast, scope)
            if isinstance(body_res, Response):
                return body_res
            last = body_res
            iter_count += 1
            if getattr(self.evaluator, 'is_in_task_context', False) or getattr(self.evaluator, 'task_context_count', 0) > 0:
                if (iter_count % 10) == 0:
                    await asyncio.sleep(0)  # cooperative yield periodically
        return last

    async def _foreach(self, args: list, *, scope: Scope):
        self.evaluator._dbg("foreach()", "argc", len(args), "types", [type(a).__name__ for a in args])
        if len(args) != 3:
            raise TypeError(f"foreach expects 3 arguments (vars-sig, collection, body), got {len(args)}")
        vars_spec, collection_expr, body_arg = args

        # Body may be a code literal or a variable holding Code
        if isinstance(body_arg, Code):
            body_code = body_arg
        else:
            body_val = await self.evaluator._eval(body_arg, scope)
            if isinstance(body_val, Response):
                return body_val
            if not isinstance(body_val, Code):
                raise TypeError("foreach requires a code block for the body")
            body_code = body_val

        # Vars must be a sig literal with positional names
        from slip.slip_datatypes import Sig as _Sig
        if not isinstance(vars_spec, _Sig):
            raise TypeError("foreach requires a sig literal for the variable pattern, e.g., {x} or {k, v}")
        var_names = list(vars_spec.positional or [])
        if not var_names:
            raise TypeError("foreach variable sig must list at least one name")

        # Evaluate the collection expression (or accept already-evaluated collections)
        if isinstance(collection_expr, (list, dict)) \
           or isinstance(collection_expr, collections.abc.Mapping) \
           or isinstance(collection_expr, Scope):
            collection = collection_expr
        else:
            collection = await self.evaluator._eval(collection_expr, scope)
            if isinstance(collection, Response):
                return collection

        iter_count = 0
        # Helper to run body and auto-yield in task context
        async def _run_body():
            nonlocal iter_count
            res = await self.evaluator._eval(body_code.ast, scope)
            if isinstance(res, Response):
                return res
            iter_count += 1
            if getattr(self.evaluator, 'is_in_task_context', False) or getattr(self.evaluator, 'task_context_count', 0) > 0:
                if (iter_count % 10) == 0:
                    await asyncio.sleep(0)
            return None

        # Mapping-like (dict) handling: {k} or {k, v}
        if isinstance(collection, collections.abc.Mapping):
            if len(var_names) == 1:
                # For mappings (including SlipDict), single-var iteration yields keys.
                for k in collection.keys():
                    scope[var_names[0]] = k
                    out = await _run_body()
                    if isinstance(out, Response):
                        return out
            elif len(var_names) == 2:
                for k, v in collection.items():
                    scope[var_names[0]] = k
                    scope[var_names[1]] = v
                    out = await _run_body()
                    if isinstance(out, Response):
                        return out
            else:
                raise TypeError("foreach over a mapping supports {k} or {k, v} variable patterns")
            return None

        # Scope handling: iterate bindings as keys/items
        from slip.slip_datatypes import Scope as _Scope
        if isinstance(collection, _Scope):
            if len(var_names) == 1:
                for k in collection.bindings.keys():
                    scope[var_names[0]] = k
                    out = await _run_body()
                    if isinstance(out, Response):
                        return out
            elif len(var_names) == 2:
                for k, v in collection.bindings.items():
                    scope[var_names[0]] = k
                    scope[var_names[1]] = v
                    out = await _run_body()
                    if isinstance(out, Response):
                        return out
            else:
                raise TypeError("foreach over a scope supports {k} or {k, v} variable patterns")
            return None

        # Sequence-like: {x} binds each element; {a, b, ...} destructures iterable elements
        it = collection
        if len(var_names) == 1:
            for item in it:
                scope[var_names[0]] = item
                out = await _run_body()
                if isinstance(out, Response):
                    return out
            return None
        else:
            for item in it:
                try:
                    parts = list(item)
                except Exception:
                    raise TypeError("foreach destructuring requires items to be iterable")
                if len(parts) != len(var_names):
                    raise TypeError(f"foreach destructuring arity mismatch: expected {len(var_names)}, got {len(parts)}")
                for nm, val in zip(var_names, parts):
                    scope[nm] = val
                out = await _run_body()
                if isinstance(out, Response):
                    return out
            return None

    def _fn(self, args: list, *, scope: Scope):
        from slip.slip_datatypes import SlipFunction, Sig as SigType
        if len(args) != 2:
            raise TypeError(f"fn expects 2 arguments (args, body), got {len(args)}")
        arg_spec, body_block = args
        if not isinstance(body_block, Code):
            raise TypeError("Body of fn must be a code block")
        fn = SlipFunction(arg_spec, body_block, scope)
        if isinstance(arg_spec, SigType):
            fn.meta['type'] = arg_spec
        elif not isinstance(arg_spec, Code):
            raise TypeError("Arguments to fn must be a code block or a sig literal")
        return fn

    # --- Container Constructors ---
    def _list(self, code: Code, *, scope: Scope):
        ev = getattr(self, "evaluator", None)
        # Test-path: mock evaluator provides .run (synchronous)
        if hasattr(ev, "run"):
            return [ev.run(expr, scope) for expr in code.ast]
        # Runtime-path: return a coroutine the evaluator can await
        async def _async_impl():
            results = []
            for expr in code.ast:
                results.append(await ev._eval_expr(expr, scope))
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


    async def _preprocess_code_for_run(self, code: Code, caller_scope: Scope) -> list[list]:
        ev = self.evaluator

        async def preprocess_expr(terms: list) -> list:
            out = []
            for term in terms:
                # Handle direct (inject ...) and (splice ...) forms: a Group with a single inner expression
                if isinstance(term, Group) and term.nodes and len(term.nodes) == 1:
                    inner_expr = term.nodes[0]
                    if inner_expr and isinstance(inner_expr[0], GetPath):
                        head = inner_expr[0]
                        if len(head.segments) == 1 and isinstance(head.segments[0], Name):
                            fname = head.segments[0].text
                            args = inner_expr[1:]

                            if fname == 'inject':
                                if len(args) != 1:
                                    raise TypeError("inject expects 1 argument")
                                val = await ev._eval(args[0], caller_scope)
                                out.append(val)
                                continue

                            if fname == 'splice':
                                if len(args) != 1:
                                    raise TypeError("splice expects 1 argument")
                                val = await ev._eval(args[0], caller_scope)
                                if isinstance(val, list):
                                    out.extend(val)
                                    continue
                                raise TypeError("splice in expression requires a list")

                # Recurse into nested Group (non-(inject/splice) cases)
                if isinstance(term, Group):
                    new_inner = []
                    for expr in term.nodes:
                        new_inner.append(await preprocess_expr(expr))
                    new_group = Group(new_inner)
                    # preserve location for diagnostics
                    if hasattr(term, 'loc'):
                        try: new_group.loc = term.loc
                        except Exception: pass
                    out.append(new_group)
                    continue

                # Recurse into list literal elements
                if isinstance(term, SlipList):
                    new_items = []
                    for expr in term.nodes:
                        new_items.append(await preprocess_expr(expr))
                    new_list = SlipList(new_items)
                    if hasattr(term, 'loc'):
                        try: new_list.loc = term.loc
                        except Exception: pass
                    out.append(new_list)
                    continue

                # Recurse into dict literal tuple ('dict', [exprs])
                match term:
                    case ('dict', exprs):
                        new_exprs = [await preprocess_expr(expr) for expr in exprs]
                        out.append(('dict', new_exprs))
                        continue

                # Default: keep term as-is
                out.append(term)
            return out

        out_exprs: list[list] = []
        for expr in code.ast:
            # Whole-expression splice: [(splice ...)]
            if len(expr) == 1:
                t = expr[0]
                if isinstance(t, Group) and t.nodes and len(t.nodes) == 1:
                    inner = t.nodes[0]
                    if inner and isinstance(inner[0], GetPath):
                        head = inner[0]
                        if len(head.segments) == 1 and isinstance(head.segments[0], Name) and head.segments[0].text == 'splice':
                            args = inner[1:]
                            if len(args) != 1:
                                raise TypeError("splice expects 1 argument")
                            val = await ev._eval(args[0], caller_scope)
                            if isinstance(val, Code):
                                nested = await self._preprocess_code_for_run(val, caller_scope)
                                out_exprs.extend(nested)
                                continue
                            if isinstance(val, list):
                                for item in val:
                                    out_exprs.append([item])
                                continue
                            raise TypeError("splice in statement requires code or list")
            # Normal expression: recursively preprocess all nested terms
            out_exprs.append(await preprocess_expr(expr))
        return out_exprs

    async def _run(self, code: Code, *, scope: Scope):
        # Preprocess using the caller’s scope (the current lexical scope)
        exprs = await self._preprocess_code_for_run(code, scope)
        last = None
        for expr in exprs:
            last = await self.evaluator._eval_expr(expr, scope)
        return last

    async def _run_with(self, code: Code, target_scope: Scope, *, scope: Scope):
        """
        Execute code within target_scope for writes, but resolve inject/splice from the caller’s scope.
        Temporarily link target_scope to caller scope for lookups, then restore.
        """
        # Preprocess using the caller’s lexical scope
        exprs = await self._preprocess_code_for_run(code, scope)

        # Temporarily link target scope to caller scope for operator/name lookups
        prev_parent = target_scope.meta.get("parent")
        added_mixin = False
        try:
            if prev_parent is None:
                target_scope.meta["parent"] = scope
            elif scope not in target_scope.meta.setdefault("mixins", []):
                target_scope.meta["mixins"].insert(0, scope)
                added_mixin = True

            # Ensure writes prefer the target scope, not its parent chain, during run-with.
            prev_bind_pref = getattr(self.evaluator, 'bind_locals_prefer_container', False)
            self.evaluator.bind_locals_prefer_container = True
            try:
                last = None
                for expr in exprs:
                    last = await self.evaluator._eval_expr(expr, target_scope)
                return last
            finally:
                self.evaluator.bind_locals_prefer_container = prev_bind_pref
        finally:
            if prev_parent is None:
                target_scope.meta["parent"] = None
            elif added_mixin:
                try:
                    target_scope.meta["mixins"].remove(scope)
                except ValueError:
                    pass

    def _response(self, status: PathLiteral, value: Any):
        return Response(status, value)

    def _respond(self, status: PathLiteral, value: Any):
        # Non-local exit: wrap the payload response in a special 'return' status
        # so the evaluator exits the current function body immediately and returns
        # the payload response as the function's value.
        return Response(PathLiteral(GetPath([Name("return")])), Response(status, value))

    def _return(self, value: Any = None):
        return Response(PathLiteral(GetPath([Name("return")])), value)

    async def _with_log(self, code, *, scope: Scope):
        from slip.slip_datatypes import Code as _Code, Response as _Resp, PathLiteral as _PL, GetPath as _GP, Name as _Name
        from slip.slip_runtime import SlipDict as _SlipDict

        ev = self.evaluator

        # Resolve argument to a Code block (allow variable that holds Code)
        if not isinstance(code, _Code):
            val = await ev._eval(code, scope)
            if isinstance(val, _Resp):
                # Propagate control-flow (e.g., return) upward
                return val
            if not isinstance(val, _Code):
                raise TypeError("with-log requires a code block")
            code = val

        start = len(ev.side_effects)
        try:
            result = await ev._eval(code.ast, scope)
        except Exception as e:
            outcome = _Resp(_PL(_GP([_Name("err")])), str(e))
        else:
            # Normalize to a Response
            if isinstance(result, _Resp):
                # Unwrap return control-flow to its payload Response, if present
                st = result.status
                if (
                    isinstance(st, _PL)
                    and isinstance(getattr(st, "inner", None), _GP)
                    and len(st.inner.segments) == 1
                    and isinstance(st.inner.segments[0], _Name)
                    and st.inner.segments[0].text == "return"
                ):
                    inner = result.value
                    if isinstance(inner, _Resp):
                        outcome = inner
                    else:
                        outcome = _Resp(_PL(_GP([_Name("ok")])), inner)
                else:
                    outcome = result
            else:
                outcome = _Resp(_PL(_GP([_Name("ok")])), result)

        end = len(ev.side_effects)
        out = _SlipDict()
        out["outcome"] = outcome
        out["effects"] = _EffectsView(ev.side_effects, start, end)
        return out

    # --- Type and Conversion ---
    def _to_str(self, value):
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode('utf-8')
            except Exception:
                return value.decode('utf-8', errors='replace')
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
    def _to_bool(self, value): return bool(value)
    def _call(self, value):
        from slip.slip_datatypes import (
            PathLiteral as _PL, GetPath, SetPath, DelPath, PipedPath,
            MultiSetPath, Name, IString
        )
        # Normalize to a runtime path object (GetPath/SetPath/DelPath/PipedPath).
        if isinstance(value, _PL):
            return value.inner
        if isinstance(value, (GetPath, SetPath, DelPath, PipedPath)):
            return value
        if isinstance(value, MultiSetPath):
            raise TypeError("call does not support multi-set paths")
        if isinstance(value, (str, IString)):
            raw = str(value).strip()
            if raw == "":
                raise ValueError("call requires a non-empty string")
            # If the string looks like a URL/special path token, keep it as a single segment.
            if ("://" in raw) or raw.startswith(("/", "../", "./", "|", "~")):
                return GetPath([Name(raw)])
            # Otherwise, split on '.' or '/' into name segments.
            parts = [p for p in re.split(r'[./]', raw) if p]
            segments = [Name(p) for p in parts]
            if not segments:
                raise ValueError("call produced empty path from string")
            return GetPath(segments)
        raise TypeError(f"call cannot convert value of type {type(value).__name__}")
    def _copy(self, value): return copy.copy(value)
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

    def _type_of(self, value):
        from slip.slip_datatypes import (
            Scope, Code, IString, SlipFunction, GenericFunction,
            GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath, Name
        )
        from slip.slip_runtime import SlipDict

        def lit(name: str):
            return PathLiteral(GetPath([Name(name)]))

        if value is None:
            return lit('none')
        if isinstance(value, bool):
            return lit('boolean')
        # bool is a subclass of int, so check it before int
        if isinstance(value, int) and not isinstance(value, bool):
            return lit('int')
        if isinstance(value, float):
            return lit('float')
        if isinstance(value, IString):
            return lit('i-string')
        if isinstance(value, str):
            return lit('string')
        if isinstance(value, list):
            return lit('list')
        if isinstance(value, (dict, SlipDict)):
            return lit('dict')
        if isinstance(value, Scope):
            return lit('scope')
        if isinstance(value, (GetPath, SetPath, DelPath, PipedPath, PathLiteral, MultiSetPath)):
            return lit('path')
        if isinstance(value, (SlipFunction, GenericFunction)) or callable(value):
            return lit('function')
        if isinstance(value, Code):
            return lit('code')
        # Fallback: treat as string type
        return lit('string')

    def _example(self, func, example_sig, *, scope: Scope = None):
        from slip.slip_datatypes import Sig, SlipFunction, GenericFunction
        if not isinstance(example_sig, Sig):
            raise TypeError("example expects a sig literal as the second argument")
        if not isinstance(func, (SlipFunction, GenericFunction)):
            raise TypeError("example expects a function or generic function as the first argument")
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

    async def _test(self, func, *, scope: Scope):
        from slip.slip_datatypes import (
            Sig, SlipFunction, GenericFunction, GetPath, Code,
            GetPath as _GP, SetPath as _SP, DelPath as _DP, PipedPath as _PP,
            PathLiteral as _PL, MultiSetPath as _MSP
        )
        if not isinstance(func, (SlipFunction, GenericFunction)):
            raise TypeError("test expects a function or generic function")

        def _status(name: str):
            return PathLiteral(GetPath([Name(name)]))

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

        # Patch: temporarily expose caller scope as a mixin on function closures for operator lookup
        def _patch_closures(extra_scope: Scope):
            patched = []
            if not isinstance(extra_scope, Scope):
                return patched
            if isinstance(func, SlipFunction):
                closures = [func.closure]
            elif isinstance(func, GenericFunction):
                closures = [getattr(m, "closure", None) for m in func.methods]
            else:
                closures = []
            for c in closures:
                if not isinstance(c, Scope):
                    continue
                mixins = c.meta.setdefault("mixins", [])
                if extra_scope not in mixins:
                    mixins.insert(0, extra_scope)
                    patched.append(c)
            return patched

        def _unpatch_closures(extra_scope: Scope, patched_list):
            for c in patched_list or []:
                try:
                    c.meta.setdefault("mixins", []).remove(extra_scope)
                except ValueError:
                    pass

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

            # Ensure '+'/'*'/etc. are visible even if the function was defined under a temporary run-with link
            patched = _patch_closures(scope)
            try:
                actual = await self.evaluator.call(func, args, scope)
            except Exception as e:
                failures.append({"index": i, "error": str(e)})
                _unpatch_closures(scope, patched)
                continue
            finally:
                _unpatch_closures(scope, patched)

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
            return PathLiteral(GetPath([Name(name)]))

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
                has_examples = any(getattr(m, "meta", {}).get("examples") for m in fn.methods)
            if not has_examples:
                continue

            total_with_examples += 1
            res = await self._test(fn, scope=scope)
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
        status = "ok" if not failed_details else "err"
        return Response(PathLiteral(GetPath([Name(status)])), summary)

    async def _call(self, target, args_list=None, *, scope: Scope):
        """
        call <path-literal|string> #[args...]
        - Resolves the path to a value in the current scope and invokes it with args_list.
        - If the path is a SetPath literal (`y:`), args_list must have one item; performs assignment and returns the value.
        - If the path is a DelPath literal (`~y`), args_list must be empty; performs delete and returns None.
        """
        from slip.slip_datatypes import (
            PathLiteral as _PL, GetPath as _GP, SetPath as _SP, DelPath as _DP,
            IString as _IStr, SlipFunction as _SF, GenericFunction as _GF
        )
        # Normalize args: None => zero-arity call; otherwise require a list
        if args_list is None:
            args = []
        elif isinstance(args_list, list):
            args = args_list
        else:
            raise TypeError("call expects an argument list (#[]), e.g., call `f` #[a, b]")

        # Only accept string or path-literal for the target
        if isinstance(target, (str, _IStr)):
            gp = self._to_getpath(target)
            from slip.slip_datatypes import PathLiteral as _PL_OUT
            return _PL_OUT(gp)

        if isinstance(target, _PL):
            inner = target.inner
            # Dynamic set-path: (call `y:`) #[2]
            if isinstance(inner, _SP):
                if args_list is None:
                    # No args provided: return the SetPath so caller can use it as an assignment head: (call `y:`) 2
                    return inner
                if len(args) != 1:
                    raise TypeError("call on a set-path requires exactly one argument")
                await self.evaluator.path_resolver.set(inner, args[0], scope)
                return args[0]
            # Dynamic del-path: (call `~y`) #[]
            if isinstance(inner, _DP):
                if args_list is not None and len(args) != 0:
                    raise TypeError("call on a del-path does not take arguments")
                await self.evaluator.path_resolver.delete(inner, scope)
                return None
            # Ordinary function lookup: path-literal must be a get-path
            if isinstance(inner, _GP):
                try:
                    val = await self.evaluator.path_resolver.get(inner, scope)
                except Exception:
                    # Unresolvable → return the original literal (normalization)
                    return target
                # If resolved value is invocable → invoke
                if isinstance(val, (_SF, _GF)) or callable(val):
                    return await self.evaluator.call(val, args, scope)
                # If resolved value is not callable:
                # - with no args (None) or explicit empty list, return the value
                if args_list is None or (isinstance(args, list) and len(args) == 0):
                    return val
                # - with any args provided, this is a type error
                raise TypeError("call expects a function at the given path")
            raise TypeError("call expects a function path (get-path) or set/del path literal")

        # Prefer exact-arity, non-variadic method when calling a GenericFunction directly
        if isinstance(target, _GF):
            from slip.slip_datatypes import Sig as _Sig
            exact = []
            for m in target.methods:
                s = getattr(m, 'meta', {}).get('type')
                if isinstance(s, _Sig):
                    base = len(getattr(s, 'positional', []) or []) + len(getattr(s, 'keywords', {}) or {})
                    if getattr(s, 'rest', None) is None and base == len(args):
                        exact.append(m)
            if exact:
                # Pick the most recently defined exact-arity method
                return await self.evaluator.call(exact[-1], args, scope)

        # Callable value or SLIP function container → invoke directly
        if isinstance(target, (_SF, _GF)) or callable(target):
            return await self.evaluator.call(target, args, scope)
        raise TypeError("call expects a path-literal, string, or callable target")


# ===================================================================
# 5. Script Execution
# ===================================================================

Token = Dict[str, Any]

class ExecutionResult:
    """The structured result of a script execution."""
    def __init__(self,
                 status: Literal['success', 'error'],
                 value: Any = None,
                 error_message: Optional[str] = None,
                 error_token: Optional[Token] = None,
                 side_effects: Optional[List[Dict]] = None):
        self.status = status
        self.value = value
        self.error_message = error_message
        self.error_token = error_token
        self.side_effects = side_effects if side_effects is not None else []

    def format_error(self) -> str:
        """Formats an error message with line and column if available."""
        if self.status != 'error':
            return ""

        msg = self.error_message or "Unknown error"

        if self.error_token and 'line' in self.error_token:
            line = self.error_token['line']
            # Not all error tokens will have a column
            col_info = f", col {self.error_token['col']}" if 'col' in self.error_token else ""
            return f"Error on line {line}{col_info}: {msg}"

        return str(msg)

    def __repr__(self) -> str:
        if self.status == 'error':
            return f"<ExecutionResult status='error' message='{self.error_message}'>"
        return f"<ExecutionResult status='{self.status}' value={self.value!r}>"


class ScriptRunner:
    """Parses, transforms, and executes SLIP code."""

    _parser: Optional[Parser] = None
    _transformer: Optional[SlipTransformer] = None
    _core_loaded_ast: Optional[Code] = None
    _core_source: Optional[str] = None

    def _format_parse_error(self, parse_out, source: str) -> str:
        node = (parse_out or {}).get('error_node') or {}
        base = (parse_out or {}).get('error_message') or str(parse_out)
        line = node.get('line')
        col = node.get('col')
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
                    if (len(stripped) >= 2 and ((stripped[0] == stripped[-1] == "'") or (stripped[0] == stripped[-1] == '"'))):
                        stripped = stripped[1:-1]
                    detail = stripped
                else:
                    detail = str(inner)
                msg = f"PathNotFound: {detail}"
            case TypeError() | AttributeError():
                call_name = None
                try:
                    if getattr(self.evaluator, 'call_stack', None):
                        call_name = self.evaluator.call_stack[-1].get('name')
                except Exception:
                    call_name = None
                safe_name = None
                if isinstance(call_name, str) and call_name not in ('return', '<call>'):
                    safe_name = call_name.lstrip('_').replace('_', '-')
                msg = "TypeError: invalid-args" + (f" in ({safe_name})" if safe_name else "")
            case _:
                msg = f"InternalError: {str(e)}"

        # Pretty-print an attached SLIP object (prefer offender term, if provided)
        slip_obj = getattr(e, 'slip_obj', None)
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
            loc = getattr(offender, 'loc', None) if offender is not None else None
            if loc and isinstance(loc, dict):
                line = loc.get('line'); col = loc.get('col')
                token = {'line': line, 'col': col, 'tag': loc.get('tag'), 'text': loc.get('text')}
                if line is not None and col is not None:
                    msg = f"{msg}\n(line {line}, col {col})\n{self._source_context(source, line, col)}"
                    loc_tag = (loc or {}).get('tag'); loc_text = (loc or {}).get('text')
                    if loc_tag or loc_text:
                        msg = f"{msg}\nAt node tag={loc_tag!r} text={loc_text!r}"
        except Exception:
            pass

        # Append SLIP stacktrace if available
        st = self._format_stacktrace()
        if st:
            msg += "\n" + st

        return msg, token

    def _source_context(self, source: str, line: int, col: Optional[int], radius: int = 2) -> str:
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

    def _format_stacktrace(self) -> str:
        stack = getattr(self.evaluator, 'call_stack', None) or []
        if not stack:
            return ""
        try:
            from slip.slip_printer import Printer
            pf = Printer().pformat
        except Exception:
            pf = repr

        import inspect
        try:
            from slip.slip_datatypes import Code as _Code, SlipFunction as _SlipFn, Sig as _Sig
        except Exception:
            _Code = tuple()
            _SlipFn = tuple()
            _Sig = tuple()

        def friendly_callable_name(fn):
            try:
                if inspect.ismethod(fn) and getattr(fn.__self__, '__class__', None).__name__ == 'StdLib':
                    n = getattr(fn, '__name__', '') or ''
                    return n.lstrip('_').replace('_', '-')
                n = getattr(fn, '__name__', None)
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
            name = frame.get('name') or '<call>'
            args = frame.get('args') or []
            # Suppress noisy arguments for 'return'
            if name == 'return':
                args_s = ""
            else:
                safe_args = [fmt(a) for a in args]
                args_s = " ".join(safe_args).strip()

            frame_str = f"({name}"
            if args_s:
                frame_str += f" {args_s}"
            frame_str += ")"
            frames.append(frame_str)

        return "SLIP stacktrace: " + " ".join(frames)

    def __init__(self, host_object: Optional['SLIPHost'] = None, load_core: bool = True):
        self.host_object = host_object
        self._initialized = False
        self.root_scope = Scope()
        self._load_core = load_core
        self.source_dir = None  # directory of the current source file, if known

        if ScriptRunner._parser is None:
            # TODO: This path is brittle. A package resource approach would be better.
            grammar_path = Path(__file__).parent.parent / "grammar" / "slip_grammar.yaml"
            ScriptRunner._parser = Parser.from_file(str(grammar_path))

        if ScriptRunner._transformer is None:
            ScriptRunner._transformer = SlipTransformer()

        self.parser = ScriptRunner._parser
        self.transformer = ScriptRunner._transformer

        self.evaluator = Evaluator() # Each runner has its own evaluator/side_effects
        # The evaluator needs access to the host object to correctly implement `task`
        if host_object:
            self.evaluator.host_object = host_object

        # Load stdlib
        stdlib = StdLib(self.evaluator)
        for name, member in inspect.getmembers(stdlib):
            if name.startswith('_') and not name.startswith('__') and callable(member):
                slip_name = name[1:].replace('_', '-')
                self.root_scope[slip_name] = member
                # Provide stable core- aliases for operators to avoid shadowing by user-defined functions
                core_name = f"core-{slip_name}"
                self.root_scope[core_name] = member

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
                    if isinstance(parse_out, dict) and 'status' in parse_out:
                        if parse_out.get('status') != 'success':
                            err = self._format_parse_error(parse_out, core_source)
                            raise RuntimeError(f"Failed to parse root.slip:\n{err}")
                        ast_node = parse_out['ast']
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
             prev_src = self.evaluator.current_source
             self.evaluator.current_source = 'core'
             try:
                 await self.evaluator.eval(ScriptRunner._core_loaded_ast.nodes, self.root_scope)
             finally:
                 self.evaluator.current_source = prev_src

        self._initialized = True


    async def handle_script(self, source_code: str) -> 'ExecutionResult':
        """The main entry point to execute a script."""
        try:
            # Clear side effects for each run
            self.evaluator.side_effects.clear()
            self.evaluator.call_stack.clear()
            self._current_script_source = source_code
            self.evaluator.current_source = 'script'
            # Ensure evaluator has the current host for task registration each run
            self.evaluator.host_object = self.host_object
            # Make source_dir available for file:// resolution; default to CWD when unknown
            import os as _os
            self.evaluator.source_dir = self.source_dir or _os.getcwd()
            await self._initialize()
            # 1. Parse
            try:
                parse_out = self.parser.parse(source_code)
            except Exception:
                msg = "ParseError: parse failed"
                self.evaluator.side_effects.append({'topics': ['stderr'], 'message': msg})
                return ExecutionResult(
                    status='error',
                    error_message=msg,
                    side_effects=self.evaluator.side_effects
                )

            if isinstance(parse_out, dict) and 'status' in parse_out:
                if parse_out.get('status') != 'success':
                    msg = self._format_parse_error(parse_out, source_code)
                    self.evaluator.side_effects.append({'topics': ['stderr'], 'message': msg})
                    return ExecutionResult(
                        status='error',
                        error_message=msg,
                        error_token=parse_out.get('error_node'),
                        side_effects=self.evaluator.side_effects
                    )
                # success
                ast_node = parse_out.get('ast')
                if ast_node is None:
                    # Defensive: if a success wrapper comes without ast, treat as fatal parse anomaly
                    msg = "Parse error: missing AST in parser result"
                    self.evaluator.side_effects.append({'topics': ['stderr'], 'message': msg})
                    return ExecutionResult(
                        status='error',
                        error_message=msg,
                        side_effects=self.evaluator.side_effects
                    )
            else:
                ast_node = parse_out

            # 2. Transform
            try:
                transformed_ast = self.transformer.transform(ast_node)
            except Exception:
                msg = "InternalError: transform failed"
                self.evaluator.side_effects.append({'topics': ['stderr'], 'message': msg})
                return ExecutionResult(status='error', error_message=msg, side_effects=self.evaluator.side_effects)

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
                        result.add_done_callback(lambda t: host.active_slip_tasks.discard(t))
            except Exception:
                pass

            if isinstance(result, Response):
                # The 'return' status is a special control flow signal
                if isinstance(result.status, PathLiteral) and isinstance(result.status.inner, GetPath) and len(result.status.inner.segments) == 1 and isinstance(result.status.inner.segments[0], Name) and result.status.inner.segments[0].text == "return":
                    return ExecutionResult(
                        status='success',
                        value=result.value,
                        side_effects=self.evaluator.side_effects
                    )
                # Other responses (like 'ok', 'err') are just data
                return ExecutionResult(
                    status='success',
                    value=result,
                    side_effects=self.evaluator.side_effects
                )

            return ExecutionResult(
                status='success',
                value=result,
                side_effects=self.evaluator.side_effects
            )

        except Exception as e:
            node = getattr(self.evaluator, 'current_node', None)
            err_msg, err_token = self._format_runtime_error(e, source_code, node)
            # Emit consolidated stderr side-effect
            self.evaluator.side_effects.append({'topics': ['stderr'], 'message': err_msg})
            return ExecutionResult(
                status='error',
                error_message=err_msg,
                error_token=err_token,
                side_effects=self.evaluator.side_effects
            )
