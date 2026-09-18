#!/usr/bin/env python3
"""Coverage-guided fuzzing of the inputs this tool parses from the outside world, with atheris (libFuzzer).

Targets take arbitrary bytes and must raise only the exceptions their callers expect (ValueError,
KeyError, PermissionError, FileNotFoundError, pydantic ValidationError); anything else is a bug
that a malformed recording, request or file could trigger. Run one target:

    pip install atheris && python fuzz/fuzz_targets.py recording -max_total_time=30

`--smoke` runs every target over a few seed inputs without atheris (the test suite does this), so
the harness itself cannot rot. Targets available on every branch: recording (JSONL replay parser),
engine (state vectors through the rules engine), safe_path (request path confinement),
manifest (report manifest verification).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

EXPECTED: tuple[type[BaseException], ...] = (ValueError, KeyError, PermissionError, FileNotFoundError, TypeError, OSError)
try:  # pydantic raises its own ValidationError (a ValueError subclass in v2, but be explicit)
    from pydantic import ValidationError

    EXPECTED = (*EXPECTED, ValidationError)
except ImportError:  # pragma: no cover
    pass


def target_recording(data: bytes) -> None:
    from aero_audit.ingest.replay import iter_recording

    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as fh:
        fh.write(data)
        path = fh.name
    try:
        for _ in iter_recording(path):
            pass
    except EXPECTED:
        pass
    finally:
        Path(path).unlink(missing_ok=True)


def target_engine(data: bytes) -> None:
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, StateVector

    try:
        import atheris

        fdp = atheris.FuzzedDataProvider(data)
        n = fdp.ConsumeIntInRange(0, 6)
        states = []
        for _ in range(n):
            states.append(StateVector(icao24=fdp.ConsumeUnicodeNoSurrogates(6) or "abc123", callsign=fdp.ConsumeUnicodeNoSurrogates(8) or None, ts=fdp.ConsumeFloat(),
                                      lat=fdp.ConsumeFloatInRange(-95, 95), lon=fdp.ConsumeFloatInRange(-190, 190), baro_alt_ft=fdp.ConsumeFloatInRange(-5000, 90000),
                                      gs_kt=fdp.ConsumeFloatInRange(-10, 3000), track_deg=fdp.ConsumeFloatInRange(-10, 400), vrate_fpm=fdp.ConsumeFloatInRange(-30000, 30000),
                                      squawk=fdp.ConsumeUnicodeNoSurrogates(4) or None, on_ground=fdp.ConsumeBool(), nic=fdp.ConsumeIntInRange(-1, 12), nacp=fdp.ConsumeIntInRange(-1, 12), sil=fdp.ConsumeIntInRange(-1, 4)))
        ts = fdp.ConsumeFloat()
    except ImportError:  # smoke mode: decode the seed as JSON state vectors
        try:
            rows = json.loads(data.decode(errors="replace"))
        except ValueError:
            return
        try:
            states = [StateVector(**r) for r in rows if isinstance(r, dict)]
        except EXPECTED:
            return
        ts = 1_700_000_000.0
    except EXPECTED:
        return
    engine = AuditEngine()
    try:
        engine.process_batch(Batch(ts=ts, provider="fuzz", region="fz", states=states))
        engine.summary()
    except EXPECTED:
        pass


def target_safe_path(data: bytes) -> None:
    from aero_audit.web.security import safe_path

    try:
        safe_path(data.decode(errors="replace"), ("data/recordings", "data/samples"), (".jsonl", ".jsonl.gz"), must_exist=False)
    except EXPECTED:
        pass


def target_manifest(data: bytes) -> None:
    from aero_audit.provenance import verify_manifest

    with tempfile.NamedTemporaryFile("wb", suffix=".manifest.json", delete=False) as fh:
        fh.write(data)
        path = fh.name
    try:
        verify_manifest(path)
    except EXPECTED:
        pass
    finally:
        Path(path).unlink(missing_ok=True)


TARGETS: dict[str, Callable[[bytes], None]] = {"recording": target_recording, "engine": target_engine, "safe_path": target_safe_path, "manifest": target_manifest}

SEEDS: dict[str, list[bytes]] = {
    "recording": [b"", b"{", b'{"ts": 1, "provider": "p", "region": "r", "states": []}\n', b'{"ts": "x"}\n\n{"states": [{"icao24": "abc123", "ts": 1}]}\n', b"\xff\xfe\x00"],
    "engine": [b"[]", b'[{"icao24": "abc123", "ts": 1, "lat": 40.7, "lon": -74.0, "baro_alt_ft": 35000, "gs_kt": 450, "track_deg": 90}]', b'[{"icao24": "abc123", "ts": 1, "lat": 400}]', b"not json"],
    "safe_path": [b"", b"../../etc/passwd", b"data/samples/x.jsonl.gz", b"\x00", b"data/recordings/" + b"a" * 5000 + b".jsonl"],
    "manifest": [b"", b"{}", b'{"files": {"json": {"path": "/nope", "sha256": "0"}}}', b"[1,2,3]", b"\x00\x01"],
}


def smoke() -> int:
    ran = 0
    for name, fn in TARGETS.items():
        for seed in SEEDS[name]:
            fn(seed)
            ran += 1
    print(f"smoke: {ran} seed inputs over {len(TARGETS)} targets, no unexpected exception")
    return 0


def main(argv: list[str]) -> int:
    if "--smoke" in argv:
        return smoke()
    if len(argv) < 2 or argv[1] not in TARGETS:
        print(f"usage: {argv[0]} <{'|'.join(TARGETS)}> [libFuzzer args] | --smoke")
        return 2
    import atheris

    fn = TARGETS[argv[1]]
    atheris.Setup([argv[0], *argv[2:]], fn)
    atheris.Fuzz()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
