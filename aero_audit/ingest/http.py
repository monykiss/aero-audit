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
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from ..config import settings

BACKEND = os.getenv("AERO_HTTP_BACKEND", "auto")  # auto | httpx | curl
_use_curl = BACKEND == "curl"  # sticky: once httpx fails to connect, stay on curl for the process


def using_curl() -> bool:
    """True once the process has switched to the curl transport (or was configured for it)."""
    return _use_curl


def switch_to_curl() -> None:
    global _use_curl
    _use_curl = True


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
    from .. import observability as obs

    host = urlsplit(url).netloc
    t0 = time.perf_counter()
    try:
        result = await _get_json(client, url, params, headers)
    except Exception as e:
        obs.METRICS.inc("aero_feed_requests_total", host=host, outcome=type(e).__name__)
        obs.METRICS.observe("aero_feed_request_seconds", time.perf_counter() - t0, host=host)
        obs.log_event("feed.error", "warning", host=host, error=f"{type(e).__name__}: {str(e)[:160]}")
        raise
    obs.METRICS.inc("aero_feed_requests_total", host=host, outcome="ok")
    obs.METRICS.observe("aero_feed_request_seconds", time.perf_counter() - t0, host=host)
    return result


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None,
                    headers: dict[str, str] | None = None) -> Any:
    if not using_curl():
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()
        except (httpx.ConnectTimeout, httpx.ConnectError) as e:
            if BACKEND == "httpx":
                raise
            print(f"[http] httpx connect failed ({type(e).__name__}); using curl transport from now on", flush=True)
            switch_to_curl()
    return await curl_json(url, params, headers)


def download_file(url: str, target: str | Path, headers: dict[str, str] | None = None, max_bytes: int | None = None,
                  timeout: float = 120.0) -> tuple[int, str]:
    """Stream ``url`` to ``target``; returns (bytes, sha256). Uses httpx, or curl once httpx cannot connect
    (the same sticky fallback as get_json). Refuses to keep more than ``max_bytes``."""
    import hashlib
    import subprocess

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    hdrs = {"User-Agent": settings.user_agent, **(headers or {})}

    def _hash_and_size() -> tuple[int, str]:
        digest = hashlib.sha256()
        n = 0
        with open(target, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                n += len(chunk)
                digest.update(chunk)
        return n, digest.hexdigest()

    if not using_curl():
        try:
            digest = hashlib.sha256()
            n = 0
            with httpx.Client(timeout=timeout, follow_redirects=True) as client, client.stream("GET", url, headers=hdrs) as r:
                r.raise_for_status()
                with open(target, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        n += len(chunk)
                        if max_bytes is not None and n > max_bytes:
                            raise ValueError(f"{url} exceeds max_bytes={max_bytes}")
                        digest.update(chunk)
                        fh.write(chunk)
            return n, digest.hexdigest()
        except (httpx.ConnectTimeout, httpx.ConnectError) as e:
            target.unlink(missing_ok=True)
            if BACKEND == "httpx":
                raise
            print(f"[http] httpx connect failed ({type(e).__name__}); using curl transport from now on", flush=True)
            switch_to_curl()
        except ValueError:
            target.unlink(missing_ok=True)
            raise
    args = ["curl", "-fsSL", "-m", str(int(timeout)), "-A", settings.user_agent, "-o", str(target)]
    if max_bytes is not None:
        args += ["--max-filesize", str(max_bytes)]
    for k, v in hdrs.items():
        if k.lower() != "user-agent":
            args += ["-H", f"{k}: {v}"]
    proc = subprocess.run([*args, url], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        target.unlink(missing_ok=True)
        if proc.returncode == 63:
            raise ValueError(f"{url} exceeds max_bytes={max_bytes}")
        raise httpx.ConnectError(f"curl exit {proc.returncode}: {proc.stderr.strip()}")
    return _hash_and_size()

