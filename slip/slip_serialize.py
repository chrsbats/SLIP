from __future__ import annotations

import json
import re
from typing import Any, Optional
import collections.abc

# YAML is already a project dependency (imported elsewhere)
import yaml

# TOML: prefer stdlib tomllib (3.11+), else fall back to 'toml' package if available
try:
    import tomllib as _toml_loader  # type: ignore[attr-defined]
    _HAS_TOMLLIB = True
except Exception:
    _HAS_TOMLLIB = False
    try:
        import toml as _toml  # type: ignore[no-redef]
    except Exception:
        _toml = None  # type: ignore[assignment]

# XML/HTML via xmltodict
try:
    import xmltodict
except Exception as e:
    xmltodict = None  # type: ignore[assignment]


# --------------------------
# Helpers
# --------------------------

def _norm_text(data: bytes | bytearray | str, *, encoding: Optional[str] = None) -> str:
    if isinstance(data, (bytes, bytearray)):
        enc = encoding or 'utf-8'
        try:
            return data.decode(enc, errors='replace')
        except Exception:
            return data.decode('utf-8', errors='replace')
    if isinstance(data, str):
        return data
    return str(data)


def _encoding_from_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    m = re.search(r'charset\s*=\s*([^\s;]+)', content_type, re.IGNORECASE)
    if m:
        return m.group(1).strip('"').strip("'")
    return None


def _to_builtin(obj: Any) -> Any:
    # Convert mapping-like OrderedDicts from xmltodict to plain dicts recursively
    if isinstance(obj, list):
        return [_to_builtin(x) for x in obj]
    # xmltodict returns OrderedDict (Mapping)
    if isinstance(obj, collections.abc.Mapping):
        return {k: _to_builtin(v) for k, v in obj.items()}
    return obj


def detect_format(content_type: Optional[str] = None, data_hint: Optional[str] = None) -> Optional[str]:
    """
    Returns a canonical format name among: 'json', 'yaml', 'toml', 'xml'.
    Uses Content-Type first; falls back to simple data sniffing if provided.
    """
    ct = (content_type or "").lower()
    if 'json' in ct:
        return 'json'
    if 'yaml' in ct or 'x-yaml' in ct:
        return 'yaml'
    if 'toml' in ct:
        return 'toml'
    if 'xml' in ct or 'html' in ct or 'xhtml' in ct:
        return 'xml'

    # Heuristics based on data
    if data_hint is not None:
        s = data_hint.lstrip()
        if s.startswith('{') or s.startswith('['):
            # Try JSON first; if it fails, YAML is a superset
            return 'json'
        if s.startswith('<'):
            return 'xml'
        # TOML heuristic is weak; caller should pass content_type when possible.
    return None


# --------------------------
# Public API
# --------------------------

def deserialize(data: bytes | bytearray | str,
                *,
                content_type: Optional[str] = None,
                fmt: Optional[str] = None) -> Any:
    """
    Convert wire data (bytes/string) to native Python/SLIP structures.
    Supported fmt: 'json', 'yaml', 'toml', 'xml'.
    If fmt is None, uses content_type, then sniffing.
    Returns dict/list/scalars for structured formats; returns raw text for others.
    """
    enc = _encoding_from_content_type(content_type)
    text = _norm_text(data, encoding=enc)
    f = (fmt or detect_format(content_type, text))
    if f == 'json':
        try:
            return json.loads(text)
        except Exception:
            # Fallback to YAML if declared JSON but content is actually YAML-like
            try:
                y = yaml.safe_load(text)
                return y
            except Exception:
                return text
    if f == 'yaml':
        try:
            return yaml.safe_load(text)
        except Exception:
            return text
    if f == 'toml':
        if _HAS_TOMLLIB:
            try:
                # tomllib loads bytes; re-encode
                return _toml_loader.loads(text)  # type: ignore[name-defined]
            except Exception:
                return text
        else:
            if _toml is None:
                raise RuntimeError("TOML support requires Python 3.11+ (tomllib) or the 'toml' package")
            try:
                return _toml.loads(text)  # type: ignore[union-attr]
            except Exception:
                return text
    if f == 'xml':
        if xmltodict is None:
            raise RuntimeError("XML/HTML support requires the 'xmltodict' package")
        try:
            parsed = xmltodict.parse(text)
            return _to_builtin(parsed)
        except Exception:
            return text

    # Unknown/unsupported → return text
    return text


def serialize(value: Any,
              *,
              fmt: str,
              pretty: bool = True,
              xml_root: str = "root") -> str:
    """
    Convert a native Python/SLIP value into a textual representation.
    - fmt: 'json' | 'yaml' | 'toml' | 'xml'
    - For XML, if value is not a dict, it will be wrapped under {xml_root: value}
    """
    f = (fmt or '').lower()
    built = _to_builtin(value)
    if f == 'json':
        return json.dumps(built, ensure_ascii=False, indent=2 if pretty else None)
    if f == 'yaml':
        return yaml.safe_dump(built, sort_keys=False)
    if f == 'toml':
        if _HAS_TOMLLIB:
            # tomllib has no dump; require 'toml' package for dumping
            raise RuntimeError("TOML serialization requires the 'toml' package (tomllib is read-only)")
        if _toml is None:
            raise RuntimeError("TOML serialization requires the 'toml' package")
        return _toml.dumps(built)  # type: ignore[union-attr]
    if f == 'xml':
        if xmltodict is None:
            raise RuntimeError("XML serialization requires the 'xmltodict' package")
        root: dict
        if isinstance(built, dict):
            root = built
        else:
            root = {xml_root: built}
        return xmltodict.unparse(root, pretty=pretty)
    raise ValueError(f"Unsupported serialization format: {fmt!r}")


__all__ = [
    "deserialize",
    "serialize",
    "detect_format",
]
