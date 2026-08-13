from __future__ import annotations
import hashlib
import importlib.metadata
import os
import pickle
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, Any
from slip.slip_serialize import deserialize, serialize
# NOTE: ScriptRunner, Scope, and Printer are imported lazily in functions
# to avoid circular import during module load.


_compiled_slip_cache = {}
_CACHE_FORMAT = 1
_pipeline_fingerprint = None
_prepared_cache_roots = set()
_cache_stats = {
    "memory_hits": 0,
    "persistent_hits": 0,
    "misses": 0,
    "parses": 0,
    "writes": 0,
    "rejections": 0,
}


def cache_stats() -> Dict[str, int]:
    return dict(_cache_stats)


def _cache_debug(event: str, **data) -> None:
    if not os.environ.get("SLIP_CACHE_DEBUG"):
        return
    fields = " ".join(f"{key}={value!r}" for key, value in data.items())
    print(f"[slip-cache] {event} {fields}", file=sys.stderr)


def _compile_fingerprint() -> str:
    global _pipeline_fingerprint
    if _pipeline_fingerprint is not None:
        return _pipeline_fingerprint

    digest = hashlib.sha256(f"slip-code-cache:{_CACHE_FORMAT}".encode())
    root = Path(__file__).resolve().parent.parent
    for path in (
        root / "grammar" / "slip_grammar.yaml",
        root / "grammar" / "slip_path.yaml",
        root / "grammar" / "slip_sig.yaml",
        Path(__file__).with_name("slip_transformer.py"),
        Path(__file__).with_name("slip_datatypes.py"),
    ):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    try:
        koine_version = importlib.metadata.version("koine")
    except importlib.metadata.PackageNotFoundError:
        koine_version = "unknown"
    digest.update(koine_version.encode())
    digest.update(sys.implementation.name.encode())
    digest.update(f"{sys.version_info.major}.{sys.version_info.minor}".encode())
    _pipeline_fingerprint = digest.hexdigest()
    return _pipeline_fingerprint


def _cache_dir() -> Optional[Path]:
    configured = os.environ.get("SLIP_CACHE_DIR")
    if configured == "":
        _cache_debug("disabled", reason="SLIP_CACHE_DIR is empty")
        return None
    if configured:
        root = Path(configured).expanduser()
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "slip"
    path = root / "transformed"
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_key = str(root.resolve())
        if root_key not in _prepared_cache_roots:
            for legacy in root.glob("transformed-v*"):
                if legacy.is_dir():
                    shutil.rmtree(legacy, ignore_errors=True)
            _prepared_cache_roots.add(root_key)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            path.chmod(0o700)
            if path.stat().st_uid != os.geteuid():
                return None
    except OSError:
        _cache_debug("disabled", reason="cache directory unavailable", path=str(path))
        return None
    _cache_debug("directory", path=str(path))
    return path


def _artifact_key(source_fingerprint: bytes) -> str:
    return hashlib.sha256(
        source_fingerprint + _compile_fingerprint().encode()
    ).hexdigest()


def _persistent_cache_path(source_fingerprint: bytes) -> Optional[Path]:
    cache_dir = _cache_dir()
    if cache_dir is None:
        return None
    path = cache_dir / "artifacts"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        return None
    return path / f"{_artifact_key(source_fingerprint)}.pickle"


def _path_index_path(canonical_path: str) -> Optional[Path]:
    cache_dir = _cache_dir()
    if cache_dir is None:
        return None
    path = cache_dir / "paths"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        return None
    key = hashlib.sha256(os.fsencode(canonical_path)).hexdigest()
    return path / f"{key}.index"


def _write_bytes(path: Path, data: bytes) -> bool:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            if os.name == "posix":
                os.chmod(stream.name, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        return False


@contextmanager
def _artifact_lock(path: Optional[Path]):
    if path is None or os.name != "posix":
        yield
        return
    import fcntl

    lock_path = path.with_suffix(".lock")
    try:
        stream = lock_path.open("a+b")
    except OSError:
        yield
        return
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError:
        stream.close()
        yield
        return
    try:
        yield
    finally:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _update_path_index(canonical_path: str, source_fingerprint: bytes) -> None:
    index_path = _path_index_path(canonical_path)
    if index_path is None:
        return
    artifact_key = _artifact_key(source_fingerprint)
    try:
        previous_key = index_path.read_text(encoding="ascii").strip()
    except OSError:
        previous_key = ""
    if previous_key == artifact_key:
        return
    if not _write_bytes(index_path, artifact_key.encode("ascii")) or not previous_key:
        return

    paths_dir = index_path.parent
    try:
        still_referenced = any(
            candidate != index_path
            and candidate.read_text(encoding="ascii").strip() == previous_key
            for candidate in paths_dir.glob("*.index")
        )
    except OSError:
        return
    if not still_referenced:
        artifact = paths_dir.parent / "artifacts" / f"{previous_key}.pickle"
        try:
            artifact.unlink()
        except OSError:
            pass


def _read_compiled(path: Optional[Path], source_fingerprint: bytes):
    if path is None:
        _cache_stats["misses"] += 1
        _cache_debug("miss", reason="disabled")
        return None
    try:
        with path.open("rb") as stream:
            artifact = pickle.load(stream)
        reasons = []
        if artifact.get("format") != _CACHE_FORMAT:
            reasons.append("format")
        if artifact.get("pipeline") != _compile_fingerprint():
            reasons.append("pipeline")
        if artifact.get("source") != source_fingerprint:
            reasons.append("source")
        if not isinstance(artifact.get("compiled"), bytes):
            reasons.append("payload")
        if reasons:
            _cache_stats["rejections"] += 1
            _cache_debug("reject", path=str(path), reasons=",".join(reasons))
            return None
        _cache_stats["persistent_hits"] += 1
        _cache_debug("hit", kind="persistent", path=str(path))
        return artifact["compiled"]
    except FileNotFoundError:
        _cache_stats["misses"] += 1
        _cache_debug("miss", reason="absent", path=str(path))
        return None
    except (OSError, EOFError, pickle.PickleError, AttributeError, TypeError) as exc:
        _cache_stats["rejections"] += 1
        _cache_debug("reject", path=str(path), reason=type(exc).__name__)
        return None


def _write_compiled(
    path: Optional[Path], source_fingerprint: bytes, compiled: bytes
) -> None:
    if path is None:
        return
    artifact = {
        "format": _CACHE_FORMAT,
        "pipeline": _compile_fingerprint(),
        "source": source_fingerprint,
        "compiled": compiled,
    }
    if _write_bytes(path, pickle.dumps(artifact, protocol=pickle.HIGHEST_PROTOCOL)):
        _cache_stats["writes"] += 1
        _cache_debug("write", path=str(path))
    else:
        _cache_debug("write-failed", path=str(path))

def _resolve_locator(locator: str, base_dir: Optional[str]) -> str:
    # locator is like 'file://...', strip scheme
    assert locator.startswith("file://"), locator
    rest = locator[7:]  # after 'file://'
    # Absolute filesystem root
    if rest.startswith("/"):
        # file:///<abs-path> or file:/// only
        # file:/// → '/'
        return "/" + rest.lstrip("/")
    # Home directory
    if rest.startswith("~"):
        tail = rest[1:]
        return os.path.expanduser("~" + (tail if tail.startswith("/") else ("/" + tail if tail else "")))
    # Working directory relative
    if rest.startswith("./"):
        base = base_dir or os.getcwd()
        return os.path.normpath(os.path.join(base, rest[2:] or ""))
    if rest.startswith("../"):
        base = base_dir or os.getcwd()
        return os.path.normpath(os.path.join(base, rest))
    # Empty → source file dir or CWD
    if rest == "":
        return base_dir or os.getcwd()
    # Default: relative to source file dir (or CWD)
    base = base_dir or os.getcwd()
    return os.path.normpath(os.path.join(base, rest))

async def file_get(locator: str, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
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
            # Return a Code block (do not execute). Use 'import `file://...`' to load modules.
            from slip.slip_runtime import ScriptRunner
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            canonical_path = os.path.realpath(path)
            fingerprint = hashlib.sha256(src.encode("utf-8")).digest()
            cached = _compiled_slip_cache.get(canonical_path)
            if cached is None or cached[0] != fingerprint:
                cache_path = _persistent_cache_path(fingerprint)
                started = time.perf_counter()
                compiled = _read_compiled(cache_path, fingerprint)
                if compiled is None:
                    with _artifact_lock(cache_path):
                        # Another process may have populated the artifact while we waited.
                        compiled = _read_compiled(cache_path, fingerprint)
                        if compiled is None:
                            _cache_debug(
                                "compile",
                                source=canonical_path,
                                source_hash=fingerprint.hex(),
                                artifact=str(cache_path),
                            )
                            runner = ScriptRunner()
                            _cache_stats["parses"] += 1
                            parse_out = runner.parser.parse(src)
                            ast_node = parse_out['ast'] if isinstance(parse_out, dict) and 'ast' in parse_out else parse_out
                            code_obj = runner.transformer.transform(ast_node)
                            compiled = pickle.dumps(
                                code_obj,
                                protocol=pickle.HIGHEST_PROTOCOL,
                            )
                            _write_compiled(cache_path, fingerprint, compiled)
                        else:
                            code_obj = pickle.loads(compiled)
                else:
                    code_obj = pickle.loads(compiled)
                _update_path_index(canonical_path, fingerprint)
                _compiled_slip_cache[canonical_path] = (fingerprint, compiled)
                _cache_debug(
                    "load",
                    source=canonical_path,
                    elapsed=round(time.perf_counter() - started, 6),
                )
            else:
                _cache_stats["memory_hits"] += 1
                _cache_debug("hit", kind="memory", source=canonical_path)
                compiled = cached[1]
                # Code is mutable and first-class, so return an isolated syntax graph.
                code_obj = pickle.loads(compiled)
            # Attach source metadata so |import can cache and set module_dir
            try:
                code_obj.source_locator = locator
                code_obj.source_path = canonical_path
            except Exception:
                pass
            return code_obj
        # Text files
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        # Default fallback: return UTF-8 text
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # Not found
    raise FileNotFoundError(path)

async def file_put(locator: str, data: Any, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
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
        from slip.slip_serialize import serialize as _ser, detect_format as _detect_fmt
        fmt = _detect_fmt(ctype)
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

async def file_delete(locator: str, config: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None):
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
