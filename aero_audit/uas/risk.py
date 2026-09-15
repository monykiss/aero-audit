"""Airspace density classes and the DAA risk ratio, from recorded traffic.

Two things a UAS safety case asks after the encounter rates (encounters.py):

1. **How busy is this airspace?** Traffic density per cell and altitude band, classed the way the
   MIT Lincoln Laboratory air-risk-class work does (density-driven classes, not a fixed map).
2. **How much does the DAA buy?** The ASTM F3442 lineage expresses DAA effectiveness as a risk
   ratio: P(NMAC with the system) / P(NMAC without it). Without a flown DAA we can still bound
   it from observation: an encounter the alerting could not have resolved is one whose alert
   lead time was shorter than the warning time, so the *mitigated* NMAC count is the subset of
   NMAC-proximate encounters with lead < 25 s.

The class thresholds and the ratio limit are programme values (documented here and in the
report), not quotations from the standards; a certification case takes the applicable numbers
from the standard's tables.

Findings: DAA-003 risk ratio above the programme limit (safety, MEDIUM), DAA-004 dense or very
dense class observed below 3,000 ft where small UAS fly (safety, LOW, informational).
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from ..ingest.replay import iter_recording
from .encounters import MIN_LEAD_S, extract_encounters, summarize_encounters

BANDS: tuple[tuple[str, float, float], ...] = (("surface-1200", -1000.0, 1200.0), ("1200-3000", 1200.0, 3000.0), ("3000-10000", 3000.0, 10000.0), ("above-10000", 10000.0, 1e9))
CELL_DEG = 0.2
# aircraft-hours per 100 nm^2 per hour observed (programme classes; see module docstring)
DENSITY_CLASSES: tuple[tuple[str, float], ...] = (("sparse", 0.05), ("moderate", 0.5), ("dense", 5.0), ("very-dense", math.inf))
RISK_RATIO_LIMIT = 0.2


def _band(alt_ft: float | None) -> str:
    a = alt_ft if alt_ft is not None else 0.0
    for name, lo, hi in BANDS:
        if lo <= a < hi:
            return name
    return BANDS[-1][0]


def _cell_area_nm2(lat_deg: float) -> float:
    return (CELL_DEG * 60.0) * (CELL_DEG * 60.0 * max(math.cos(math.radians(lat_deg)), 0.05))


def density_class(aircraft_hours_per_100nm2_h: float) -> str:
    for name, limit in DENSITY_CLASSES:
        if aircraft_hours_per_100nm2_h < limit:
            return name
    return DENSITY_CLASSES[-1][0]


def density(recording: str | Path, max_batches: int | None = None) -> dict[str, Any]:
    """Aircraft-hours per cell and altitude band, normalised to the area observed and the time span."""
    hours_by: dict[tuple[tuple[int, int], str], float] = defaultdict(float)
    last_ts: dict[str, float] = {}
    t0: float | None = None
    t1: float | None = None
    batches = 0
    for b in iter_recording(recording):
        if max_batches and batches >= max_batches:
            break
        batches += 1
        for sv in b.states:
            if sv.on_ground or sv.lat is None or sv.lon is None:
                continue
            t0 = sv.ts if t0 is None else min(t0, sv.ts)
            t1 = sv.ts if t1 is None else max(t1, sv.ts)
            prev = last_ts.get(sv.icao24)
            dt = min(max(sv.ts - prev, 0.0), 120.0) if prev is not None else 0.0  # cap gaps so a dropout is not counted as presence
            last_ts[sv.icao24] = sv.ts
            hours_by[((int(sv.lat / CELL_DEG), int(sv.lon / CELL_DEG)), _band(sv.baro_alt_ft))] += dt / 3600.0
    span_h = max(((t1 or 0.0) - (t0 or 0.0)) / 3600.0, 1e-6)
    cells: list[dict[str, Any]] = []
    by_band: dict[str, dict[str, Any]] = {name: {"aircraft_hours": 0.0, "cells": 0, "classes": defaultdict(int)} for name, _, _ in BANDS}
    for (cell, band), h in hours_by.items():
        lat_c = (cell[0] + 0.5) * CELL_DEG
        per = h / span_h / (_cell_area_nm2(lat_c) / 100.0)
        cls = density_class(per)
        cells.append({"cell": [round(cell[0] * CELL_DEG, 2), round(cell[1] * CELL_DEG, 2)], "band": band, "aircraft_hours": round(h, 4),
                      "per_100nm2_h": round(per, 4), "class": cls})
        bb = by_band[band]
        bb["aircraft_hours"] += h
        bb["cells"] += 1
        bb["classes"][cls] += 1
    for bb in by_band.values():
        bb["aircraft_hours"] = round(bb["aircraft_hours"], 3)
        bb["classes"] = dict(bb["classes"])
    cells.sort(key=lambda c: -c["per_100nm2_h"])
    return {"recording": str(recording), "span_h": round(span_h, 3), "batches": batches, "cell_deg": CELL_DEG, "bands": by_band,
            "cells": cells[:500], "cells_total": len(cells), "classes": [n for n, _ in DENSITY_CLASSES], "class_limits_per_100nm2_h": [lim if math.isfinite(lim) else None for _, lim in DENSITY_CLASSES]}


def risk_ratio(summary: dict[str, Any], min_lead_s: float = MIN_LEAD_S) -> dict[str, Any]:
    """Observed bound on the DAA risk ratio from an encounter summary (encounters.summarize_encounters):
    NMAC-proximate encounters the alerting could not have resolved over all NMAC-proximate encounters.
    1.0 means the alerting adds nothing observable; 0 means every close encounter had at least the warning time of notice."""
    pairs = summary.get("pairs", [])
    nmac = [p for p in pairs if p.get("nmac_proximate")]
    unresolvable = [p for p in nmac if p.get("lead_time_s") is None or p["lead_time_s"] < min_lead_s]
    ratio = (len(unresolvable) / len(nmac)) if nmac else None
    return {"encounters": len(pairs), "nmac_proximate": len(nmac), "unresolvable": len(unresolvable), "min_lead_s": min_lead_s,
            "risk_ratio": None if ratio is None else round(ratio, 3), "limit": RISK_RATIO_LIMIT,
            "basis": "observed bound: NMAC-proximate encounters whose alert lead was below the warning time, over all NMAC-proximate encounters"}


def assess(recording: str | Path, max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    dens = density(recording, max_batches)
    ex = extract_encounters(recording, max_batches=max_batches)
    enc, _ = summarize_encounters(ex)
    rr = risk_ratio(enc)
    ts = max((p.get("first_ts", 0.0) for p in enc.get("pairs", [])), default=0.0)
    out: list[Finding] = []
    if rr["risk_ratio"] is not None and rr["risk_ratio"] > RISK_RATIO_LIMIT:
        out.append(Finding(rule_id="DAA-003", title=f"Observed DAA risk ratio {rr['risk_ratio']:.2f} above programme limit {RISK_RATIO_LIMIT}", severity=Severity.MEDIUM,
                           category=Category.SAFETY, ts=ts, evidence={"stream": Path(str(recording)).name, **rr}, controls=["ASTM F3442", "RTCA DO-365"],
                           recommendation="Most close encounters gave less than the warning time of notice at this feed's revisit rate; a DAA case needs higher-rate surveillance or a longer alerting horizon."))
    low = {b: v for b, v in dens["bands"].items() if b in ("surface-1200", "1200-3000")}
    dense_cells = sum(v["classes"].get("dense", 0) + v["classes"].get("very-dense", 0) for v in low.values())
    if dense_cells:
        out.append(Finding(rule_id="DAA-004", title=f"{dense_cells} dense low-altitude cell(s) below 3,000 ft", severity=Severity.LOW, category=Category.SAFETY, ts=ts,
                           evidence={"stream": Path(str(recording)).name, "dense_cells": dense_cells, "bands": {k: v["classes"] for k, v in low.items()}},
                           controls=["ASTM F3442", "ICAO Annex 2"],
                           recommendation="Small-UAS operations in these cells face crewed traffic at the densities that drive the encounter rate; plan corridors or times accordingly."))
    summary = {"density": {k: v for k, v in dens.items() if k != "cells"}, "top_cells": dens["cells"][:20], "risk_ratio": rr,
               "flight_hours": ex.get("flight_hours"), "findings": len(out)}
    return summary, out


__all__ = ["BANDS", "DENSITY_CLASSES", "RISK_RATIO_LIMIT", "assess", "density", "density_class", "risk_ratio"]
