"""Well-clear volume and alerting levels, from the DAIDALUS / DO-365 definitions.

Horizontal condition (modified tau): with relative horizontal position ``s`` (ft), relative
velocity ``v`` (ft/s), range ``r = |s|`` and ``s·v < 0`` when converging,

    tau_mod = (DTHR^2 - r^2) / -(s·v)

and the pair is horizontally not well clear when ``r <= DTHR`` or when ``0 <= tau_mod <= TTHR``
and the horizontal miss distance ``HMD`` (closest approach of the linear projection) is at most
``DTHR``. Vertical condition: ``|dz| <= ZTHR`` or, when converging vertically, time to
co-altitude ``0 <= tcoa <= TCOA``. A well-clear violation needs both.

Alert levels project the pair forward: a level is active when the projection violates that
level's thresholds within its alerting time. Defaults are the DO-365 Phase 1 values used by
DAIDALUS: DTHR 4000 ft, ZTHR 450 ft (700 ft preventive), TTHR 35 s, alerting times 55 s
(preventive, corrective) and 25 s (warning).

Reference: NASA DAIDALUS (nasa/daidalus) and WellClear (nasa/WellClear); RTCA DO-365.
This module re-implements the published definitions for offline metrics only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

FT_PER_NM = 6076.1155
FT_PER_S_PER_KT = FT_PER_NM / 3600.0


@dataclass(frozen=True)
class WellClearParams:
    name: str
    dthr_ft: float = 4000.0
    zthr_ft: float = 450.0
    tthr_s: float = 35.0
    tcoa_s: float = 0.0
    alerting_time_s: float = 0.0  # 0 = the violation itself


WCV = WellClearParams("well-clear violation", 4000.0, 450.0, 35.0, 0.0, 0.0)
ALERT_LEVELS: tuple[WellClearParams, ...] = (
    WellClearParams("preventive", 4000.0, 700.0, 35.0, 0.0, 55.0),
    WellClearParams("corrective", 4000.0, 450.0, 35.0, 0.0, 55.0),
    WellClearParams("warning", 4000.0, 450.0, 35.0, 0.0, 25.0),
)


def hmd_ft(s: tuple[float, float], v: tuple[float, float]) -> float:
    """Horizontal miss distance of the linear projection (closest approach at t >= 0)."""
    vv = v[0] * v[0] + v[1] * v[1]
    if vv < 1e-9:
        return math.hypot(*s)
    t = max(0.0, -(s[0] * v[0] + s[1] * v[1]) / vv)
    return math.hypot(s[0] + v[0] * t, s[1] + v[1] * t)


def tau_mod_s(s: tuple[float, float], v: tuple[float, float], dthr_ft: float) -> float:
    """Modified tau; +inf when diverging, 0 when already inside DTHR."""
    r2 = s[0] * s[0] + s[1] * s[1]
    if r2 <= dthr_ft * dthr_ft:
        return 0.0
    sv = s[0] * v[0] + s[1] * v[1]
    if sv >= 0:
        return math.inf
    return (dthr_ft * dthr_ft - r2) / sv  # both negative -> positive seconds


def horizontal_violation(s: tuple[float, float], v: tuple[float, float], p: WellClearParams) -> bool:
    r = math.hypot(*s)
    if r <= p.dthr_ft:
        return True
    tm = tau_mod_s(s, v, p.dthr_ft)
    return 0.0 <= tm <= p.tthr_s and hmd_ft(s, v) <= p.dthr_ft


def vertical_violation(dz_ft: float, vz_ftps: float, p: WellClearParams) -> bool:
    if abs(dz_ft) <= p.zthr_ft:
        return True
    if dz_ft * vz_ftps < 0:  # converging vertically
        tcoa = -dz_ft / vz_ftps
        return 0.0 <= tcoa <= p.tcoa_s
    return False


def violates(s: tuple[float, float], v: tuple[float, float], dz_ft: float, vz_ftps: float, p: WellClearParams = WCV) -> bool:
    return horizontal_violation(s, v, p) and vertical_violation(dz_ft, vz_ftps, p)


def time_to_violation(s: tuple[float, float], v: tuple[float, float], dz_ft: float, vz_ftps: float, p: WellClearParams,
                      horizon_s: float, step_s: float = 1.0) -> float | None:
    """First time in [0, horizon] at which the linear projection violates ``p``; None if never."""
    t = 0.0
    while t <= horizon_s + 1e-9:
        st = (s[0] + v[0] * t, s[1] + v[1] * t)
        if violates(st, v, dz_ft + vz_ftps * t, vz_ftps, p):
            return t
        t += step_s
    return None


def alert_level(s: tuple[float, float], v: tuple[float, float], dz_ft: float, vz_ftps: float,
                levels: tuple[WellClearParams, ...] = ALERT_LEVELS) -> tuple[int, str | None, float | None]:
    """Highest active alert level (1..n), its name, and the projected time to that level's violation."""
    best = (0, None, None)
    for i, p in enumerate(levels, 1):
        t = time_to_violation(s, v, dz_ft, vz_ftps, p, p.alerting_time_s)
        if t is not None:
            best = (i, p.name, t)
    return best


def evaluate(s: tuple[float, float], v: tuple[float, float], dz_ft: float, vz_ftps: float) -> dict[str, Any]:
    """One sample of a pair: geometry, well-clear status and alert level."""
    r = math.hypot(*s)
    sv = s[0] * v[0] + s[1] * v[1]
    lvl, name, t = alert_level(s, v, dz_ft, vz_ftps)
    return {"range_ft": round(r, 1), "closure_ftps": round(-sv / r, 2) if r > 1e-9 else 0.0, "hmd_ft": round(hmd_ft(s, v), 1),
            "tau_mod_s": None if math.isinf(tau_mod_s(s, v, WCV.dthr_ft)) else round(tau_mod_s(s, v, WCV.dthr_ft), 1),
            "dz_ft": round(dz_ft, 1), "well_clear": not violates(s, v, dz_ft, vz_ftps), "alert_level": lvl, "alert": name,
            "time_to_violation_s": None if t is None else round(t, 1)}


def relative_geometry(lat1: float, lon1: float, gs1_kt: float, trk1_deg: float, lat2: float, lon2: float, gs2_kt: float, trk2_deg: float
                      ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Relative position (ft, east/north) and relative velocity (ft/s) of aircraft 2 as seen from aircraft 1."""
    coslat = math.cos(math.radians((lat1 + lat2) / 2.0))
    sx = (lon2 - lon1) * 60.0 * coslat * FT_PER_NM
    sy = (lat2 - lat1) * 60.0 * FT_PER_NM
    v1 = (gs1_kt * math.sin(math.radians(trk1_deg)) * FT_PER_S_PER_KT, gs1_kt * math.cos(math.radians(trk1_deg)) * FT_PER_S_PER_KT)
    v2 = (gs2_kt * math.sin(math.radians(trk2_deg)) * FT_PER_S_PER_KT, gs2_kt * math.cos(math.radians(trk2_deg)) * FT_PER_S_PER_KT)
    return (sx, sy), (v2[0] - v1[0], v2[1] - v1[1])


__all__ = ["ALERT_LEVELS", "FT_PER_NM", "FT_PER_S_PER_KT", "WCV", "WellClearParams", "alert_level", "evaluate", "hmd_ft", "horizontal_violation",
           "relative_geometry", "tau_mod_s", "time_to_violation", "vertical_violation", "violates"]
