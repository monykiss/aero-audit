"""Flight-ecosystem enrichment: who operates each aircraft, what it is, what it is doing, where.

Every aircraft in a batch gets an operator (from the callsign designator), a type category,
a flight phase (ground, departure, climb, cruise, descent, arrival, approach, pattern, terminal,
level), and its nearest airport within 40 nm. From those, per-airport and per-operator tables
describe the whole picture: departures and arrivals in progress, ground traffic, overhead flow,
holds, emergencies, findings, and integrity compliance by operator.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from .audit.findings import SEVERITY_ORDER, Finding
from .knowledge import AIRPORTS, Airport, nearest_airport, operator_of, type_info
from .models import Batch, StateVector

AIRPORT_RADIUS_NM = 40.0
APPROACH_NM, APPROACH_AGL_FT = 15.0, 3000.0
TERMINAL_AGL_FT = 10000.0
CRUISE_FT = 18000.0
VRATE_FPM = 300.0

PHASES = ("ground", "departure", "climb", "cruise", "level", "descent", "arrival", "approach", "pattern", "terminal")


@dataclass
class Enriched:
    icao24: str
    operator_code: str
    operator: str
    operator_country: str
    operator_cat: str
    type_code: str | None
    type_name: str
    type_cat: str
    phase: str
    airport: str | None
    airport_nm: float | None
    agl_ft: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def phase_of(sv: StateVector, apt: Airport | None, dist_nm: float | None) -> tuple[str, float | None]:
    alt = sv.baro_alt_ft
    agl = (alt - apt.elev_ft) if (alt is not None and apt is not None) else alt
    vr = sv.vrate_fpm or 0.0
    if sv.on_ground or (apt is not None and agl is not None and agl < 150 and (sv.gs_kt or 0) < 80):
        return "ground", agl
    if apt is not None and dist_nm is not None and dist_nm <= AIRPORT_RADIUS_NM and agl is not None and agl < TERMINAL_AGL_FT:
        if vr > VRATE_FPM:
            return "departure", agl
        if vr < -VRATE_FPM:
            return ("approach" if (agl < APPROACH_AGL_FT and dist_nm <= APPROACH_NM) else "arrival"), agl
        return ("pattern" if agl < APPROACH_AGL_FT else "terminal"), agl
    if alt is not None and alt >= CRUISE_FT and abs(vr) < 500:
        return "cruise", agl
    if vr > VRATE_FPM:
        return "climb", agl
    if vr < -VRATE_FPM:
        return "descent", agl
    return "level", agl


def enrich(sv: StateVector) -> Enriched:
    code, name, country, cat = operator_of(sv.callsign, sv.registration)
    tname, tcat = type_info(sv.aircraft_type)
    apt: Airport | None = None
    dist: float | None = None
    if sv.has_position:
        hit = nearest_airport(sv.lat, sv.lon, AIRPORT_RADIUS_NM)  # type: ignore[arg-type]
        if hit:
            apt, dist = hit
    phase, agl = phase_of(sv, apt, dist)
    return Enriched(sv.icao24, code, name, country, cat, sv.aircraft_type, tname, tcat, phase,
                    apt.icao if apt else None, round(dist, 1) if dist is not None else None,
                    round(agl) if agl is not None else None)


def _worst(findings: list[Finding]) -> str | None:
    return min((f.severity for f in findings), key=SEVERITY_ORDER.index).value if findings else None


def _compliance(states: list[StateVector]) -> float | None:
    fixes = [s for s in states if s.airborne and (s.position_source or "").startswith("adsb") and s.nic is not None]
    if not fixes:
        return None
    ok = sum(1 for s in fixes if (s.nic or 0) >= 7 and (s.nac_p or 0) >= 8 and (s.sil or 0) >= 3)
    return round(ok / len(fixes), 4)


def summarize(batch: Batch, enriched: dict[str, Enriched], recent: dict[str, list[Finding]],
              faa_status: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-airport, per-operator, per-type tables plus phase and category totals."""
    by_apt: dict[str, list[tuple[StateVector, Enriched]]] = defaultdict(list)
    by_op: dict[str, list[tuple[StateVector, Enriched]]] = defaultdict(list)
    by_type: dict[str, list[tuple[StateVector, Enriched]]] = defaultdict(list)
    phases: Counter[str] = Counter()
    cats: Counter[str] = Counter()
    for sv in batch.states:
        e = enriched.get(sv.icao24)
        if e is None:
            continue
        phases[e.phase] += 1
        cats[e.type_cat] += 1
        by_op[e.operator_code].append((sv, e))
        if e.type_code:
            by_type[e.type_code.upper()].append((sv, e))
        if e.airport:
            by_apt[e.airport].append((sv, e))
    status_by_apt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in faa_status or []:
        status_by_apt[rec["airport"]].append(rec)

    airports = []
    for icao, rows in by_apt.items():
        a = AIRPORTS[icao]
        ph = Counter(e.phase for _, e in rows)
        fs = [f for sv, _ in rows for f in recent.get(sv.icao24, [])]
        airports.append({
            "icao": icao, "iata": a.iata, "name": a.name, "city": a.city, "country": a.country, "lat": a.lat, "lon": a.lon,
            "nearby": len(rows), "ground": ph["ground"], "departing": ph["departure"], "arriving": ph["arrival"] + ph["approach"],
            "approach": ph["approach"], "terminal": ph["terminal"] + ph["pattern"],
            "overhead": sum(1 for sv, e in rows if e.phase in ("cruise", "level", "climb", "descent")),
            "holds": sum(1 for f in fs if f.rule_id == "OPS-002"),
            "emergencies": sum(1 for sv, _ in rows if sv.squawk in ("7500", "7600", "7700")),
            "findings": len(fs), "worst": _worst(fs),
            "faa": [{k: v for k, v in r.items() if k != "airport"} for r in status_by_apt.get(a.iata, [])],
        })
    airports.sort(key=lambda r: -r["nearby"])

    operators = []
    for code, rows in by_op.items():
        e0 = rows[0][1]
        svs = [sv for sv, _ in rows]
        fs = [f for sv in svs for f in recent.get(sv.icao24, [])]
        alts = [sv.baro_alt_ft for sv in svs if sv.baro_alt_ft is not None and sv.airborne]
        operators.append({
            "code": code, "name": e0.operator, "country": e0.operator_country, "category": e0.operator_cat,
            "aircraft": len(rows), "airborne": sum(1 for sv in svs if sv.airborne), "ground": sum(1 for sv in svs if sv.on_ground),
            "mean_alt": round(sum(alts) / len(alts)) if alts else None,
            "types": [t for t, _ in Counter(e.type_code or "?" for _, e in rows).most_common(3)],
            "phases": dict(Counter(e.phase for _, e in rows)),
            "findings": len(fs), "worst": _worst(fs), "compliance": _compliance(svs),
        })
    operators.sort(key=lambda r: -r["aircraft"])

    types = []
    for code, rows in by_type.items():
        e0 = rows[0][1]
        svs = [sv for sv, _ in rows]
        fs = [f for sv in svs for f in recent.get(sv.icao24, [])]
        alts = [sv.baro_alt_ft for sv in svs if sv.baro_alt_ft is not None and sv.airborne]
        gss = [sv.gs_kt for sv in svs if sv.gs_kt is not None and sv.airborne]
        types.append({
            "code": code, "name": e0.type_name, "category": e0.type_cat, "aircraft": len(rows),
            "airborne": sum(1 for sv in svs if sv.airborne), "mean_alt": round(sum(alts) / len(alts)) if alts else None,
            "mean_gs": round(sum(gss) / len(gss)) if gss else None, "findings": len(fs), "worst": _worst(fs),
        })
    types.sort(key=lambda r: -r["aircraft"])

    return {"airports": airports, "operators": operators, "types": types, "phases": dict(phases), "categories": dict(cats),
            "faa_status": faa_status or [], "airports_known": len(AIRPORTS)}
