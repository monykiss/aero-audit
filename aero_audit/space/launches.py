"""Launch windows joined to air traffic: The Space Devs' Launch Library 2 (keyless, rate-limited)
gives upcoming and recent launches with pad coordinates and windows; the recordings give the
aircraft. 14 CFR 91.143 lets the FAA restrict flight near space operations, and every launch
carries a hazard area; the question a regulator or an airline dispatcher asks is whether traffic
actually stayed out of it, and how much was displaced.

Findings: LCH-001 aircraft inside the hazard radius of an active pad during its window (safety),
LCH-002 launch record stale or in hold while the window is open (data quality), LCH-003 window
overlaps the recording but the pad is outside the recorded region (informational: coverage gap).
Passive only. Cite The Space Devs when publishing (their terms ask for attribution).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import httpx

from ..audit.findings import Category, Finding, Severity
from ..config import settings
from ..ingest.http import get_json

LL2 = "https://ll.thespacedevs.com/2.2.0/launch/"
CACHE_DIR = Path("data/space/launches")
HAZARD_NM = 50.0
STALE_S = 24 * 3600.0
NM_PER_DEG = 60.0


async def fetch(mode: str = "upcoming", limit: int = 20, dest_dir: str | Path = CACHE_DIR) -> Path:
    """Fetch upcoming or previous launches with a provenance sidecar. Keyless tier: 15 requests per hour, so cache."""
    if mode not in ("upcoming", "previous"):
        raise ValueError("mode must be upcoming or previous")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30) as client:
        payload = await get_json(client, f"{LL2}{mode}/", {"limit": min(max(limit, 1), 100), "mode": "detailed"}, {"User-Agent": settings.user_agent})
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    payload = {"launches": parse(payload), "fetched_at": stamp, "source": f"{LL2}{mode}/", "mode": mode}
    text = json.dumps(payload, indent=1)
    p = dest / f"ll2_{mode}_{stamp}.json"
    p.write_text(text)
    p.with_suffix(".json.provenance.json").write_text(json.dumps({"source": payload["source"], "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                                                   "terms": "The Space Devs Launch Library 2: free tier, attribution requested (https://thespacedevs.com)"}, indent=1))
    return p


def parse(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce LL2 launch records to what the join needs; tolerant of missing pads and windows."""
    out = []
    for r in payload.get("results", payload.get("launches", [])):
        if "pad_lat" in r:  # already reduced
            out.append(r)
            continue
        pad = r.get("pad") or {}
        loc = pad.get("location") or {}
        status = r.get("status") or {}
        out.append({"id": r.get("id"), "name": r.get("name"), "provider": ((r.get("launch_service_provider") or {}).get("name")),
                    "status": status.get("abbrev") or status.get("name"), "net": r.get("net"), "window_start": r.get("window_start"), "window_end": r.get("window_end"),
                    "pad": pad.get("name"), "location": loc.get("name"), "country": loc.get("country_code"),
                    "pad_lat": _f(pad.get("latitude")), "pad_lon": _f(pad.get("longitude")), "last_updated": r.get("last_updated"), "url": r.get("url")})
    return out


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    import calendar

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            st = time.strptime(iso.replace("+00:00", "Z") if fmt.endswith("Z") else iso, fmt)
            return calendar.timegm(st)
        except ValueError:
            continue
    return None


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = [f for f in sorted(Path(dest_dir).glob("ll2_*.json")) if not f.name.endswith(".provenance.json")] if Path(dest_dir).is_dir() else []
    return files[-1] if files else None


def _dist_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * NM_PER_DEG
    dlon = (lon2 - lon1) * NM_PER_DEG * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def join_traffic(payload: dict[str, Any], recording: str | Path, hazard_nm: float = HAZARD_NM, now: float | None = None,
                 max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    """For every launch whose window overlaps the recording, count aircraft inside the hazard radius during the window,
    and the traffic in the same radius outside the window (the displacement baseline)."""
    from ..ingest.replay import iter_recording

    launches = payload.get("launches", [])
    ts_now = now if now is not None else time.time()
    windows = []
    for launch in launches:
        w0, w1 = _ts(launch.get("window_start")) or _ts(launch.get("net")), _ts(launch.get("window_end")) or _ts(launch.get("net"))
        if w0 is None or launch.get("pad_lat") is None or launch.get("pad_lon") is None:
            continue
        windows.append((launch, w0, (w1 or w0) + 1.0))
    rec_t0: float | None = None
    rec_t1: float | None = None
    inside: dict[str, dict[str, Any]] = {}
    baseline: dict[str, set[str]] = {}
    batches = 0
    bbox = [90.0, 180.0, -90.0, -180.0]
    for b in iter_recording(recording):
        if max_batches and batches >= max_batches:
            break
        batches += 1
        for sv in b.states:
            if sv.lat is None or sv.lon is None or sv.on_ground:
                continue
            rec_t0 = sv.ts if rec_t0 is None else min(rec_t0, sv.ts)
            rec_t1 = sv.ts if rec_t1 is None else max(rec_t1, sv.ts)
            bbox = [min(bbox[0], sv.lat), min(bbox[1], sv.lon), max(bbox[2], sv.lat), max(bbox[3], sv.lon)]
            for launch, w0, w1 in windows:
                d = _dist_nm(sv.lat, sv.lon, launch["pad_lat"], launch["pad_lon"])
                if d > hazard_nm:
                    continue
                key = launch["id"] or launch["name"]
                if w0 <= sv.ts <= w1:
                    row = inside.setdefault(key, {"launch": launch["name"], "aircraft": {}, "window": [w0, w1]})
                    ac = row["aircraft"].setdefault(sv.icao24, {"icao24": sv.icao24, "callsign": (sv.callsign or "").strip(), "min_nm": d, "alt_ft": sv.baro_alt_ft, "ts": sv.ts})
                    if d < ac["min_nm"]:
                        ac.update({"min_nm": d, "alt_ft": sv.baro_alt_ft, "ts": sv.ts})
                else:
                    baseline.setdefault(key, set()).add(sv.icao24)
    out: list[Finding] = []
    rows = []
    for launch, w0, w1 in windows:
        key = launch["id"] or launch["name"]
        overlaps = rec_t0 is not None and rec_t1 is not None and w0 <= rec_t1 and w1 >= rec_t0
        pad_in_box = bbox[0] - 1 <= launch["pad_lat"] <= bbox[2] + 1 and bbox[1] - 1 <= launch["pad_lon"] <= bbox[3] + 1
        n_in = len(inside.get(key, {}).get("aircraft", {}))
        n_base = len(baseline.get(key, set()))
        upd = _ts(launch.get("last_updated"))
        stale = upd is not None and (ts_now - upd) > STALE_S and w0 <= ts_now <= w1
        rows.append({"id": key, "name": launch["name"], "provider": launch.get("provider"), "status": launch.get("status"), "pad": launch.get("pad"), "location": launch.get("location"),
                     "window_start": launch.get("window_start"), "window_end": launch.get("window_end"), "overlaps_recording": overlaps, "pad_in_recorded_region": pad_in_box,
                     "aircraft_inside_during_window": n_in, "aircraft_inside_outside_window": n_base, "hazard_nm": hazard_nm})
        if n_in:
            acs = sorted(inside[key]["aircraft"].values(), key=lambda a: a["min_nm"])
            out.append(Finding(rule_id="LCH-001", title=f"{n_in} aircraft within {hazard_nm:g} nm of {launch.get('pad') or 'pad'} during the {launch['name']} window", severity=Severity.MEDIUM,
                               category=Category.SAFETY, ts=acs[0]["ts"], icao24=acs[0]["icao24"], callsign=acs[0]["callsign"] or None,
                               evidence={"stream": Path(str(recording)).name, "launch": launch["name"], "window": [launch.get("window_start"), launch.get("window_end")],
                                         "closest": acs[:10], "baseline_outside_window": n_base},
                               controls=["14 CFR 91.143", "FAA JO 7400.2 (special use airspace)"],
                               recommendation="Compare with the published TFR/NOTAM hazard area; aircraft inside a real hazard area during the window are a coordination failure, otherwise the radius here is wider than the NOTAM."))
        if stale:
            out.append(Finding(rule_id="LCH-002", title=f"{launch['name']}: record last updated {(ts_now - upd) / 3600:.0f} h ago while its window is open", severity=Severity.LOW,
                               category=Category.DATA_QUALITY, ts=ts_now, evidence={"stream": "ll2", "launch": launch["name"], "status": launch.get("status"), "last_updated": launch.get("last_updated")},
                               controls=["14 CFR 91.143"], recommendation="Refresh the launch record; holds and scrubs move windows."))
        if overlaps and not pad_in_box:
            out.append(Finding(rule_id="LCH-003", title=f"{launch['name']} window overlaps the recording but its pad is outside the recorded region", severity=Severity.LOW,
                               category=Category.DATA_QUALITY, ts=w0, evidence={"stream": Path(str(recording)).name, "launch": launch["name"], "pad": [launch["pad_lat"], launch["pad_lon"]], "bbox": bbox},
                               controls=["14 CFR 91.143"], recommendation="Record the launch region to observe the airspace closure; this recording cannot."))
    summary = {"recording": str(recording), "launches": len(launches), "with_windows": len(windows), "overlapping": sum(1 for r in rows if r["overlaps_recording"]),
               "hazard_nm": hazard_nm, "rows": rows, "findings": len(out)}
    return summary, out


__all__ = ["CACHE_DIR", "HAZARD_NM", "LL2", "STALE_S", "fetch", "join_traffic", "latest", "parse"]
