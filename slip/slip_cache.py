"""File-loaded symbolic Code, serialized without runtime bindings."""

import hashlib
import os
import pickle
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from threading import Lock

from . import slip_syntax
from .grammar import GRAMMAR_PATH
from .slip_core import Code


_memory_lock = Lock()


@lru_cache(maxsize=1)
def pipeline_fingerprint():
    directory = Path(__file__).resolve().parent
    files = [directory / name for name in (
        "slip_core.py", "slip_syntax.py", "slip_cache.py",
    )] + [GRAMMAR_PATH.with_name(name) for name in (
        "slip_grammar.yaml", "slip_path.yaml", "slip_sig.yaml",
    )]
    digest = hashlib.sha256(b"slip-symbolic-code:1")
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(version("koine").encode())
    digest.update(sys.implementation.name.encode())
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    digest.update(python.encode())
    return digest.hexdigest()


def cache_directory():
    configured = os.environ.get("SLIP_CACHE_DIR")
    if configured == "":
        return None
    root = Path(configured).expanduser() if configured else Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"),
    ) / "slip"
    directory = root / "transformed"
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path in (directory, directory / "artifacts", directory / "paths"):
            path.mkdir(mode=0o700, exist_ok=True)
        if os.name == "posix":
            if directory.stat().st_uid != os.geteuid():
                return None
            directory.chmod(0o700)
    except OSError:
        # Cache availability must not determine whether valid source can load.
        return None
    return directory


@contextmanager
def cache_lock(directory):
    if directory is None:
        yield None
        return
    stream = None
    try:
        stream = (directory / ".lock").open("a+b")
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError:
        if stream is not None:
            stream.close()
        yield None
        return
    try:
        # One native lock covers artifact publication and last-index cleanup.
        yield directory
    finally:
        stream.close()


def write_atomic(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Best-effort cleanup of this write's temporary file.


def restore(payload, key):
    stored_key, code = pickle.loads(payload)
    if stored_key != key or type(code) is not Code or code.stacks is not None:
        raise ValueError("Invalid symbolic Code cache")
    return code


@lru_cache(maxsize=128)
def compiled(source, key):
    # Only parser output is serialized, never returned/editable Code.
    return pickle.dumps((key, slip_syntax.parse(source)),
                        protocol=pickle.HIGHEST_PROTOCOL)


def update_index(directory, path, key):
    name = hashlib.sha256(os.fsencode(path)).hexdigest()
    index = directory / "paths" / (name + ".index")
    try:
        previous = index.read_bytes().strip()
    except OSError:
        previous = b""
    current = key.encode("ascii")
    if previous == current or not write_atomic(index, current):
        return
    if not re.fullmatch(rb"[0-9a-f]{64}", previous):
        return
    try:
        if any(candidate.read_bytes().strip() == previous
               for candidate in index.parent.glob("*.index")):
            return
        artifact = directory / "artifacts" / (previous.decode() + ".pickle")
        artifact.unlink(missing_ok=True)
    except OSError:
        pass  # Retain artifacts if index inspection/cleanup is unavailable.


def load_code(path):
    path = Path(path).resolve()
    source = path.read_text(encoding="utf-8")
    with _memory_lock, cache_lock(cache_directory()) as directory:
        key = hashlib.sha256(
            pipeline_fingerprint().encode() + source.encode("utf-8"),
        ).hexdigest()
        artifact = directory / "artifacts" / (key + ".pickle") \
            if directory is not None else None
        if directory is not None:
            for legacy in directory.parent.glob("transformed-v*"):
                if legacy.is_dir():
                    shutil.rmtree(legacy, ignore_errors=True)
        payload = None
        if artifact is not None:
            try:
                payload = artifact.read_bytes()
                code = restore(payload, key)
            except (OSError, EOFError, pickle.PickleError, AttributeError,
                    ImportError, TypeError, ValueError):
                payload = None  # Absent/outdated/corrupt cache: use source.
        if payload is None:
            payload = compiled(source, key)
            code = restore(payload, key)
            if artifact is not None:
                write_atomic(artifact, payload)
        if directory is not None:
            update_index(directory, path, key)
    slip_syntax.attach_source(code, source, str(path))
    return code
