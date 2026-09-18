"""Well-clear and density trends across recordings: the study a safety office runs monthly.

One recording gives a rate; a directory of them gives a trend. For every recording this computes
the encounter summary (violations and NMAC-proximate pairs per flight hour, median alert lead)
and the low-altitude density picture, orders them by first timestamp, and fits a least-squares
slope of the violation rate against time. Finding DAA-005 fires when the rate is rising across at
least three recordings and the latest is well above the first (programme factor 1.5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from ..ingest.replay import RECORDING_SUFFIXES
from .encounters import extract_encounters, summarize_encounters
from .risk import density

RISE_FACTOR = 1.5
MIN_RECORDINGS = 3


def find_recordings(folder: str | Path, pattern: str = "*") -> list[Path]:
    root = Path(folder)
    files = [p for p in root.glob(pattern) if p.is_file() and any(p.name.endswith(s) for s in RECORDING_SUFFIXES)]
    return sorted(files)


def row_for(recording: str | Path, max_batches: int | None = None) -> dict[str, Any]:
    ex = extract_encounters(recording, max_batches=max_batches)
    summ, _ = summarize_encounters(ex)
    dens = density(recording, max_batches)
    low = {b: v["classes"] for b, v in dens["bands"].items() if b in ("surface-1200", "1200-3000")}
    from ..ingest.replay import iter_recording

    first_ts = min((p["first_ts"] for p in summ["pairs"]), default=None)
    if first_ts is None:  # no encounter pairs in the window: the recording still has a place on the time axis
        first_ts = next((b.ts for b in iter_recording(recording)), None)
    fh = summ["flight_hours"] or 0.0
    return {"recording": Path(str(recording)).name, "first_ts": first_ts, "flight_hours": fh, "aircraft": summ["aircraft_airborne"], "encounter_pairs": summ["encounter_pairs"],
            "violations": summ["violations"], "violations_per_fh": summ["violations_per_flight_hour"], "nmac_proximate": summ["nmac_proximate"],
            "nmac_per_fh": round(summ["nmac_proximate"] / fh, 4) if fh else None, "median_lead_s": summ["median_lead_time_s"],
            "dense_low_cells": sum(c.get("dense", 0) + c.get("very-dense", 0) for c in low.values()), "regions": sorted({p["region"] for p in summ["pairs"]})}


def _slope(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def assess_rows(rows: list[dict[str, Any]], stream: str = "recordings") -> tuple[dict[str, Any], list[Finding]]:
    rows = sorted([r for r in rows if r.get("first_ts") is not None], key=lambda r: r["first_ts"])
    xs = [(r["first_ts"] - rows[0]["first_ts"]) / 86400.0 for r in rows] if rows else []
    ys = [r["violations_per_fh"] or 0.0 for r in rows]
    slope = _slope(xs, ys)  # violations per flight hour, per day
    out: list[Finding] = []
    rising = bool(rows) and len(rows) >= MIN_RECORDINGS and slope is not None and slope > 0 and (ys[0] == 0 or ys[-1] >= RISE_FACTOR * ys[0]) and ys[-1] > 0
    if rising:
        out.append(Finding(rule_id="DAA-005", title=f"Well-clear violation rate rising across {len(rows)} recordings: {ys[0]:.3f} -> {ys[-1]:.3f} per flight hour",
                           severity=Severity.MEDIUM, category=Category.SAFETY, ts=rows[-1]["first_ts"],
                           evidence={"stream": stream, "recordings": [r["recording"] for r in rows], "rates": ys, "slope_per_day": round(slope, 6), "rise_factor": RISE_FACTOR},
                           controls=["RTCA DO-365", "ASTM F3442"],
                           recommendation="Check whether the feed's revisit rate or coverage changed before reading this as more encounters; then compare the regions with the density trend."))
    summary = {"recordings": len(rows), "span_days": round(xs[-1], 2) if xs else 0.0, "rows": rows, "slope_violations_per_fh_per_day": None if slope is None else round(slope, 6),
               "first_rate": ys[0] if ys else None, "last_rate": ys[-1] if ys else None, "total_flight_hours": round(sum(r["flight_hours"] for r in rows), 2),
               "rise_factor": RISE_FACTOR, "min_recordings": MIN_RECORDINGS, "findings": len(out)}
    return summary, out


def trend(recordings: list[str | Path], max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    return assess_rows([row_for(r, max_batches) for r in recordings])


__all__ = ["MIN_RECORDINGS", "RISE_FACTOR", "assess_rows", "find_recordings", "row_for", "trend"]
