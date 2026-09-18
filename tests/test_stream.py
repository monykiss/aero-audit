"""The stream package: the JSONL recorder round-trips batches through the replay reader, and the polling loop
round-robins regions, records what it yields, tolerates a 429 with Retry-After, and aborts after max_failures."""

import asyncio
import gzip

import httpx
import pytest

from aero_audit.config import REGIONS
from aero_audit.ingest.replay import iter_recording
from aero_audit.models import Batch, StateVector
from aero_audit.stream.poller import JsonlRecorder, stream_batches


def _batch(region: str, n: int, ts: float = 1_700_000_000.0) -> Batch:
    return Batch(ts=ts, provider="fake", region=region, states=[StateVector(icao24=f"a{i:05x}", ts=ts, source="synthetic", lat=40.0 + i * 0.01, lon=-74.0, baro_alt_ft=3000.0 + i) for i in range(n)])


class FakeProvider:
    name = "fake"

    def __init__(self, fail_first: int = 0, rate_limit_once: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_first = fail_first
        self.rate_limit_once = rate_limit_once

    async def fetch(self, region) -> Batch:
        self.calls.append(region.key)
        if self.rate_limit_once:
            self.rate_limit_once = False
            req = httpx.Request("GET", "https://example.invalid")
            raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, headers={"Retry-After": "0"}, request=req))
        if self.fail_first > 0:
            self.fail_first -= 1
            raise ConnectionError("down")
        return _batch(region.key, 3 + len(self.calls))


def _regions(n: int):
    regs = list(REGIONS.values()) if isinstance(REGIONS, dict) else list(REGIONS)
    return regs[:n]


def test_recorder_round_trips_through_the_replay_reader(tmp_path):
    p = tmp_path / "rec.jsonl"
    rec = JsonlRecorder(p)
    rec.write(_batch("nyc", 2))
    rec.write(_batch("nyc", 5, ts=1_700_000_010.0))
    rec.close()
    assert rec.batches == 2
    back = list(iter_recording(p))
    assert [len(b) for b in back] == [2, 5] and back[1].ts == 1_700_000_010.0 and back[0].states[1].icao24 == "a00001"
    gz = tmp_path / "rec.jsonl.gz"
    with gzip.open(gz, "wt") as fh:
        fh.write(p.read_text())
    assert [len(b) for b in iter_recording(gz)] == [2, 5]


def test_stream_round_robins_records_and_survives_a_rate_limit(tmp_path):
    regs = _regions(2)
    assert len(regs) == 2
    prov = FakeProvider(rate_limit_once=True)
    rec = JsonlRecorder(tmp_path / "s.jsonl")

    async def run():
        out = []
        async for b in stream_batches(prov, regs, interval_s=0.0, recorder=rec):
            out.append(b)
            if len(out) == 4:
                break
        return out

    got = asyncio.run(run())
    rec.close()
    assert [b.region for b in got] == [regs[0].key, regs[1].key, regs[0].key, regs[1].key]  # the 429 retried the same region
    assert prov.calls[0] == prov.calls[1] == regs[0].key and rec.batches == 4
    assert [len(b) for b in iter_recording(tmp_path / "s.jsonl")] == [len(b) for b in got]


def test_stream_backs_off_then_aborts_after_max_failures():
    regs = _regions(1)

    async def run(prov, max_failures):
        out = []
        async for b in stream_batches(prov, regs, interval_s=0.0, recorder=None, max_failures=max_failures):
            out.append(b)
            break
        return out

    got = asyncio.run(run(FakeProvider(fail_first=1), 3))
    assert len(got) == 1  # one failure, then a batch
    with pytest.raises(ConnectionError):
        asyncio.run(run(FakeProvider(fail_first=5), 2))
