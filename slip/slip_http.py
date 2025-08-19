import asyncio
from typing import Optional, Dict, Any
import os
import sys
import httpx

async def http_request(method: str, url: str, *, config: Optional[Dict] = None, data: Optional[str] = None) -> str:
    cfg = dict(config or {})
    timeout = float(cfg.pop('timeout', 5.0))
    retries = int(cfg.pop('retries', 2))
    backoff = float(cfg.pop('backoff', 0.2))
    headers = dict(cfg.pop('headers', {}))
    params = dict(cfg.pop('params', {}))
    # Remaining cfg entries are ignored by default

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
                if 200 <= resp.status_code < 300:
                    from slip.slip_serialize import deserialize
                    ct = resp.headers.get("Content-Type")
                    return deserialize(resp.content, content_type=ct)
                # Non-2xx → raise
                body = (resp.text or "")[:200]
                raise RuntimeError(f"HTTP {resp.status_code} for {url}: {body}")
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                raise last_exc

async def http_get(url: str, config: Optional[Dict] = None) -> str:
    return await http_request('GET', url, config=config)

async def http_put(url: str, data: str, config: Optional[Dict] = None) -> str:
    return await http_request('PUT', url, config=config, data=data)

async def http_delete(url: str, config: Optional[Dict] = None) -> str:
    return await http_request('DELETE', url, config=config)

async def http_post(url: str, data: str, config: Optional[Dict] = None) -> str:
    return await http_request('POST', url, config=config, data=data)
