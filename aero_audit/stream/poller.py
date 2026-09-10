"""Async polling loop that turns a REST provider into a batch stream, with JSONL recording."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from ..config import Region
from ..ingest.base import Provider
from ..models import Batch


class JsonlRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a")  # noqa: SIM115 - held open across the stream, closed in close()
        self.batches = 0

    def write(self, batch: Batch) -> None:
        self._fh.write(batch.model_dump_json() + "\n")
        self._fh.flush()
        self.batches += 1

    def close(self) -> None:
        self._fh.close()


def _log(msg: str) -> None:
    print(msg, flush=True)


async def stream_batches(
    provider: Provider,
    region: Region | list[Region],
    interval_s: float = 10.0,
    duration_s: float | None = None,
    recorder: JsonlRecorder | None = None,
    max_failures: int = 10,
) -> AsyncIterator[Batch]:
    """Yield one Batch per poll, round-robin over regions.

    `interval_s` is the gap between consecutive polls of *any* region, so each region is
    revisited every interval * n_regions. HTTP 429 sleeps for Retry-After (default 30 s) and
    retries the same region without counting as a failure; other errors back off exponentially
    and abort after `max_failures` consecutive failures.
    """
    regions = [region] if isinstance(region, Region) else list(region)
    start = time.time()
    failures = 0
    i = 0
    while duration_s is None or time.time() - start < duration_s:
        reg = regions[i % len(regions)]
        t0 = time.time()
        try:
            batch = await provider.fetch(reg)
            failures = 0
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = float(e.response.headers.get("Retry-After", 30))
                _log(f"[stream] 429 from {provider.name} for {reg.key}; sleeping {wait:.0f}s")
                await asyncio.sleep(wait)
                continue  # same region, no failure counted
            failures += 1
            _log(f"[stream] HTTP {e.response.status_code} for {reg.key} ({failures}/{max_failures})")
            if failures >= max_failures:
                raise
            await asyncio.sleep(min(60, interval_s * 2**failures))
            continue
        except Exception as e:
            failures += 1
            _log(f"[stream] fetch failed for {reg.key} ({failures}/{max_failures}): {type(e).__name__}: {e}")
            if failures >= max_failures:
                raise
            await asyncio.sleep(min(60, interval_s * 2**failures))
            continue
        i += 1
        if recorder:
            recorder.write(batch)
        yield batch
        await asyncio.sleep(max(0.0, interval_s - (time.time() - t0)))
