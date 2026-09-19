"""Ground tracks of objects about to re-enter, against airports and recorded traffic.

An uncontrolled reentry ends somewhere along the last orbits' ground track; the tracking authority's
TIP messages narrow the window, and the FAA and its counterparts close airspace under the predicted
footprint (14 CFR 91.143 and the reentry NOTAM practice). Before any of that exists, the question an
airline dispatcher or an ANSP can already answer with public data is: whose airports and which
flights sit under the track of an object the element history says is decaying? This module answers
that. It propagates each decaying object (perigee under the low-perigee threshold or the mean-motion
derivative implying reentry within the watch window, from space/maneuvers.py) with SGP4, converts
TEME positions to latitude and longitude, and builds a corridor of +-width around the sub-satellite
track for the next hours.

Findings: REN-001 aircraft under the corridor at the time the object passed (safety, LOW: exposure
to a possible footprint, not a prediction of impact); REN-002 airports under the corridor
(operations, LOW); REN-003 element set older than the reentry freshness limit for a decaying
object, so the corridor itself is unreliable (data quality). Passive only; the authority's
prediction, when there is one, supersedes all of this.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..audit.findings import Category, Finding, Severity
from ..knowledge.airports import AIRPORTS
from .maneuvers import DECAY_DAYS, LOW_PERIGEE_KM, decay_days, mean_elements
from .orbital import ELEMENTS_DIR, ElementSet, parse_tle, positions_array

WIDTH_NM = 50.0
HOURS = 6.0
STEP_S = 30.0
FRESH_S = 48 * 3600.0
WGS84_A = 6378.137
WGS84_F = 1 / 298.257223563
_E2 = WGS84_F * (2 - WGS84_F)
NM_PER_DEG = 60.0


def gmst_rad(jd_ut1: np.ndarray | float) -> np.ndarray | float:
    """Greenwich mean sidereal time (IAU 1982 polynomial, Vallado eq. 3-45), radians."""
    t = (np.asarray(jd_ut1, dtype=np.float64) - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t**2 - 6.2e-6 * t**3
    return np.mod(np.deg2rad(sec / 240.0), 2 * np.pi)


def teme_to_geodetic(r_teme: np.ndarray, jd: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """TEME (km) positions at Julian dates -> geodetic latitude (deg), longitude (deg, -180..180), height (km).
    TEME to a pseudo-Earth-fixed frame by the GMST rotation only (no polar motion, no nutation): a few hundred
    metres of error, irrelevant at a corridor width of tens of miles."""
    theta = gmst_rad(jd)
    x, y, z = r_teme[..., 0], r_teme[..., 1], r_teme[..., 2]
    lon = np.rad2deg(np.arctan2(y, x) - theta)
    lon = (lon + 180.0) % 360.0 - 180.0
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - _E2))
    for _ in range(4):  # Bowring-style iteration converges in two or three passes at LEO heights
        n = WGS84_A / np.sqrt(1 - _E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1 - _E2 * n / (n + h)))
    n = WGS84_A / np.sqrt(1 - _E2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - n
    return np.rad2deg(lat), lon, h


def _jd(dt: datetime) -> float:
    from sgp4.api import jday

    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
    return jd + fr


def subpoints(sets: list[ElementSet], start: datetime, hours: float = HOURS, step_s: float = STEP_S) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """Per set and sample: epoch seconds, latitude, longitude, height (NaN where SGP4 failed)."""
    times, r, errors = positions_array(sets, start, hours, step_s)
    jd = _jd(start) + times / 86400.0
    lat, lon, h = teme_to_geodetic(r, np.broadcast_to(jd, r.shape[:2]))
    ts = start.timestamp() + times
    return ts, lat, lon, h, errors


def candidates(files: list[str | Path] | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Newest element set per object among those the history flags as decaying, with the flags that put it there."""
    files = files if files is not None else sorted(ELEMENTS_DIR.glob("*.tle"))
    ts_now = (now or datetime.now(UTC)).timestamp()
    newest: dict[int, tuple[float, ElementSet, str]] = {}
    for f in files:
        try:
            for s in parse_tle(Path(f).read_text()):
                epoch = mean_elements(s)["epoch"]
                if s.norad_id not in newest or epoch > newest[s.norad_id][0]:
                    newest[s.norad_id] = (epoch, s, Path(f).name)
        except (OSError, ValueError):
            continue
    out = []
    for norad, (epoch, s, fname) in sorted(newest.items()):
        me = mean_elements(s)
        dd = decay_days(me)
        low = me["perigee_km"] < LOW_PERIGEE_KM
        soon = dd is not None and dd < DECAY_DAYS
        if low or soon:
            out.append({"norad": norad, "name": s.name, "set": s, "file": fname, "epoch": epoch, "age_h": round((ts_now - epoch) / 3600.0, 1),
                        "perigee_km": round(me["perigee_km"], 1), "apogee_km": round(me["apogee_km"], 1), "decay_days_estimate": None if dd is None else round(dd, 1),
                        "flags": [x for x, on in (("low_perigee", low), ("decay_within_window", soon)) if on]})
    return out


def _dist_nm(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    dlat = (lat2 - lat1) * NM_PER_DEG
    dlon = ((lon2 - lon1 + 180.0) % 360.0 - 180.0) * NM_PER_DEG * math.cos(math.radians(lat1))
    return np.hypot(dlat, dlon)


def exposure(cands: list[dict[str, Any]], recording: str | Path | None = None, start: datetime | None = None, hours: float = HOURS, step_s: float = STEP_S,
             width_nm: float = WIDTH_NM, now: datetime | None = None, max_batches: int | None = None, max_track_points: int = 240) -> tuple[dict[str, Any], list[Finding]]:
    """Corridors for the candidates from `start` (default: now) and what lies under them."""
    ts_now = (now or datetime.now(UTC)).timestamp()
    start = start or datetime.fromtimestamp(ts_now, UTC)
    out: list[Finding] = []
    rows = []
    if not cands:
        return {"objects": 0, "from": start.isoformat(), "hours": hours, "step_s": step_s, "width_nm": width_nm, "recording": str(recording) if recording else None,
                "with_airports_under": 0, "with_aircraft_under": 0, "rows": [], "findings": 0}, out
    sets = [c["set"] for c in cands]
    ts, lat, lon, h, errors = subpoints(sets, start, hours, step_s)
    states: list[tuple[float, float, float, float | None, str, str]] = []
    if recording is not None:
        from ..ingest.replay import iter_recording

        for batches, b in enumerate(iter_recording(recording)):
            if max_batches and batches >= max_batches:
                break
            states.extend((sv.ts, sv.lat, sv.lon, sv.baro_alt_ft, sv.icao24, (sv.callsign or "").strip()) for sv in b.states if sv.lat is not None and sv.lon is not None and not sv.on_ground)
    for i, c in enumerate(cands):
        la, lo, hh = lat[i], lon[i], h[i]
        ok = ~np.isnan(la)
        row: dict[str, Any] = {k: v for k, v in c.items() if k != "set"}
        row.update({"sgp4_error": errors[i], "samples": int(ok.sum()), "airports_under": [], "aircraft_under": []})
        if ok.sum() == 0:
            rows.append(row)
            continue
        stride = max(1, int(ok.sum() // max_track_points))
        idx = np.flatnonzero(ok)[::stride]
        row["track"] = [[round(float(ts[j])), round(float(la[j]), 3), round(float(lo[j]), 3), round(float(hh[j]), 1)] for j in idx]
        for a in AIRPORTS.values():
            d = _dist_nm(a.lat, a.lon, la[ok], lo[ok])
            j = int(np.argmin(d))
            if d[j] <= width_nm:
                row["airports_under"].append({"icao": a.icao, "name": a.name, "major": a.major, "min_nm": round(float(d[j]), 1), "ts": round(float(ts[ok][j])), "height_km": round(float(hh[ok][j]), 1)})
        row["airports_under"].sort(key=lambda r: r["min_nm"])
        if states:
            seen: dict[str, dict[str, Any]] = {}
            t_ok = ts[ok]
            for sts, slat, slon, salt, icao24, cs in states:
                j = int(np.argmin(np.abs(t_ok - sts)))
                if abs(t_ok[j] - sts) > step_s:
                    continue
                d = float(_dist_nm(slat, slon, la[ok][j : j + 1], lo[ok][j : j + 1])[0])
                if d <= width_nm and (icao24 not in seen or d < seen[icao24]["min_nm"]):
                    seen[icao24] = {"icao24": icao24, "callsign": cs, "min_nm": round(d, 1), "alt_ft": salt, "ts": sts}
            row["aircraft_under"] = sorted(seen.values(), key=lambda r: r["min_nm"])[:50]
        rows.append(row)
        name = c["name"] or str(c["norad"])
        ev = {"stream": "elements", "norad": c["norad"], "name": name, "perigee_km": c["perigee_km"], "decay_days_estimate": c["decay_days_estimate"], "flags": c["flags"],
              "corridor": {"hours": hours, "width_nm": width_nm, "from": start.isoformat()}}
        if row["aircraft_under"]:
            first = row["aircraft_under"][0]
            out.append(Finding(rule_id="REN-001", title=f"{len(row['aircraft_under'])} aircraft under the track of decaying object {name} as it passed", severity=Severity.LOW,
                               category=Category.SAFETY, ts=first["ts"], icao24=first["icao24"], callsign=first["callsign"] or None,
                               evidence={**ev, "recording": Path(str(recording)).name if recording else None, "aircraft": row["aircraft_under"][:15]},
                               controls=["14 CFR 91.143", "ICAO Doc 4444 (reentry NOTAM practice)"],
                               recommendation="Exposure, not impact: the object is still in orbit. Watch for the tracking authority's TIP message and the reentry NOTAM; then plan around the published footprint."))
        if row["airports_under"]:
            majors = [a["icao"] for a in row["airports_under"] if a["major"]]
            out.append(Finding(rule_id="REN-002", title=f"{len(row['airports_under'])} airports under the {hours:g} h corridor of decaying object {name}" + (f" incl. {', '.join(majors[:5])}" if majors else ""),
                               severity=Severity.LOW, category=Category.OPERATIONS, ts=ts_now, callsign=name,
                               evidence={**ev, "airports": row["airports_under"][:25]}, controls=["14 CFR 91.143"],
                               recommendation="Informational until a footprint is published; a corridor this wide covers many airports on every pass."))
        if (ts_now - c["epoch"]) > FRESH_S:
            out.append(Finding(rule_id="REN-003", title=f"{name}: element set {c['age_h']:.0f} h old for an object flagged decaying", severity=Severity.LOW,
                               category=Category.DATA_QUALITY, ts=ts_now, callsign=name, evidence={**ev, "age_h": c["age_h"], "fresh_limit_h": FRESH_S / 3600.0},
                               controls=["CCSDS 502.0-B"], recommendation="Refetch elements: decay accelerates and a two-day-old set no longer places the object on the right pass."))
    summary = {"objects": len(rows), "from": start.isoformat(), "hours": hours, "step_s": step_s, "width_nm": width_nm, "recording": str(recording) if recording else None,
               "with_airports_under": sum(1 for r in rows if r["airports_under"]), "with_aircraft_under": sum(1 for r in rows if r["aircraft_under"]), "rows": rows, "findings": len(out)}
    return summary, out


def analyse(files: list[str | Path] | None = None, recording: str | Path | None = None, start: datetime | None = None, hours: float = HOURS, step_s: float = STEP_S,
            width_nm: float = WIDTH_NM, now: datetime | None = None, max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    cands = candidates(files, now)
    summary, fs = exposure(cands, recording, start, hours, step_s, width_nm, now, max_batches)
    summary["files"] = [Path(f).name for f in (files if files is not None else sorted(ELEMENTS_DIR.glob("*.tle")))]
    summary["thresholds"] = {"perigee_km": LOW_PERIGEE_KM, "decay_days": DECAY_DAYS, "fresh_h": FRESH_S / 3600.0}
    return summary, fs


__all__ = ["FRESH_S", "HOURS", "STEP_S", "WIDTH_NM", "analyse", "candidates", "exposure", "gmst_rad", "subpoints", "teme_to_geodetic"]
