"""HTTP GET-JSON with a curl fallback.

On some hosts a per-process network filter lets the system curl connect while Python sockets
time out. `get_json` tries httpx first and, on a *connect*-level failure, shells out to curl so
captures keep running. Status handling is preserved: non-2xx responses (including 429) raise
`httpx.HTTPStatusError` so the poller's back-off logic works for both transports.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import settings

BACKEND = os.getenv("AERO_HTTP_BACKEND", "auto")  # auto | httpx | curl
_use_curl = BACKEND == "curl"  # sticky: once httpx fails to connect, stay on curl for the process


async def curl_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                    timeout: float = 30.0) -> Any:
    full = url + ("?" + urlencode(params) if params else "")
    args = ["curl", "-sS", "-m", str(int(timeout)), "-A", settings.user_agent, "-w", "\n%{http_code}"]
    for k, v in (headers or {}).items():
        args += ["-H", f"{k}: {v}"]
    args.append(full)
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise httpx.ConnectError(f"curl exit {proc.returncode}: {err.decode(errors='replace').strip()}")
    body, _, code = out.rpartition(b"\n")
    status = int(code or b"0")
    request = httpx.Request("GET", full)
    if status >= 400:
        response = httpx.Response(status, request=request, content=body)
        raise httpx.HTTPStatusError(f"HTTP {status} for {full}", request=request, response=response)
    return json.loads(body)


async def get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None) -> Any:
    global _use_curl
    if not _use_curl:
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()
        except (httpx.ConnectTimeout, httpx.ConnectError) as e:
            if BACKEND == "httpx":
                raise
            print(f"[http] httpx connect failed ({type(e).__name__}); using curl transport from now on", flush=True)
            _use_curl = True
    return await curl_json(url, params, headers)
