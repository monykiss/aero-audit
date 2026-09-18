"""Space weather as it reaches aviation and orbital operations, from NOAA SWPC's keyless JSON products.

ICAO Annex 3 (since 2019) has global space weather centres issue advisories in three effects,
each at a moderate or severe level: HF communications, GNSS, and radiation at flight levels.
NOAA's R / S / G scales map onto the first two directly enough for a watch: R (radio blackouts,
X-ray flux) drives HF; G (geomagnetic, Kp) drives GNSS and also raises thermospheric density,
which ages orbital elements faster; S (solar radiation storms, proton flux) is the flight-level
radiation concern on polar routes. The mapping used here is written down in ``ICAO_LEVELS`` and
reported with every assessment; the exact advisory thresholds are the centres' to apply.

Findings: SWX-001 GNSS-effect conditions (G/Kp), SWX-002 HF-effect conditions (R), SWX-003
radiation conditions (S), SWX-004 stale scales product, SWX-005 aircraft observed at high latitude
during G/S conditions (cross-domain: which flights are exposed). Passive only: read, never post.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from ..audit.findings import Category, Finding, Severity
from ..config import settings
from ..ingest.http import get_json

SCALES_URL = "https://services.swpc.noaa.gov/products/noaa-scales.json"
KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"
CACHE_DIR = Path("data/space/spaceweather")
STALE_S = 3 * 3600.0
HIGH_LAT_DEG = 60.0
# programme mapping of NOAA scale levels onto the two ICAO advisory levels (see module docstring)
ICAO_LEVELS: dict[str, dict[str, int]] = {"G": {"moderate": 4, "severe": 5}, "R": {"moderate": 3, "severe": 4}, "S": {"moderate": 3, "severe": 4}}
EFFECTS = {"G": "GNSS (and thermospheric drag on LEO objects)", "R": "HF communications (sunlit side)", "S": "radiation at flight levels (polar / high latitude)"}


async def fetch(dest_dir: str | Path = CACHE_DIR) -> Path:
    """Fetch the current scales (and Kp) products with a provenance sidecar; keyless, be polite (products update every few minutes)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30) as client:
        scales = await get_json(client, SCALES_URL, None, {"User-Agent": settings.user_agent})
        try:
            kp = await get_json(client, KP_URL, None, {"User-Agent": settings.user_agent})
        except httpx.HTTPError:
            kp = []
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    payload = {"scales": scales, "kp": kp[-60:] if isinstance(kp, list) else [], "fetched_at": stamp, "source": [SCALES_URL, KP_URL]}
    p = dest / f"swpc_{stamp}.json"
    text = json.dumps(payload, indent=1)
    p.write_text(text)
    p.with_suffix(".json.provenance.json").write_text(json.dumps({"source": payload["source"], "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                                                   "terms": "NOAA SWPC products are US Government works in the public domain; cite NOAA/NWS/SWPC"}, indent=1))
    return p


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = sorted(Path(dest_dir).glob("swpc_*.json")) if Path(dest_dir).is_dir() else []
    files = [f for f in files if not f.name.endswith(".provenance.json")]
    return files[-1] if files else None


def current_scales(payload: dict[str, Any]) -> dict[str, Any]:
    """The 'now' entry of the scales product (key "0"), with observed 24 h maxima and the product time."""
    scales = payload.get("scales", payload)
    now = scales.get("0") or {}
    past = scales.get("-1") or {}

    def lvl(block: dict[str, Any], key: str) -> int:
        try:
            return int((block.get(key) or {}).get("Scale") or 0)
        except (TypeError, ValueError):
            return 0

    def text(block: dict[str, Any], key: str) -> str:
        return str((block.get(key) or {}).get("Text") or "")

    return {"time_stamp": now.get("DateStamp", "") + " " + now.get("TimeStamp", ""),
            "now": {k: {"level": lvl(now, k), "text": text(now, k)} for k in ("R", "S", "G")},
            "past_24h": {k: {"level": lvl(past, k), "text": text(past, k)} for k in ("R", "S", "G")},
            "kp_latest": _kp_latest(payload.get("kp") or [])}


def _kp_latest(kp: list[dict[str, Any]]) -> float | None:
    for row in reversed(kp):
        try:
            return float(row.get("kp_index") if row.get("kp_index") is not None else row.get("estimated_kp"))
        except (TypeError, ValueError):
            continue
    return None


def _icao_level(scale: str, level: int) -> str | None:
    th = ICAO_LEVELS[scale]
    if level >= th["severe"]:
        return "severe"
    if level >= th["moderate"]:
        return "moderate"
    return None


def assess(payload: dict[str, Any], now: float | None = None, stream: str = "swpc") -> tuple[dict[str, Any], list[Finding]]:
    cur = current_scales(payload)
    ts = now if now is not None else time.time()
    fetched = payload.get("fetched_at")
    age_s = None
    if fetched:
        try:
            age_s = ts - _utc_epoch(fetched)
        except ValueError:
            age_s = None
    out: list[Finding] = []
    advisories: dict[str, str | None] = {}
    for scale, rule in (("G", "SWX-001"), ("R", "SWX-002"), ("S", "SWX-003")):
        level = cur["now"][scale]["level"]
        adv = _icao_level(scale, level)
        advisories[scale] = adv
        if adv:
            out.append(Finding(rule_id=rule, title=f"{scale}{level} ({cur['now'][scale]['text'] or 'NOAA scale'}): ICAO {adv} conditions for {EFFECTS[scale]}",
                               severity=Severity.HIGH if adv == "severe" else Severity.MEDIUM, category=Category.OPERATIONS, ts=ts,
                               evidence={"stream": stream, "scale": scale, "level": level, "kp": cur["kp_latest"], "product_time": cur["time_stamp"], "mapping": ICAO_LEVELS[scale]},
                               controls=["ICAO Annex 3 (space weather advisories)", "NOAA space weather scales"],
                               recommendation={"G": "Expect GNSS degradation (ADS-B NACp/NIC drops are weather, not spoofing) and faster element ageing; rescreen conjunctions on fresh elements.",
                                               "R": "HF unreliable on the sunlit side; polar and oceanic operations fall back to SATCOM/CPDLC where equipped.",
                                               "S": "Flight-level radiation: operators may lower polar routes or reroute; note exposure in the flight log."}[scale]))
    if age_s is not None and age_s > STALE_S:
        out.append(Finding(rule_id="SWX-004", title=f"Space weather product is {age_s / 3600:.1f} h old", severity=Severity.LOW, category=Category.DATA_QUALITY, ts=ts,
                           evidence={"stream": stream, "age_s": round(age_s), "fetched_at": fetched}, controls=["ICAO Annex 3"],
                           recommendation="Refresh SWPC products before relying on the assessment."))
    summary = {"product_time": cur["time_stamp"], "scales_now": {k: v["level"] for k, v in cur["now"].items()}, "scales_24h": {k: v["level"] for k, v in cur["past_24h"].items()},
               "kp": cur["kp_latest"], "icao_advisory_conditions": advisories, "age_s": None if age_s is None else round(age_s), "effects": EFFECTS,
               "mapping": ICAO_LEVELS, "findings": len(out)}
    return summary, out


def _utc_epoch(stamp: str) -> float:
    import calendar

    return calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%SZ"))


def exposed_flights(recording: str | Path, advisories: dict[str, str | None], lat_min: float = HIGH_LAT_DEG, max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    """Aircraft observed poleward of ``lat_min`` while G or S conditions hold: the traffic the advisory is about."""
    from ..ingest.replay import iter_recording

    active = [k for k in ("G", "S") if advisories.get(k)]
    seen: dict[str, dict[str, Any]] = {}
    batches = 0
    for b in iter_recording(recording):
        if max_batches and batches >= max_batches:
            break
        batches += 1
        for sv in b.states:
            if sv.on_ground or sv.lat is None or abs(sv.lat) < lat_min:
                continue
            row = seen.setdefault(sv.icao24, {"icao24": sv.icao24, "callsign": (sv.callsign or "").strip(), "max_abs_lat": 0.0, "max_alt_ft": 0.0, "samples": 0, "first_ts": sv.ts})
            row["max_abs_lat"] = max(row["max_abs_lat"], abs(sv.lat))
            row["max_alt_ft"] = max(row["max_alt_ft"], sv.baro_alt_ft or 0.0)
            row["samples"] += 1
    rows = sorted(seen.values(), key=lambda r: -r["max_abs_lat"])
    out: list[Finding] = []
    if active and rows:
        out.append(Finding(rule_id="SWX-005", title=f"{len(rows)} aircraft poleward of {lat_min:g}° during {'/'.join(active)} conditions", severity=Severity.MEDIUM,
                           category=Category.OPERATIONS, ts=rows[0]["first_ts"], icao24=rows[0]["icao24"], callsign=rows[0]["callsign"] or None,
                           evidence={"stream": Path(str(recording)).name, "aircraft": len(rows), "conditions": {k: advisories[k] for k in active}, "lat_min": lat_min,
                                     "top": [r["callsign"] or r["icao24"] for r in rows[:10]]},
                           controls=["ICAO Annex 3", "ICAO Annex 6 (flight data monitoring)"],
                           recommendation="These are the flights an advisory concerns; check they carried the advisory and whether GNSS integrity fields degraded in the same window."))
    return {"recording": str(recording), "lat_min": lat_min, "conditions": {k: advisories.get(k) for k in ("G", "R", "S")}, "aircraft": len(rows), "rows": rows[:50]}, out


__all__ = ["ALERTS_URL", "CACHE_DIR", "EFFECTS", "HIGH_LAT_DEG", "ICAO_LEVELS", "KP_URL", "SCALES_URL", "STALE_S", "assess", "current_scales", "exposed_flights", "fetch", "latest"]
