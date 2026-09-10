"""Cross-feed corroboration: the strongest cheap defence against injected or modified ADS-B.

A forged transmission reaches the receivers near the attacker. Two independent receiver
networks (e.g. adsb.lol and OpenSky) rarely share the same set of antennas, so a genuine
aircraft is seen at (nearly) the same place by both while a localised forgery is not.
Fixes are dead-reckoned to a common time before comparing, because the feeds are not
synchronised.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..audit.findings import Category, Finding, Severity
from ..features import haversine_nm
from ..models import Batch, StateVector

MAX_DT_S = 90.0  # beyond this, dead reckoning is too uncertain to call a disagreement
BASE_TOLERANCE_NM = 1.5  # receiver timing / rounding slack
DR_UNCERTAINTY_KT = 60.0  # extra tolerance per hour of dead reckoning (turns, accel)


def dead_reckon(sv: StateVector, to_ts: float) -> tuple[float, float]:
    """Project a fix forward/backward along its track at its reported ground speed."""
    dt_h = (to_ts - sv.ts) / 3600.0
    if sv.gs_kt is None or sv.track_deg is None or sv.lat is None or sv.lon is None:
        return sv.lat or 0.0, sv.lon or 0.0
    d_nm = sv.gs_kt * dt_h
    t = math.radians(sv.track_deg)
    lat = sv.lat + d_nm * math.cos(t) / 60.0
    lon = sv.lon + d_nm * math.sin(t) / (60.0 * max(math.cos(math.radians(sv.lat)), 0.1))
    return lat, lon


@dataclass
class CorroborationResult:
    matched: int = 0
    only_primary: int = 0
    only_secondary: int = 0
    disagreements: int = 0
    separations_nm: list[float] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def summary(self) -> dict[str, float | int]:
        seps = sorted(self.separations_nm)
        p95 = seps[int(0.95 * (len(seps) - 1))] if seps else 0.0
        return {
            "matched": self.matched,
            "only_primary": self.only_primary,
            "only_secondary": self.only_secondary,
            "disagreements": self.disagreements,
            "median_sep_nm": round(seps[len(seps) // 2], 3) if seps else 0.0,
            "p95_sep_nm": round(p95, 3),
        }


def corroborate(primary: Batch, secondary: Batch, tolerance_nm: float = BASE_TOLERANCE_NM) -> CorroborationResult:
    res = CorroborationResult()
    a = {sv.icao24: sv for sv in primary.states if sv.has_position and sv.airborne}
    b = {sv.icao24: sv for sv in secondary.states if sv.has_position and sv.airborne}
    res.only_primary = len(set(a) - set(b))
    res.only_secondary = len(set(b) - set(a))
    for icao, sa in a.items():
        sb = b.get(icao)
        if sb is None:
            continue
        dt = abs(sa.ts - sb.ts)
        if dt > MAX_DT_S:
            continue
        # move the older fix to the newer fix's time
        older, newer = (sa, sb) if sa.ts < sb.ts else (sb, sa)
        lat, lon = dead_reckon(older, newer.ts)
        sep = haversine_nm(lat, lon, newer.lat, newer.lon)  # type: ignore[arg-type]
        res.matched += 1
        res.separations_nm.append(sep)
        allowed = tolerance_nm + DR_UNCERTAINTY_KT * dt / 3600.0
        if sep > allowed:
            res.disagreements += 1
            res.findings.append(
                Finding(
                    rule_id="SEC-015",
                    title="Cross-feed position disagreement (possible spoof or feed fault)",
                    severity=Severity.HIGH if sep > 4 * allowed else Severity.MEDIUM,
                    category=Category.SECURITY,
                    icao24=icao,
                    callsign=(sa.callsign or sb.callsign or "").strip() or None,
                    ts=newer.ts,
                    evidence={
                        "separation_nm": round(sep, 2), "allowed_nm": round(allowed, 2), "dt_s": round(dt, 1),
                        "primary": {"feed": str(sa.source), "lat": sa.lat, "lon": sa.lon, "src": sa.position_source},
                        "secondary": {"feed": str(sb.source), "lat": sb.lat, "lon": sb.lon, "src": sb.position_source},
                        "baro_alt_ft": sa.baro_alt_ft, "position_source": sa.position_source, "feed": str(sa.source),
                    },
                    controls=["ICAO Doc 9924 (surveillance integrity)", "ICAO Annex 17"],
                    recommendation="Determine which feed is the outlier; if one aircraft only, treat as spoof "
                    "candidate and lower trust; if many, suspect a feed-wide fault (T10).",
                )
            )
    return res
