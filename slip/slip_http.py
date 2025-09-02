import asyncio
from typing import Optional, Dict, Any
import os
import sys
import httpx

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

    def _normalize_response_mode_from_cfg(c: dict) -> Optional[str]:
        mode = c.get('response-mode')
        # Back-compat flags
        if mode is None:
            try:
                if c.get('lite') is True:
                    return 'lite'
                if c.get('full') is True:
                    return 'full'
            except Exception:
                pass
        # Strings (incl. IString)
        try:
            from slip.slip_datatypes import IString as _IStr
            if isinstance(mode, (str, _IStr)):
                s = str(mode).strip().strip('`').lower()
                return s if s in ('lite', 'full', 'none') else None
        except Exception:
            pass
        # Path-literal or get-path
        try:
            from slip.slip_datatypes import PathLiteral as _PL, GetPath as _GP, Name as _Name
            if isinstance(mode, _PL):
                inner = getattr(mode, 'inner', None)
                if isinstance(inner, _GP) and len(inner.segments) == 1 and isinstance(inner.segments[0], _Name):
                    s = inner.segments[0].text
                    if isinstance(s, str):
                        s = s.strip().strip('`').lower()
                        return s if s in ('lite', 'full', 'none') else None
            if isinstance(mode, _GP) and len(mode.segments) == 1 and hasattr(mode.segments[0], 'text'):
                s = mode.segments[0].text
                if isinstance(s, str):
                    s = s.strip().strip('`').lower()
                    return s if s in ('lite', 'full', 'none') else None
        except Exception:
            pass
        return None

    mode = _normalize_response_mode_from_cfg(cfg)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        last_exc = None
        for attempt in range(retries + 1):
            try:
                body = (data.encode('utf-8') if isinstance(data, str) else data) if data is not None else None
                if body is not None:
                    headers = {**headers}
                    headers.setdefault("Content-Type", "text/plain; charset=utf-8")
                if os.environ.get("SLIP_HTTP_DEBUG"):
                    try:
                        blen = len(body) if body is not None else 0
                        print(f"[SLIP_HTTP_DEBUG] -> {method.upper()} {url} headers={headers} params={params} body_len={blen}", file=sys.stderr)
                    except Exception:
                        pass
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    content=body,
                )
                if os.environ.get("SLIP_HTTP_DEBUG"):
                    try:
                        ct = resp.headers.get("Content-Type")
                        preview = (resp.text or "")
                        print(f"[SLIP_HTTP_DEBUG] <- {resp.status_code} len={len(preview)} ct={ct}", file=sys.stderr)
                    except Exception:
                        pass
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
