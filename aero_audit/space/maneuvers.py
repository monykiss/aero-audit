"""Orbital state changes from element history: manoeuvres and imminent decay, with no account needed.

Every cached element file (CelesTrak fetches keep their stamp) is a snapshot. Comparing the same
NORAD id across snapshots gives the mean-element history; a jump in semi-major axis or
inclination beyond what drag and modelling noise explain is a manoeuvre (or a re-identification),
and a low, falling perigee with a large B* is an object about to re-enter. Both matter to a
conjunction screen: elements from before a manoeuvre are wrong, and a decaying object's screen
window should be short.

Findings: ORB-006 manoeuvre-scale change between consecutive sets (data quality, MEDIUM), ORB-007
decay imminent: perigee under 200 km or mean-motion decay rate implying re-entry within 30 days
(safety, MEDIUM). Thresholds are programme values stated in the report.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from .orbital import ELEMENTS_DIR, ElementSet, parse_tle

MU_KM3_S2 = 398600.4418
RE_KM = 6378.137
DA_MANEUVER_KM = 2.0  # semi-major-axis change beyond which drag alone is not the explanation (LEO, per day)
DI_MANEUVER_DEG = 0.02
LOW_PERIGEE_KM = 200.0
DECAY_DAYS = 30.0


def mean_elements(s: ElementSet) -> dict[str, float]:
    l1, l2 = s.line1, s.line2
    n_rev = float(l2[52:63])  # rev/day
    n_rad_s = n_rev * 2 * math.pi / 86400.0
    a_km = (MU_KM3_S2 / (n_rad_s ** 2)) ** (1.0 / 3.0)
    e = float("0." + l2[26:33].strip())
    ndot = float(l1[33:43])  # rev/day^2 (first derivative of mean motion / 2)
    bstar_str = l1[53:61].strip()
    bstar = _decimal_exp(bstar_str)
    return {"norad": s.norad_id, "epoch": s.epoch.timestamp(), "a_km": a_km, "e": e, "inc_deg": float(l2[8:16]), "raan_deg": float(l2[17:25]),
            "perigee_km": a_km * (1 - e) - RE_KM, "apogee_km": a_km * (1 + e) - RE_KM, "n_rev_day": n_rev, "ndot_rev_day2": ndot, "bstar": bstar}


def _decimal_exp(tok: str) -> float:
    """TLE assumed-decimal exponent field, e.g. '12345-4' -> 0.12345e-4."""
    tok = tok.replace(" ", "")
    if not tok:
        return 0.0
    sign = -1.0 if tok[0] == "-" else 1.0
    body = tok.lstrip("+-")
    for i in range(1, len(body)):
        if body[i] in "+-":
            mant, exp = body[:i], body[i:]
            try:
                return sign * float("0." + mant) * 10 ** int(exp)
            except ValueError:
                return 0.0
    try:
        return sign * float("0." + body)
    except ValueError:
        return 0.0


def history(files: list[str | Path]) -> dict[int, list[dict[str, float]]]:
    """Mean elements per NORAD id from every file, sorted by epoch; identical epochs are collapsed."""
    hist: dict[int, dict[float, dict[str, float]]] = defaultdict(dict)
    for f in files:
        for s in parse_tle(Path(f).read_text()):
            me = mean_elements(s)
            me["name"] = s.name
            me["file"] = Path(f).name
            hist[s.norad_id][me["epoch"]] = me
    return {k: [v[t] for t in sorted(v)] for k, v in hist.items()}


def decay_days(me: dict[str, float]) -> float | None:
    """Rough time to re-entry from the mean-motion derivative: n grows as the orbit shrinks; treat the current
    rate as constant down to the ~90 min orbit (a ~ RE + 100 km). Upper bound, optimistic for accelerating decay."""
    ndot = me["ndot_rev_day2"] * 2.0  # the TLE field is ndot/2
    if ndot <= 0:
        return None
    n_now = me["n_rev_day"]
    n_reentry = 86400.0 / (2 * math.pi * math.sqrt((RE_KM + 100.0) ** 3 / MU_KM3_S2))  # rev/day at 100 km
    return max((n_reentry - n_now) / ndot, 0.0)


def analyse(files: list[str | Path] | None = None, now: datetime | None = None) -> tuple[dict[str, Any], list[Finding]]:
    files = files if files is not None else sorted(ELEMENTS_DIR.glob("*.tle"))
    hist = history(files)
    ts = (now or datetime.now(UTC)).timestamp()
    out: list[Finding] = []
    changes = []
    decays = []
    for norad, rows in hist.items():
        for prev, cur in pairwise(rows):
            dt_d = max((cur["epoch"] - prev["epoch"]) / 86400.0, 1e-3)
            da = cur["a_km"] - prev["a_km"]
            di = cur["inc_deg"] - prev["inc_deg"]
            # drag lowers a; a rise of any size, or a drop beyond the threshold scaled by elapsed days, is a manoeuvre
            drag_allow = DA_MANEUVER_KM * dt_d
            if da > 0.5 or abs(da) > drag_allow or abs(di) > DI_MANEUVER_DEG:
                row = {"norad": norad, "name": cur["name"], "from_epoch": prev["epoch"], "to_epoch": cur["epoch"], "da_km": round(da, 3), "di_deg": round(di, 4),
                       "d_perigee_km": round(cur["perigee_km"] - prev["perigee_km"], 2), "days": round(dt_d, 2), "files": [prev["file"], cur["file"]]}
                changes.append(row)
                out.append(Finding(rule_id="ORB-006", title=f"{cur['name']}: semi-major axis {da:+.2f} km, inclination {di:+.3f}° over {dt_d:.1f} d", severity=Severity.MEDIUM,
                                   category=Category.DATA_QUALITY, callsign=cur["name"], ts=cur["epoch"], evidence={"stream": "elements", **row, "thresholds": {"da_km_per_day": DA_MANEUVER_KM, "di_deg": DI_MANEUVER_DEG}},
                                   controls=["CCSDS 502.0-B"], recommendation="Manoeuvre or re-identification: rescreen conjunctions with the newer set only and discard approaches computed from the older one."))
        last = rows[-1]
        dd = decay_days(last)
        if last["perigee_km"] < LOW_PERIGEE_KM or (dd is not None and dd < DECAY_DAYS):
            row = {"norad": norad, "name": last["name"], "perigee_km": round(last["perigee_km"], 1), "apogee_km": round(last["apogee_km"], 1), "decay_days_estimate": None if dd is None else round(dd, 1),
                   "bstar": last["bstar"], "epoch": last["epoch"], "age_days": round((ts - last["epoch"]) / 86400.0, 2)}
            decays.append(row)
            out.append(Finding(rule_id="ORB-007", title=f"{last['name']}: perigee {last['perigee_km']:.0f} km" + (f", re-entry in ~{dd:.0f} d at the current decay rate" if dd is not None else ""),
                               severity=Severity.MEDIUM, category=Category.SAFETY, callsign=last["name"], ts=ts, evidence={"stream": "elements", **row, "thresholds": {"perigee_km": LOW_PERIGEE_KM, "days": DECAY_DAYS}},
                               controls=["NASA-STD-8719.14", "ISO 24113"], recommendation="Shorten the screening window and refresh elements daily; reentry predictions belong to the tracking authority (TIP messages)."))
    summary = {"files": [Path(f).name for f in files], "objects": len(hist), "with_history": sum(1 for r in hist.values() if len(r) > 1), "changes": changes, "decaying": decays,
               "thresholds": {"da_km_per_day": DA_MANEUVER_KM, "di_deg": DI_MANEUVER_DEG, "perigee_km": LOW_PERIGEE_KM, "decay_days": DECAY_DAYS}, "findings": len(out)}
    return summary, out


__all__ = ["DA_MANEUVER_KM", "DECAY_DAYS", "DI_MANEUVER_DEG", "LOW_PERIGEE_KM", "analyse", "decay_days", "history", "mean_elements"]
