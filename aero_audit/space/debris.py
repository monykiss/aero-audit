"""Debris-mitigation checklist against NASA-STD-8719.14 and ISO 24113 (with the 2022 FCC 5-year
LEO rule noted), from a mission description in JSON.

Inputs describe the mission as its owner knows it: orbit (perigee/apogee km, inclination), mass,
cross-section, drag coefficient, propulsion and manoeuvre capability, passivation plan, disposal
plan, planned releases, trackability, casualty risk figure, constellation size and disposal
reliability. Each check is a DEB rule with the requirement it maps to. The orbital-lifetime
estimate is a deliberately simple exponential-atmosphere decay integration (King-Hele style) with
a stated factor-of-two uncertainty; it decides whether a LEO disposal plan is even plausible, not
whether it is certified.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity

MU_KM3_S2 = 398600.4418
RE_KM = 6378.137
NASA_LIFETIME_YEARS = 25.0
FCC_LIFETIME_YEARS = 5.0
GEO_ALT_KM = 35786.0
CASUALTY_RISK_LIMIT = 1e-4
# (altitude km, density kg/m^3, scale height km): Vallado / US Standard Atmosphere 1976 style table, mean solar activity
_DENSITY = (
    (150, 2.070e-9, 22.523), (180, 5.464e-10, 29.740), (200, 2.789e-10, 37.105), (250, 7.248e-11, 45.546), (300, 2.418e-11, 53.628),
    (350, 9.518e-12, 53.298), (400, 3.725e-12, 58.515), (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822), (600, 1.454e-13, 71.835),
    (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64), (900, 5.245e-15, 181.05), (1000, 3.019e-15, 268.00),
)


def density_kg_m3(alt_km: float) -> float:
    if alt_km < 150:
        return _DENSITY[0][1]
    base = _DENSITY[-1]
    for row in _DENSITY:
        if alt_km >= row[0]:
            base = row
    h0, rho0, H = base
    return rho0 * math.exp(-(alt_km - h0) / H)


def orbital_lifetime_years(perigee_km: float, apogee_km: float, mass_kg: float, area_m2: float, cd: float = 2.2,
                           max_years: float = 200.0) -> float:
    """Circular-equivalent decay integration until 150 km; returns min(lifetime, max_years)."""
    if perigee_km > 2000:
        return max_years  # not LEO: drag is not the disposal mechanism
    a_km = RE_KM + (perigee_km + apogee_km) / 2.0
    bstar = cd * area_m2 / max(mass_kg, 1e-6)  # m^2/kg
    t = 0.0
    dt = 86400.0 * 5
    while a_km - RE_KM > 150.0 and t < max_years * 365.25 * 86400:
        alt = a_km - RE_KM
        rho = density_kg_m3(alt)
        v = math.sqrt(MU_KM3_S2 / a_km) * 1000.0  # m/s
        da_dt = -bstar * rho * v * a_km * 1000.0 / 1000.0  # km/s: da/dt = -(Cd A/m) rho v a
        a_km += da_dt * dt
        t += dt
        if alt > 1500 and da_dt * dt > -1e-6:
            return max_years
    return min(t / (365.25 * 86400), max_years)


@dataclass
class Mission:
    name: str
    perigee_km: float
    apogee_km: float
    inclination_deg: float
    mass_kg: float
    area_m2: float
    cd: float = 2.2
    mission_years: float = 5.0
    propulsion: bool = False
    maneuverable: bool = False
    passivation_plan: bool = False
    disposal_plan: str = "none"  # none | natural-decay | controlled-reentry | disposal-orbit | graveyard
    disposal_perigee_raise_km: float = 0.0
    planned_releases: int = 0
    trackable: bool = True
    casualty_risk: float | None = None
    demisable: bool | None = None
    constellation_size: int = 1
    disposal_reliability: float | None = None
    us_licensed: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> Mission:
        d = json.loads(Path(path).read_text())
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k != "extra"}
        extra = {k: v for k, v in d.items() if k not in cls.__dataclass_fields__}
        return cls(**known, extra=extra)

    @property
    def regime(self) -> str:
        if self.perigee_km <= 2000:
            return "LEO"
        if abs((self.perigee_km + self.apogee_km) / 2 - GEO_ALT_KM) < 300:
            return "GEO"
        return "MEO/HEO"


def checklist(m: Mission, now: datetime | None = None) -> tuple[dict[str, Any], list[Finding]]:
    ts = (now or datetime.now(UTC)).timestamp()
    rows: list[dict[str, Any]] = []
    findings: list[Finding] = []

    def add(rule: str, requirement: str, ok: bool | None, detail: str, sev: Severity = Severity.MEDIUM, refs: tuple[str, ...] = ("NASA-STD-8719.14", "ISO 24113"),
            rec: str = "") -> None:
        rows.append({"rule": rule, "requirement": requirement, "status": "pass" if ok else ("unknown" if ok is None else "fail"), "detail": detail})
        if ok is False:
            findings.append(Finding(rule_id=rule, title=f"{requirement}: {detail}", severity=sev, category=Category.SAFETY, callsign=m.name, ts=ts,
                                    evidence={"stream": m.name, "regime": m.regime, "detail": detail}, controls=list(refs), recommendation=rec))
        elif ok is None:
            findings.append(Finding(rule_id=rule, title=f"{requirement}: not assessable ({detail})", severity=Severity.LOW, category=Category.DATA_QUALITY,
                                    callsign=m.name, ts=ts, evidence={"stream": m.name, "detail": detail}, controls=list(refs), recommendation="Supply the missing figure in the mission file."))

    lifetime = None
    if m.regime == "LEO":
        lifetime = orbital_lifetime_years(m.perigee_km, m.apogee_km, m.mass_kg, m.area_m2, m.cd)
        limit = FCC_LIFETIME_YEARS if m.us_licensed else NASA_LIFETIME_YEARS
        if m.disposal_plan in ("controlled-reentry",) and m.propulsion:
            add("DEB-001", "Post-mission disposal within the rule", True, f"controlled reentry planned with propulsion; natural lifetime estimate {lifetime:.1f} y")
        else:
            add("DEB-001", "Post-mission disposal within the rule", lifetime <= limit,
                f"estimated post-mission lifetime {lifetime:.1f} y (x2 uncertainty) vs {limit:g} y limit ({'FCC 2022' if m.us_licensed else 'NASA 25-year'})",
                Severity.HIGH, rec="Lower the disposal perigee, add drag augmentation, or plan a controlled reentry with propulsion.")
    elif m.regime == "GEO":
        raise_min = 235.0 + 1000.0 * 1.2 * (m.area_m2 / max(m.mass_kg, 1e-6))  # IADC: 235 km + 1000 Cr A/m
        add("DEB-005", "GEO graveyard orbit raise", m.disposal_plan == "graveyard" and m.disposal_perigee_raise_km >= raise_min,
            f"planned raise {m.disposal_perigee_raise_km:g} km vs minimum {raise_min:.0f} km", Severity.HIGH, ("IADC guidelines", "ISO 24113"),
            "Reserve propellant for the graveyard manoeuvre and state the raise in the disposal plan.")
    else:
        add("DEB-001", "Post-mission disposal within the rule", m.disposal_plan in ("disposal-orbit", "controlled-reentry", "graveyard"),
            f"{m.regime} with disposal plan '{m.disposal_plan}'", Severity.MEDIUM, rec="Define a disposal orbit that stays clear of protected regions.")
    add("DEB-002", "Passivation of stored energy at end of mission", m.passivation_plan, "passivation plan " + ("present" if m.passivation_plan else "absent"),
        Severity.HIGH, rec="Plan battery and propellant passivation; most fragmentation events are un-passivated stages and spacecraft.")
    populated = m.regime == "LEO" and 400 <= (m.perigee_km + m.apogee_km) / 2 <= 1200
    add("DEB-003", "Collision-avoidance capability in populated regions", (not populated) or m.maneuverable,
        f"{'populated LEO shell' if populated else m.regime} and {'manoeuvrable' if m.maneuverable else 'not manoeuvrable'}", Severity.HIGH,
        rec="Subscribe to conjunction data messages and keep manoeuvre capability, or accept the shell's collision risk explicitly.")
    if m.disposal_plan in ("natural-decay", "controlled-reentry") or m.regime == "LEO":
        if m.casualty_risk is not None:
            add("DEB-004", "Reentry casualty risk below 1e-4", m.casualty_risk < CASUALTY_RISK_LIMIT, f"stated casualty risk {m.casualty_risk:.1e}", Severity.HIGH,
                rec="Design for demise or plan a controlled reentry into an ocean area.")
        elif m.demisable is not None:
            add("DEB-004", "Reentry casualty risk below 1e-4", bool(m.demisable), "demisability " + ("claimed" if m.demisable else "not claimed"), Severity.HIGH)
        else:
            add("DEB-004", "Reentry casualty risk below 1e-4", None, "no casualty risk or demisability stated")
    add("DEB-006", "Trackable by the surveillance network", m.trackable, "trackable " + ("yes" if m.trackable else "no (too small or no aids)"),
        rec="Add retroreflectors or an identification beacon; register with 18 SDS / EU SST.")
    add("DEB-007", "No planned release of long-lived debris", m.planned_releases == 0, f"{m.planned_releases} planned release(s)",
        rec="Retain covers, tethers and separation hardware.")
    if m.constellation_size >= 100:
        add("DEB-008", "Large-constellation disposal reliability", (m.disposal_reliability or 0) >= 0.99,
            f"{m.constellation_size} satellites, disposal reliability {m.disposal_reliability}", Severity.HIGH, ("NASA-STD-8719.14", "FCC 2022 order"),
            "Demonstrate >= 99 % disposal reliability or plan for failed-satellite lifetimes.")
    passed = sum(1 for r in rows if r["status"] == "pass")
    summary = {"mission": m.name, "regime": m.regime, "checks": len(rows), "passed": passed, "failed": sum(1 for r in rows if r["status"] == "fail"),
               "unknown": sum(1 for r in rows if r["status"] == "unknown"), "estimated_lifetime_years": None if lifetime is None else round(lifetime, 1),
               "rows": rows, "references": ["NASA-STD-8719.14C", "ISO 24113:2023", "IADC Space Debris Mitigation Guidelines", "FCC 22-74 (5-year rule)"]}
    return summary, findings


__all__ = ["CASUALTY_RISK_LIMIT", "FCC_LIFETIME_YEARS", "NASA_LIFETIME_YEARS", "Mission", "checklist", "density_kg_m3", "orbital_lifetime_years"]
