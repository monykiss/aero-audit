"""Space Data Link Security expectations (CCSDS 355.0-B) applied to ingested telemetry: every packet
carries an authentication status, and the audit says what it accepted on trust.

The toolkit never terminates a real space link; NASA CryptoLib and the ground segment do. What it
can do is refuse to pretend. A packet stream in the JSON layout below carries, per packet, the
SDLS-style security header fields (security parameter index ``spi``, sequence number ``seq``) and
a MAC over the canonical payload. With the key for that SPI in the environment
(``AERO_SDLS_KEY_<spi>``, UTF-8 bytes or hex), each packet is verified with HMAC-SHA256 and its
status recorded: ``verified``, ``failed``, ``no-key`` (a MAC we cannot check) or
``unauthenticated`` (no MAC at all). Verified streams also get an anti-replay check on the
sequence number, the second thing SDLS promises.

Layout::

    {"stream": "demo", "packets": [{"spi": 1, "seq": 1, "t_s": 0.0, "speed_mps": 0.0, "altitude_km": 0.0, "mac": "<hex>"}, ...]}

Findings: SPC-006 packet failed authentication (security, HIGH); SPC-007 telemetry accepted
without authentication, one per stream with the counts (data quality, LOW); SPC-008 sequence
number replayed or regressed in an authenticated stream (security, MEDIUM). The physics rules
(SPC-001..005) run on the points regardless, so a forged packet is caught twice when it is also
implausible, and an implausible genuine one is still reported.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity

ENV_PREFIX = "AERO_SDLS_KEY_"
STATUSES = ("verified", "failed", "no-key", "unauthenticated")
_HEX = re.compile(r"^[0-9a-fA-F]+$")


def key_bytes(value: str) -> bytes:
    """Even-length hex is decoded; anything else is taken as UTF-8 (a passphrase-style key)."""
    v = value.strip()
    if len(v) >= 16 and len(v) % 2 == 0 and _HEX.match(v):
        return bytes.fromhex(v)
    return v.encode()


def keys_from_env(env: dict[str, str] | None = None) -> dict[int, bytes]:
    src = env if env is not None else os.environ
    out: dict[int, bytes] = {}
    for k, v in src.items():
        if k.startswith(ENV_PREFIX) and v:
            try:
                out[int(k[len(ENV_PREFIX):])] = key_bytes(v)
            except ValueError:
                continue
    return out


def canonical(pkt: dict[str, Any]) -> bytes:
    """The bytes the MAC covers: SPI, sequence and the three telemetry fields at fixed precision, so a re-serialised
    packet verifies identically."""
    return f"{int(pkt['spi'])}|{int(pkt['seq'])}|{float(pkt['t_s']):.6f}|{float(pkt['speed_mps']):.6f}|{float(pkt['altitude_km']):.6f}".encode()


def mac(pkt: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical(pkt), hashlib.sha256).hexdigest()


def sign(packets: list[dict[str, Any]], key: bytes) -> list[dict[str, Any]]:
    """Attach a MAC to every packet (test fixtures and simulators; a real link signs on board)."""
    return [{**p, "mac": mac(p, key)} for p in packets]


def verify(packets: list[dict[str, Any]], keys: dict[int, bytes] | None = None) -> list[dict[str, Any]]:
    """Per packet: its identity, its authentication status and whether its sequence number replays an earlier one
    (only meaningful for verified packets: an attacker who cannot forge a MAC can still replay a captured packet)."""
    keys = keys if keys is not None else keys_from_env()
    rows: list[dict[str, Any]] = []
    last_seq: dict[int, int] = {}
    for i, p in enumerate(packets):
        spi = int(p.get("spi", 0) or 0)
        seq = int(p.get("seq", i))
        given = p.get("mac")
        if not given:
            status = "unauthenticated"
        elif spi not in keys:
            status = "no-key"
        else:
            status = "verified" if hmac.compare_digest(str(given).lower(), mac(p, keys[spi])) else "failed"
        replay = False
        if status == "verified":
            if spi in last_seq and seq <= last_seq[spi]:
                replay = True
            else:
                last_seq[spi] = seq
        rows.append({"index": i, "spi": spi, "seq": seq, "t_s": float(p.get("t_s", 0.0)), "status": status, "replay": replay})
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"packets": len(rows), **counts, "replays": sum(1 for r in rows if r["replay"]), "spis": sorted({r["spi"] for r in rows}),
            "trusted_share": round(counts["verified"] / len(rows), 4) if rows else None}


def findings(rows: list[dict[str, Any]], stream: str = "telemetry", max_each: int = 20) -> list[Finding]:
    out: list[Finding] = []
    failed = [r for r in rows if r["status"] == "failed"]
    for r in failed[:max_each]:
        out.append(Finding(rule_id="SPC-006", title=f"packet seq {r['seq']} (SPI {r['spi']}) failed authentication", severity=Severity.HIGH, category=Category.SECURITY,
                           ts=r["t_s"], callsign=stream, evidence={"stream": stream, **r}, controls=["CCSDS 355.0-B (SDLS)", "NASA-STD-1006"],
                           recommendation="Discard the packet; a MAC mismatch is a forged, corrupted or re-keyed frame. Check the key for the SPI before trusting the stream again."))
    unauth = [r for r in rows if r["status"] in ("unauthenticated", "no-key")]
    if unauth:
        s = summary(rows)
        out.append(Finding(rule_id="SPC-007", title=f"{len(unauth)} of {len(rows)} packets accepted without authentication ({s['unauthenticated']} without MAC, {s['no-key']} without a key)",
                           severity=Severity.LOW, category=Category.DATA_QUALITY, ts=unauth[0]["t_s"], callsign=stream, evidence={"stream": stream, **s},
                           controls=["CCSDS 355.0-B (SDLS)"], recommendation="Analyses on this stream rest on trust in the transport; obtain the SPI keys or an authenticated feed before acting on its findings."))
    for r in [x for x in rows if x["replay"]][:max_each]:
        out.append(Finding(rule_id="SPC-008", title=f"packet seq {r['seq']} (SPI {r['spi']}) replays or regresses the sequence", severity=Severity.MEDIUM, category=Category.SECURITY,
                           ts=r["t_s"], callsign=stream, evidence={"stream": stream, **r}, controls=["CCSDS 355.0-B (SDLS anti-replay)"],
                           recommendation="A valid MAC on an old sequence number is a replayed frame; drop it and check the link's anti-replay window."))
    return out


def load_packets(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    d = json.loads(Path(path).read_text())
    pk = d.get("packets") if isinstance(d, dict) else None
    if not isinstance(pk, list):
        raise TypeError("expected an object with a 'packets' list")
    return [p for p in pk if isinstance(p, dict)], str(d.get("stream") or Path(path).stem)


def is_packet_file(path: str | Path) -> bool:
    p = Path(path)
    if p.suffix.lower() != ".json":
        return False
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(d, dict) and isinstance(d.get("packets"), list)


__all__ = ["ENV_PREFIX", "STATUSES", "canonical", "findings", "is_packet_file", "key_bytes", "keys_from_env", "load_packets", "mac", "sign", "summary", "verify"]
