from __future__ import annotations
import os
from typing import Optional, Dict, Any
from slip.slip_serialize import deserialize, serialize
# NOTE: ScriptRunner, Scope, and Printer are imported lazily in functions
# to avoid circular import during module load.

def _resolve_locator(locator: str, base_dir: Optional[str]) -> str:
    # locator is like 'fs://...', strip scheme
    assert locator.startswith("fs://"), locator
    rest = locator[5:]  # after 'fs://'
    # Absolute filesystem root
    if rest.startswith("/"):
        # fs:///<abs-path> or fs:/// only
        # fs:/// → '/'
        return "/" + rest.lstrip("/")
    # Home directory
    if rest.startswith("~"):
        tail = rest[1:]
        return os.path.expanduser("~" + (tail if tail.startswith("/") else ("/" + tail if tail else "")))
    # Working directory relative
    if rest.startswith("./"):
        return os.path.normpath(os.path.join(os.getcwd(), rest[2:] or ""))
    if rest.startswith("../"):
        base = base_dir or os.getcwd()
        return os.path.normpath(os.path.join(base, rest))
    # Empty → source file dir or CWD
    if rest == "":
        return base_dir or os.getcwd()
    # Default: relative to source file dir (or CWD)
    base = base_dir or os.getcwd()
    return os.path.normpath(os.path.join(base, rest))

async def fs_get(locator: str, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
    path = _resolve_locator(locator, base_dir)
    cfg = dict(config or {})
    encoding = cfg.get("encoding")  # optional, if provided forces text decode

    # Directory → dict of {filename: bytes}
    if os.path.isdir(path):
        out: Dict[str, bytes] = {}
        try:
            for name in os.listdir(path):
                full = os.path.join(path, name)
                if os.path.isfile(full):
                    with open(full, "rb") as f:
                        out[name] = f.read()
        except FileNotFoundError:
            # Nonexistent directory → empty mapping
            return {}
        return out

    # File → decode/convert based on extension
    if os.path.isfile(path):
        ext = os.path.splitext(path)[1].lower()
        # Explicit override: if caller provided an encoding, return decoded text
        if encoding:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        # Structured formats
        if ext in (".json", ".yaml", ".yml", ".toml"):
            with open(path, "rb") as f:
                data = f.read()
            fmt = "json" if ext == ".json" else ("yaml" if ext in (".yaml", ".yml") else "toml")
            return deserialize(data, fmt=fmt)
        # SLIP modules: evaluate and return a scope of module bindings
        if ext == ".slip":
            # Lazy imports to avoid circular imports during module load
            from slip.slip_runtime import ScriptRunner
            from slip.slip_datatypes import Scope
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            runner = ScriptRunner()
            # Ensure relative fs:// lookups inside the module resolve to this file’s directory
            runner.source_dir = os.path.dirname(path) or os.getcwd()
            # Capture pre-existing bindings to compute module exports
            before = set(runner.root_scope.bindings.keys())
            res = await runner.handle_script(src)
            if res.status != "success":
                raise RuntimeError(res.error_message or "Failed to load .slip module")
            after = set(runner.root_scope.bindings.keys())
            exports = after - before
            mod = Scope(parent=runner.root_scope)
            for name in exports:
                mod[name] = runner.root_scope.bindings[name]
            return mod
        # Text files
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        # Default fallback: return UTF-8 text
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # Not found
    raise FileNotFoundError(path)

async def fs_put(locator: str, data: Any, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
    path = _resolve_locator(locator, base_dir)
    cfg = dict(config or {})
    encoding = cfg.get("encoding")
    ctype = cfg.get("content-type") or cfg.get("content_type")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    # Bytes always written verbatim
    if isinstance(data, (bytes, bytearray)):
        with open(path, "wb") as f:
            f.write(data)
        return
    # Explicit encoding override for text
    if encoding:
        with open(path, "w", encoding=encoding or "utf-8") as f:
            f.write(str(data))
        return
    # content-type override: serialize accordingly (takes precedence over extension if no explicit encoding)
    if ctype and encoding is None:
        from slip.slip_serialize import serialize as _ser
        def _fmt_from_ctype(ct: str | None) -> str | None:
            if not isinstance(ct, str): return None
            ct_l = ct.lower()
            if 'json' in ct_l: return 'json'
            if 'yaml' in ct_l or 'x-yaml' in ct_l: return 'yaml'
            if 'toml' in ct_l: return 'toml'
            if 'xml' in ct_l or 'html' in ct_l or 'xhtml' in ct_l: return 'xml'
            return None
        fmt = _fmt_from_ctype(ctype)
        if fmt is not None:
            text = _ser(data, fmt=fmt, pretty=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return
    # Structured formats
    if ext in (".json", ".yaml", ".yml", ".toml"):
        fmt = "json" if ext == ".json" else ("yaml" if ext in (".yaml", ".yml") else "toml")
        text = serialize(data, fmt=fmt, pretty=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return
    # SLIP source: pretty‑print valid SLIP using the Printer (AST → source)
    if ext == ".slip":
        from slip.slip_printer import Printer  # lazy import to avoid cycles
        text = Printer().pformat(data)
        # Ensure newline at EOF for nicer diffs
        if not text.endswith("\n"):
            text += "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return
    # Plain text for common text types
    if ext in (".txt", ".md"):
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(data))
        return
    # Default fallback: write as UTF-8 text
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(data))

async def fs_delete(locator: str, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
    path = _resolve_locator(locator, base_dir)
    if os.path.isfile(path):
        os.remove(path)
        return
    if os.path.isdir(path):
        # Conservative: do not delete directories by default
        # (could add config e.g., recursive: true in the future)
        raise IsADirectoryError(path)
    # If neither → no-op or error; keep consistent with file delete semantics
    # Silently ignore if not found
    return
