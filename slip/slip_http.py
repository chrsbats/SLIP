import asyncio
from typing import Optional, Dict, Any

import httpx


def normalize_response_mode(cfg: dict) -> Optional[str]:
    """Return `full` when the caller explicitly requests the HTTP envelope."""
    if "lite" in cfg or "full" in cfg:
        raise ValueError(
            "legacy HTTP response flags were removed; "
            "use response-mode: `full`"
        )
    mode = cfg.get('response-mode')
    if mode is None:
        return None

    from slip.slip_datatypes import (
        IString as _IStr,
        PathLiteral as _PL,
        GetPath as _GP,
        Name as _Name,
    )

    match mode:
        case str() | _IStr():
            s = str(mode).strip().strip('`').lower()
            if s == 'full':
                return s

        case _PL(inner=_GP(segments=[_Name(text=s)])):
            if isinstance(s, str):
                s = s.strip().strip('`').lower()
                if s == 'full':
                    return s

        case _GP(segments=[_Name(text=s)]):
            if isinstance(s, str):
                s = s.strip().strip('`').lower()
                if s == 'full':
                    return s

    raise ValueError("HTTP response-mode only supports `full`")


async def http_request(
    method: str,
    url: str,
    *,
    config: Optional[Dict] = None,
    data: Optional[str] = None,
) -> Any:
    """
    Core HTTP helper.

    response-mode (enum):
      - `full` -> return (status, value, headers) without raising on non-2xx
      - unset -> return the body on 2xx and signal a protocol failure otherwise
    """
    cfg = dict(config or {})
    timeout = float(cfg.pop('timeout', 5.0))
    retries = int(cfg.pop('retries', 2))
    backoff = float(cfg.pop('backoff', 0.2))
    headers = dict(cfg.pop('headers', {}))
    params = dict(cfg.pop('params', {}))

    mode = normalize_response_mode(cfg)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        last_exc = None
        for attempt in range(retries + 1):
            try:
                body = None
                if data is not None:
                    body = (
                        data.encode('utf-8')
                        if isinstance(data, str)
                        else data
                    )
                if body is not None:
                    headers = {**headers}
                    headers.setdefault(
                        "Content-Type",
                        "text/plain; charset=utf-8",
                    )
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    content=body,
                )
                from slip.slip_serialize import deserialize
                ct = resp.headers.get("Content-Type")
                if mode == 'full':
                    value = deserialize(resp.content, content_type=ct)
                    # Lower-case header keys for consistent lookups
                    headers_map = {
                        str(k).lower(): v for k, v in resp.headers.items()
                    }
                    return (int(resp.status_code), value, headers_map)
                # Default strict behavior
                if 200 <= resp.status_code < 300:
                    return deserialize(resp.content, content_type=ct)
                # Non-2xx → raise
                from slip.slip_datatypes import ProtocolFailure

                value = deserialize(resp.content, content_type=ct)
                headers_map = {
                    str(k).lower(): v for k, v in resp.headers.items()
                }
                raise ProtocolFailure(
                    'http',
                    f"HTTP {resp.status_code} for {url}",
                    status=int(resp.status_code),
                    data=value,
                    meta={
                        'headers': headers_map,
                        'url': url,
                        'method': method.upper(),
                    },
                )
            except Exception as e:
                from slip.slip_datatypes import ProtocolFailure

                if isinstance(e, ProtocolFailure):
                    raise
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                raise ProtocolFailure(
                    'http',
                    str(last_exc),
                    meta={'url': url, 'method': method.upper()},
                ) from last_exc


async def http_get(url: str, config: Optional[Dict] = None) -> Any:
    return await http_request('GET', url, config=config)


async def http_put(url: str, data: str, config: Optional[Dict] = None) -> Any:
    return await http_request('PUT', url, config=config, data=data)


async def http_delete(url: str, config: Optional[Dict] = None) -> Any:
    return await http_request('DELETE', url, config=config)


async def http_post(url: str, data: str, config: Optional[Dict] = None) -> Any:
    return await http_request('POST', url, config=config, data=data)
