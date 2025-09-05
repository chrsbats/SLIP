import asyncio
from typing import Optional, Dict, Any
import os
import sys
import httpx

def normalize_response_mode(cfg: dict) -> Optional[str]:
    """
    Returns one of 'lite' | 'full' | 'none' | None based on cfg['response-mode'] (or legacy flags).
    Accepts string/IString or path-like (`ok`-style) values.
    """
    mode = cfg.get('response-mode')

    # Legacy flags when not explicitly set
    if mode is None:
        if cfg.get('lite') is True:
            return 'lite'
        if cfg.get('full') is True:
            return 'full'
        return None

    from slip.slip_datatypes import IString as _IStr, PathLiteral as _PL, GetPath as _GP, Name as _Name

    match mode:
        case str() | _IStr():
            s = str(mode).strip().strip('`').lower()
            return s if s in ('lite', 'full', 'none') else None

        case _PL(inner=_GP(segments=[_Name(text=s)])):
            if isinstance(s, str):
                s = s.strip().strip('`').lower()
                return s if s in ('lite', 'full', 'none') else None
            return None

        case _GP(segments=[_Name(text=s)]):
            if isinstance(s, str):
                s = s.strip().strip('`').lower()
                return s if s in ('lite', 'full', 'none') else None
            return None

        case _:
            return None

async def http_request(method: str, url: str, *, config: Optional[Dict] = None, data: Optional[str] = None) -> Any:
    """
    Core HTTP helper.

    response-mode (enum):
      - `lite`  -> return (status: int, value: Any, headers: dict[str,str]) without raising on non-2xx
      - `full`  -> same tuple; callers package into a dict with meta
      - `none`/unset -> default behavior: return deserialized body on 2xx; raise on non-2xx
    """
    cfg = dict(config or {})
    timeout = float(cfg.pop('timeout', 5.0))
    retries = int(cfg.pop('retries', 2))
    backoff = float(cfg.pop('backoff', 0.2))
    headers = dict(cfg.pop('headers', {}))
    params = dict(cfg.pop('params', {}))

    mode = normalize_response_mode(cfg)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        last_exc = None
        for attempt in range(retries + 1):
            try:
                body = (data.encode('utf-8') if isinstance(data, str) else data) if data is not None else None
                if body is not None:
                    headers = {**headers}
                    headers.setdefault("Content-Type", "text/plain; charset=utf-8")
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    content=body,
                )
                from slip.slip_serialize import deserialize
                ct = resp.headers.get("Content-Type")
                if mode in ('lite', 'full'):
                    value = deserialize(resp.content, content_type=ct)
                    # Lower-case header keys for consistent lookups
                    headers_map = {str(k).lower(): v for k, v in resp.headers.items()}
                    return (int(resp.status_code), value, headers_map)
                # Default strict behavior
                if 200 <= resp.status_code < 300:
                    return deserialize(resp.content, content_type=ct)
                # Non-2xx → raise
                preview = (resp.text or "")[:200]
                raise RuntimeError(f"HTTP {resp.status_code} for {url}: {preview}")
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                raise last_exc

async def http_get(url: str, config: Optional[Dict] = None) -> Any:
    return await http_request('GET', url, config=config)

async def http_put(url: str, data: str, config: Optional[Dict] = None) -> Any:
    return await http_request('PUT', url, config=config, data=data)

async def http_delete(url: str, config: Optional[Dict] = None) -> Any:
    return await http_request('DELETE', url, config=config)

async def http_post(url: str, data: str, config: Optional[Dict] = None) -> Any:
    return await http_request('POST', url, config=config, data=data)
