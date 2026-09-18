"""Encounters from surveillance recordings: pairs of airborne aircraft close enough to matter,
scored per sample with the well-clear definitions, then aggregated into rates a safety case
can use (violations per flight hour, NMAC-proximate encounters, alert lead time).

Findings: DAA-001 well-clear violation observed (safety, HIGH when NMAC-proximate), DAA-002
alert lead time below the warning time (safety, MEDIUM).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from ..ingest.replay import iter_recording
from ..models import StateVector
from .wellclear import FT_PER_NM, evaluate, relative_geometry

CANDIDATE_NM = 10.0
CANDIDATE_FT = 3000.0
NMAC_H_FT = 500.0
NMAC_V_FT = 100.0
MIN_LEAD_S = 25.0  # a violation that arrives with less than the warning time is the finding


def _airborne(sv: StateVector) -> bool:
    return bool(sv.has_position and not sv.on_ground and sv.gs_kt is not None and sv.track_deg is not None and sv.baro_alt_ft is not None
                and sv.baro_alt_ft > 500)


def extract_encounters(recording: str | Path, candidate_nm: float = CANDIDATE_NM, candidate_ft: float = CANDIDATE_FT,
                       max_batches: int | None = None) -> dict[str, Any]:
    pairs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    first_seen: dict[str, float] = {}
    last_seen: dict[str, float] = {}
    batches = 0
    for b in iter_recording(recording):
        if max_batches and batches >= max_batches:
            break
        batches += 1
        air = [sv for sv in b.states if _airborne(sv)]
        for sv in air:
            first_seen.setdefault(sv.icao24, sv.ts)
            last_seen[sv.icao24] = sv.ts
        # coarse bucket by 0.2 deg cells to keep this O(n) for national batches
        cells: dict[tuple[int, int], list[StateVector]] = defaultdict(list)
        for sv in air:
            cells[(int(sv.lat / 0.2), int(sv.lon / 0.2))].append(sv)
        for (ci, cj), members in cells.items():
            neigh: list[StateVector] = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    neigh += cells.get((ci + di, cj + dj), [])
            for a in members:
                for c in neigh:
                    if c.icao24 <= a.icao24:
                        continue
                    dz = abs((c.baro_alt_ft or 0) - (a.baro_alt_ft or 0))
                    if dz > candidate_ft:
                        continue
                    s, v = relative_geometry(a.lat, a.lon, a.gs_kt or 0, a.track_deg or 0, c.lat, c.lon, c.gs_kt or 0, c.track_deg or 0)
                    r_nm = (s[0] ** 2 + s[1] ** 2) ** 0.5 / FT_PER_NM
                    if r_nm > candidate_nm:
                        continue
                    vz = ((c.vrate_fpm or 0) - (a.vrate_fpm or 0)) / 60.0
                    ev = evaluate(s, v, (c.baro_alt_ft or 0) - (a.baro_alt_ft or 0), vz)
                    ev.update({"ts": b.ts, "region": b.region, "a": a.icao24, "b": c.icao24, "a_callsign": (a.callsign or "").strip(),
                               "b_callsign": (c.callsign or "").strip(), "alt_ft": a.baro_alt_ft})
                    pairs[(a.icao24, c.icao24)].append(ev)
    flight_hours = sum((last_seen[k] - first_seen[k]) for k in first_seen) / 3600.0
    return {"recording": str(recording), "batches": batches, "aircraft_airborne": len(first_seen), "flight_hours": round(flight_hours, 2),
            "pairs": {f"{a}:{c}": samples for (a, c), samples in pairs.items()}}


def summarize_encounters(ex: dict[str, Any]) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []
    violations = 0
    nmac = 0
    alerts = 0
    leads: list[float] = []
    rows = []
    for key, samples in ex["pairs"].items():
        samples = sorted(samples, key=lambda e: e["ts"])
        viol = [e for e in samples if not e["well_clear"]]
        first_alert = next((e["ts"] for e in samples if e["alert_level"] > 0), None)
        first_viol = viol[0]["ts"] if viol else None
        lead = (first_viol - first_alert) if (first_alert is not None and first_viol is not None) else None
        min_range = min(e["range_ft"] for e in samples)
        min_dz = min(abs(e["dz_ft"]) for e in samples)
        is_nmac = any(e["range_ft"] <= NMAC_H_FT and abs(e["dz_ft"]) <= NMAC_V_FT for e in samples)
        max_alert = max(e["alert_level"] for e in samples)
        if max_alert:
            alerts += 1
        if viol:
            violations += 1
            if lead is not None:
                leads.append(lead)
        if is_nmac:
            nmac += 1
        row = {"pair": key, "samples": len(samples), "min_range_ft": min_range, "min_dz_ft": round(min_dz, 1), "min_hmd_ft": min(e["hmd_ft"] for e in samples),
               "violation": bool(viol), "nmac_proximate": is_nmac, "max_alert": max_alert, "lead_time_s": None if lead is None else round(lead, 1),
               "callsigns": f"{samples[0]['a_callsign'] or samples[0]['a']} / {samples[0]['b_callsign'] or samples[0]['b']}", "region": samples[0]["region"],
               "first_ts": samples[0]["ts"], "alt_ft": samples[0]["alt_ft"]}
        rows.append(row)
        if viol:
            e0 = viol[0]
            findings.append(Finding(rule_id="DAA-001", title=f"Well-clear violation: {row['callsigns']} at {e0['range_ft']:.0f} ft / {abs(e0['dz_ft']):.0f} ft",
                                    severity=Severity.HIGH if is_nmac else Severity.MEDIUM, category=Category.SAFETY, icao24=samples[0]["a"],
                                    callsign=samples[0]["a_callsign"] or None, ts=e0["ts"],
                                    evidence={"pair": key, "range_ft": e0["range_ft"], "dz_ft": e0["dz_ft"], "hmd_ft": e0["hmd_ft"], "tau_mod_s": e0["tau_mod_s"],
                                              "nmac_proximate": is_nmac, "region": e0["region"], "definition": "DO-365 Phase 1 (DTHR 4000 ft, ZTHR 450 ft, TTHR 35 s)"},
                                    controls=["RTCA DO-365", "ASTM F3442"],
                                    recommendation="Surveillance-derived; confirm with the operator's own data before treating it as a loss of separation."))
            if lead is not None and lead < MIN_LEAD_S:
                findings.append(Finding(rule_id="DAA-002", title=f"Alert lead time {lead:.0f} s below the warning time for {row['callsigns']}", severity=Severity.MEDIUM,
                                        category=Category.SAFETY, icao24=samples[0]["a"], ts=e0["ts"], evidence={"pair": key, "lead_time_s": round(lead, 1), "min_lead_s": MIN_LEAD_S},
                                        controls=["RTCA DO-365"], recommendation="At this update rate the encounter developed faster than the alerting time; higher-rate surveillance is needed for DAA use."))
    rows.sort(key=lambda r: (not r["violation"], r["min_range_ft"]))
    fh = ex["flight_hours"] or 0.0
    summary = {"recording": ex["recording"], "batches": ex["batches"], "aircraft_airborne": ex["aircraft_airborne"], "flight_hours": fh,
               "encounter_pairs": len(rows), "pairs_with_alert": alerts, "violations": violations, "nmac_proximate": nmac,
               "violations_per_flight_hour": round(violations / fh, 4) if fh else None, "nmac_per_flight_hour": round(nmac / fh, 4) if fh else None,
               "median_lead_time_s": round(sorted(leads)[len(leads) // 2], 1) if leads else None, "pairs": rows[:200],
               "definition": "well clear per DO-365 Phase 1 / DAIDALUS defaults; NMAC-proximate = 500 ft horizontal and 100 ft vertical"}
    return summary, findings


__all__ = ["CANDIDATE_FT", "CANDIDATE_NM", "MIN_LEAD_S", "NMAC_H_FT", "NMAC_V_FT", "extract_encounters", "summarize_encounters"]
