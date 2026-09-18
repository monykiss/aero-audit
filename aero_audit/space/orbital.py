"""Orbital operations: keyless element sets, SGP4 propagation, conjunction screening, and the
first ORB rules. Propagation is delegated to the MIT-licensed ``sgp4`` package (the ``[space]``
extra); nothing here re-derives the maths.

What is honest about this screen: two-line elements carry no covariance, so a probability of
collision cannot be computed from them. The screen reports minimum separation, time of closest
approach and relative speed, and flags stale elements, which is what an operator needs to know
before asking the owner for a CDM (CCSDS 508.0-B) with covariance. That is the next slice.

Rules
- ORB-001 stale elements: epoch older than MAX_ELEMENT_AGE_DAYS at screening time.
- ORB-002 close approach: minimum separation below THRESHOLD_KM inside the screening window.
- ORB-003 propagation failure: SGP4 returns an error code (decayed or malformed set).
"""

from __future__ import annotations

import itertools
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ..audit.findings import Category, Finding, Severity
from ..config import settings

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"
ELEMENTS_DIR = Path("data/space/elements")
MAX_ELEMENT_AGE_DAYS = 7.0
THRESHOLD_KM = 10.0
COARSE_STEP_S = 60.0
MIN_REL_SPEED_KMS = 0.05  # below this the pair is co-moving (docked modules, formation flying), not a conjunction
FINE_STEP_S = 1.0
GROUPS = ("stations", "active", "visual", "starlink", "gps-ops", "galileo", "weather", "science", "cubesat", "analyst")


@dataclass(frozen=True)
class ElementSet:
    name: str
    line1: str
    line2: str

    @property
    def norad_id(self) -> int:
        return int(self.line1[2:7])

    @property
    def epoch(self) -> datetime:
        yy, ddd = int(self.line1[18:20]), float(self.line1[20:32])
        year = 2000 + yy if yy < 57 else 1900 + yy
        return datetime(year, 1, 1, tzinfo=UTC) + __import__("datetime").timedelta(days=ddd - 1)

    def age_days(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(UTC)) - self.epoch).total_seconds() / 86400.0


def parse_tle(text: str) -> list[ElementSet]:
    """Three-line (name + 2 lines) or two-line sets; checksums are verified per TLE convention."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out: list[ElementSet] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            l1, l2 = lines[i], lines[i + 1]
            name = f"NORAD {l1[2:7].strip()}"
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue
        if _checksum_ok(l1) and _checksum_ok(l2):
            out.append(ElementSet(name, l1, l2))
    return out


def _checksum_ok(line: str) -> bool:
    if len(line) < 69:
        return False
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10 == int(line[68]) if line[68].isdigit() else False


async def fetch_group(group: str = "stations", dest_dir: str | Path = ELEMENTS_DIR) -> Path:
    """Download a CelesTrak group as TLE text with a provenance sidecar (keyless; be polite: cache for hours)."""
    if not re.fullmatch(r"[a-z0-9-]+", group):
        raise ValueError("group must be a CelesTrak group name (letters, digits, hyphens)")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            r = await client.get(CELESTRAK, params={"GROUP": group, "FORMAT": "tle"}, headers={"User-Agent": settings.user_agent})
            r.raise_for_status()
            text = r.text
        except (httpx.ConnectError, httpx.ConnectTimeout):
            text = await _curl_text(f"{CELESTRAK}?GROUP={group}&FORMAT=tle")
    if not parse_tle(text):
        raise ValueError(f"no element sets in CelesTrak response for group '{group}'")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    p = dest / f"celestrak_{group}_{stamp}.tle"
    p.write_text(text)
    import hashlib
    import json

    p.with_suffix(".tle.provenance.json").write_text(json.dumps({"source": f"{CELESTRAK}?GROUP={group}&FORMAT=tle", "fetched_at": stamp,
                                                                 "sha256": hashlib.sha256(text.encode()).hexdigest(), "sets": len(parse_tle(text)),
                                                                 "terms": "CelesTrak data is provided free of charge; cite CelesTrak (Dr. T.S. Kelso)"}, indent=1))
    return p


async def _curl_text(url: str) -> str:
    import asyncio

    proc = await asyncio.create_subprocess_exec("curl", "-fsSL", "-m", "30", "-A", settings.user_agent, url,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise httpx.ConnectError(f"curl exit {proc.returncode}: {err.decode(errors='replace').strip()}")
    return out.decode()


# ---- propagation and screening -----------------------------------------------------------------
def _satrecs(sets: list[ElementSet]) -> list[Any]:
    try:
        from sgp4.api import Satrec
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("orbital screening needs the sgp4 package: uv pip install -e '.[space]'") from e
    return [Satrec.twoline2rv(s.line1, s.line2) for s in sets]


def _jd(dt: datetime) -> tuple[float, float]:
    from sgp4.api import jday

    return jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)


def positions(sets: list[ElementSet], start: datetime, hours: float, step_s: float) -> tuple[list[float], list[list[tuple[float, float, float] | None]], list[int]]:
    """Positions (km, TEME) per set per sample; None where SGP4 reported an error (decayed / bad set)."""
    recs = _satrecs(sets)
    n = int(hours * 3600 / step_s) + 1
    times = [i * step_s for i in range(n)]
    jd0, fr0 = _jd(start)
    grid: list[list[tuple[float, float, float] | None]] = []
    errors: list[int] = []
    for rec in recs:
        row: list[tuple[float, float, float] | None] = []
        err = 0
        for t in times:
            e, r, _ = rec.sgp4(jd0, fr0 + t / 86400.0)
            if e != 0:
                row.append(None)
                err = e
            else:
                row.append((r[0], r[1], r[2]))
        grid.append(row)
        errors.append(err)
    return times, grid, errors


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


@dataclass
class Approach:
    a: ElementSet
    b: ElementSet
    t_s: float
    min_km: float
    rel_speed_kms: float

    def to_dict(self) -> dict[str, Any]:
        return {"a": self.a.name, "a_norad": self.a.norad_id, "b": self.b.name, "b_norad": self.b.norad_id, "tca_s": round(self.t_s, 1),
                "min_km": round(self.min_km, 3), "rel_speed_kms": round(self.rel_speed_kms, 3)}


def positions_array(sets: list[ElementSet], start: datetime, hours: float, step_s: float) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Positions (km, TEME) as an (n, samples, 3) array with NaN where SGP4 reported an error, via SatrecArray."""
    from sgp4.api import SatrecArray

    recs = _satrecs(sets)
    n = int(hours * 3600 / step_s) + 1
    times = np.arange(n, dtype=np.float64) * step_s
    jd0, fr0 = _jd(start)
    jd = np.full(n, jd0)
    fr = fr0 + times / 86400.0
    e, r, _ = SatrecArray(recs).sgp4(jd, fr)
    r = np.asarray(r, dtype=np.float64)
    bad = np.asarray(e) != 0
    r[bad] = np.nan
    errors = [int(row[row != 0][0]) if (row != 0).any() else 0 for row in np.asarray(e)]
    return times, r, errors


def screen(sets: list[ElementSet], start: datetime | None = None, hours: float = 24.0, threshold_km: float = THRESHOLD_KM,
           coarse_step_s: float = COARSE_STEP_S, fine_step_s: float = FINE_STEP_S, max_sets: int = 200,
           min_rel_speed_kms: float = MIN_REL_SPEED_KMS) -> dict[str, Any]:
    """Pairwise minimum separation inside the window: coarse grid, then a fine pass around each coarse minimum
    under 5x the threshold. The coarse pass is one broadcasted distance computation per object (SatrecArray
    propagation, numpy nanmin over the window), so a 150-object group screens in seconds; the fine pass runs only
    for candidate pairs. Same results as ``_screen_reference`` (tested)."""
    start = start or datetime.now(UTC)
    sets = sets[:max_sets]
    times, grid, errors = positions_array(sets, start, hours, coarse_step_s)
    n = len(sets)
    approaches: list[Approach] = []
    recs = _satrecs(sets)
    jd0, fr0 = _jd(start)
    for i in range(n - 1):
        d = np.linalg.norm(grid[i + 1:] - grid[i][None, :, :], axis=2)  # (n-i-1, samples), NaN where either failed
        if np.isnan(d).all():
            continue
        with np.errstate(all="ignore"):
            best_k = np.nanargmin(np.where(np.isnan(d), np.inf, d), axis=1)
        best_d = d[np.arange(len(d)), best_k]
        for off in np.flatnonzero(np.isfinite(best_d) & (best_d <= 5 * threshold_km)):
            j = i + 1 + int(off)
            bt = float(times[best_k[off]])
            lo, hi = max(0.0, bt - coarse_step_s), min(hours * 3600, bt + coarse_step_s)
            ft = np.arange(lo, hi + 1e-9, fine_step_s)
            ea, ra, va = recs[i].sgp4_array(np.full(len(ft), jd0), fr0 + ft / 86400.0)
            eb, rb, vb = recs[j].sgp4_array(np.full(len(ft), jd0), fr0 + ft / 86400.0)
            good = (np.asarray(ea) == 0) & (np.asarray(eb) == 0)
            fine_best_t, fine_best_d, vel = bt, float(best_d[off]), 0.0
            if good.any():
                dd = np.linalg.norm(np.asarray(ra) - np.asarray(rb), axis=1)
                dd = np.where(good, dd, np.inf)
                m = int(np.argmin(dd))
                if dd[m] < fine_best_d:
                    fine_best_t, fine_best_d = float(ft[m]), float(dd[m])
                    vel = float(np.linalg.norm(np.asarray(va)[m] - np.asarray(vb)[m]))
            if fine_best_d <= threshold_km:
                approaches.append(Approach(sets[i], sets[j], fine_best_t, fine_best_d, vel))
    approaches.sort(key=lambda x: x.min_km)
    co_moving = [x for x in approaches if x.rel_speed_kms < min_rel_speed_kms]
    approaches = [x for x in approaches if x.rel_speed_kms >= min_rel_speed_kms]
    return {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": hours, "threshold_km": threshold_km, "sets": len(sets),
            "pairs": len(sets) * (len(sets) - 1) // 2, "approaches": [x.to_dict() for x in approaches],
            "co_moving": [x.to_dict() for x in co_moving], "min_rel_speed_kms": min_rel_speed_kms,
            "propagation_errors": [{"name": s.name, "norad": s.norad_id, "code": e} for s, e in zip(sets, errors, strict=True) if e],
            "element_age_days": {s.name: round(s.age_days(start), 2) for s in sets}, "covariance": "none in TLEs: Pc not computable; request CDMs"}


def _screen_reference(sets: list[ElementSet], start: datetime | None = None, hours: float = 24.0, threshold_km: float = THRESHOLD_KM,
           coarse_step_s: float = COARSE_STEP_S, fine_step_s: float = FINE_STEP_S, max_sets: int = 200,
           min_rel_speed_kms: float = MIN_REL_SPEED_KMS) -> dict[str, Any]:
    """Pairwise minimum separation inside the window: coarse grid, then a fine pass around each coarse minimum
    under 5x the threshold. O(n^2 x samples): keep the set small (a group, a constellation shell, or a watchlist)."""
    start = start or datetime.now(UTC)
    sets = sets[:max_sets]
    times, grid, errors = positions(sets, start, hours, coarse_step_s)
    approaches: list[Approach] = []
    recs = _satrecs(sets)
    jd0, fr0 = _jd(start)
    for (i, a), (j, b) in itertools.combinations(enumerate(sets), 2):
        best_t, best_d = None, math.inf
        for k, t in enumerate(times):
            pa, pb = grid[i][k], grid[j][k]
            if pa is None or pb is None:
                continue
            d = _dist(pa, pb)
            if d < best_d:
                best_t, best_d = t, d
        if best_t is None or best_d > 5 * threshold_km:
            continue
        lo, hi = max(0.0, best_t - coarse_step_s), min(hours * 3600, best_t + coarse_step_s)
        t = lo
        fine_best_t, fine_best_d, vel = best_t, best_d, 0.0
        while t <= hi:
            ea, ra, va = recs[i].sgp4(jd0, fr0 + t / 86400.0)
            eb, rb, vb = recs[j].sgp4(jd0, fr0 + t / 86400.0)
            if ea == 0 and eb == 0:
                d = _dist(ra, rb)
                if d < fine_best_d:
                    fine_best_t, fine_best_d = t, d
                    vel = math.sqrt(sum((va[m] - vb[m]) ** 2 for m in range(3)))
            t += fine_step_s
        if fine_best_d <= threshold_km:
            approaches.append(Approach(a, b, fine_best_t, fine_best_d, vel))
    approaches.sort(key=lambda x: x.min_km)
    co_moving = [x for x in approaches if x.rel_speed_kms < min_rel_speed_kms]
    approaches = [x for x in approaches if x.rel_speed_kms >= min_rel_speed_kms]
    return {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": hours, "threshold_km": threshold_km, "sets": len(sets),
            "pairs": len(sets) * (len(sets) - 1) // 2, "approaches": [x.to_dict() for x in approaches],
            "co_moving": [x.to_dict() for x in co_moving], "min_rel_speed_kms": min_rel_speed_kms,
            "propagation_errors": [{"name": s.name, "norad": s.norad_id, "code": e} for s, e in zip(sets, errors, strict=True) if e],
            "element_age_days": {s.name: round(s.age_days(start), 2) for s in sets}, "covariance": "none in TLEs: Pc not computable; request CDMs"}


def findings(result: dict[str, Any], sets: list[ElementSet], stream: str = "elements") -> list[Finding]:
    now = datetime.strptime(result["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    ts = now.timestamp()
    out: list[Finding] = []
    for s in sets:
        age = s.age_days(now)
        if age > MAX_ELEMENT_AGE_DAYS:
            out.append(Finding(rule_id="ORB-001", title=f"Stale element set: {age:.1f} days old", severity=Severity.MEDIUM, category=Category.DATA_QUALITY,
                               callsign=s.name, ts=ts, evidence={"stream": stream, "norad": s.norad_id, "epoch": s.epoch.isoformat(), "age_days": round(age, 2)},
                               controls=["CCSDS 502.0-B", "NASA-STD-8719.14"], recommendation="Refresh elements before screening; propagation error grows with age."))
    for e in result["propagation_errors"]:
        out.append(Finding(rule_id="ORB-003", title=f"SGP4 propagation error code {e['code']}", severity=Severity.LOW, category=Category.DATA_QUALITY,
                           callsign=e["name"], ts=ts, evidence={"stream": stream, **e}, controls=["CCSDS 502.0-B"],
                           recommendation="Decayed or malformed set; drop it from the screen and check the source."))
    for a in result["approaches"]:
        sev = Severity.HIGH if a["min_km"] < result["threshold_km"] / 2 else Severity.MEDIUM
        out.append(Finding(rule_id="ORB-002", title=f"Close approach {a['min_km']:.2f} km: {a['a']} / {a['b']}", severity=sev, category=Category.SAFETY,
                           callsign=a["a"], ts=ts + a["tca_s"], evidence={"stream": stream, **a, "covariance": "none"},
                           controls=["CCSDS 508.0-B", "ISO 24113"],
                           recommendation="Distance screen only. Request or ingest a CDM with covariance for Pc before any manoeuvre decision."))
    return out


__all__ = ["CELESTRAK", "ELEMENTS_DIR", "GROUPS", "MAX_ELEMENT_AGE_DAYS", "THRESHOLD_KM", "Approach", "ElementSet", "fetch_group",
           "findings", "parse_tle", "positions", "screen"]
