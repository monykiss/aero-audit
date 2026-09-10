"""Deterministic audit rules. Each rule is small, explainable, and cites the control it maps to.

Rule id prefixes:  SEC = security / integrity, OPS = operations & process, SAF = safety.
Thresholds are module constants so an auditor can tune them per airspace and defend the choice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..features import TrackFeatures, haversine_nm
from ..models import Batch, StateVector
from .findings import Category, Finding, Severity

# ---- thresholds -------------------------------------------------------------------------
MAX_PLAUSIBLE_GS_KT = 750.0  # fastest civil traffic with tailwind ~ 650 kt; beyond = implausible
GS_MISMATCH_KT = 150.0  # |implied - reported| ground speed for direct ADS-B positions
GS_MISMATCH_FACTOR_BY_SOURCE = {"mlat": 2.5, "tisb": 2.0, "asterix": 1.5}  # multilateration jitter over 48 s ~ 3 nm
MIN_DT_FOR_KINEMATICS_S = 4.0  # below this, timestamp jitter dominates
# 14 CFR 91.227(c): NACp >= 8 (< 0.05 nm), NIC >= 7 (< 0.2 nm), SIL = 3 for rule airspace.
MIN_NIC, MIN_NACP, MIN_SIL = 7, 8, 3
MAX_VRATE_FPM = 6000.0
MAX_IMPLIED_VRATE_FPM = 8000.0  # altitude change between fixes that no transport aircraft achieves
VRATE_MISMATCH_FPM = 4000.0  # |implied - reported| vertical rate
MIN_DT_FOR_VRATE_S = 10.0
HOLD_MIN_FIXES, HOLD_HEADING_DEG, HOLD_MAX_NET_NM = 8, 300.0, 8.0
HOLD_MIN_ALT_FT, HOLD_MIN_GS_KT = 3000.0, 150.0  # below these it is pattern work, not an airline hold
ALT_DEV_FT, ALT_DEV_MIN_ALT_FT, LEVEL_VRATE_FPM = 300.0, 3000.0, 300.0
ALT_DEV_PRESELECT_FT = 1000.0  # beyond this the selected value is almost always the *next* cleared level
ALT_DEV_MIN_FIXES = 3  # deviation must persist across this many consecutive fixes...
ALT_DEV_MIN_PERSIST_S = 60.0  # ...and at least this long (fast polling would otherwise satisfy 3 fixes in 20 s)
STALE_CONTACT_S = 90.0
CLASS_A_FLOOR_FT = 18000.0
DUPLICATE_ICAO_MIN_SEP_NM = 5.0
# Separation monitor (indicative only: fixes are asynchronous and dead-reckoned to batch time)
PROX_LATERAL_NM, PROX_VERTICAL_FT, PROX_MIN_ALT_FT = 3.0, 900.0, 3000.0  # 900 ft leaves margin under 1,000 ft spacing
PROX_CLOSE_NM, PROX_CLOSE_FT = 1.5, 600.0  # medium severity inside this
PROX_MAX_FIX_AGE_S = 60.0  # older fixes cannot be dead-reckoned reliably

EMERGENCY_SQUAWKS = {
    "7500": ("SEC-003", "Squawk 7500: unlawful interference (hijack) code", Severity.CRITICAL),
    "7600": ("SEC-002", "Squawk 7600: radio communication failure", Severity.HIGH),
    "7700": ("SEC-001", "Squawk 7700: general emergency", Severity.HIGH),
}


@dataclass(frozen=True)
class RuleContext:
    batch_ts: float
    provider: str
    region: str
    track: Callable[[str], list[StateVector]] = lambda icao24: []  # recent fixes for an aircraft


Rule = Callable[[StateVector, TrackFeatures | None, RuleContext], list[Finding]]
BatchRule = Callable[[Batch, RuleContext], list[Finding]]
RULES: list[tuple[str, Rule]] = []
BATCH_RULES: list[tuple[str, BatchRule]] = []


def rule(rule_id: str) -> Callable[[Rule], Rule]:
    def deco(fn: Rule) -> Rule:
        RULES.append((rule_id, fn))
        return fn

    return deco


def batch_rule(rule_id: str) -> Callable[[BatchRule], BatchRule]:
    def deco(fn: BatchRule) -> BatchRule:
        BATCH_RULES.append((rule_id, fn))
        return fn

    return deco


def _mk(
    rule_id: str,
    title: str,
    severity: Severity,
    category: Category,
    sv: StateVector,
    evidence: dict[str, Any],
    controls: list[str],
    recommendation: str,
) -> Finding:
    evidence = {
        "lat": sv.lat,
        "lon": sv.lon,
        "baro_alt_ft": sv.baro_alt_ft,
        "gs_kt": sv.gs_kt,
        "position_source": sv.position_source,
        "feed": str(sv.source),
        **evidence,
    }
    return Finding(
        rule_id=rule_id,
        title=title,
        severity=severity,
        category=category,
        icao24=sv.icao24,
        callsign=(sv.callsign or "").strip() or None,
        ts=sv.ts,
        evidence=evidence,
        controls=controls,
        recommendation=recommendation,
    )


# ---- security / integrity -----------------------------------------------------------------
@rule("SEC-00x")
def emergency_squawk(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    if sv.squawk in EMERGENCY_SQUAWKS:
        rid, title, sev = EMERGENCY_SQUAWKS[sv.squawk]
        consecutive = 1
        for prev in reversed(ctx.track(sv.icao24)[:-1]):  # earlier distinct fixes, newest first
            if prev.squawk != sv.squawk:
                break
            consecutive += 1
        if consecutive < 2:  # a single fix is usually a mis-dial; confirmed on the next fix (escalation bypasses cooldown)
            sev = {Severity.CRITICAL: Severity.HIGH, Severity.HIGH: Severity.MEDIUM}.get(sev, sev)
            title += " (single fix, unconfirmed)"
        out.append(
            _mk(
                rid, title, sev, Category.SECURITY, sv,
                {"squawk": sv.squawk, "emergency_field": sv.emergency, "consecutive_fixes": consecutive},
                ["ICAO Doc 4444 PANS-ATM 8.5 / 15.x (emergency codes)", "FAA AIM 4-1-20, 6-2-x"],
                "Correlate with ATC/AOC logs; confirm whether code was intentional, "
                "mis-set, or spoofed (a spoofed 7500 is a known ADS-B attack pattern).",
            )
        )
    elif sv.emergency and sv.emergency not in ("none", ""):
        out.append(
            _mk(
                "SEC-004", f"Emergency status field set: {sv.emergency}", Severity.HIGH,
                Category.SECURITY, sv, {"emergency_field": sv.emergency, "squawk": sv.squawk},
                ["RTCA DO-260B 2.2.3.2.7.8.1.1 (emergency/priority status)"],
                "Cross-check squawk vs emergency subfield; mismatch suggests a mis-set or forged message.",
            )
        )
    return out


@rule("SEC-010")
def kinematic_impossibility(
    sv: StateVector, f: TrackFeatures | None, ctx: RuleContext
) -> list[Finding]:
    if f is None or f.dt_s < MIN_DT_FOR_KINEMATICS_S or sv.on_ground:
        return []
    if f.implied_gs_kt <= MAX_PLAUSIBLE_GS_KT:
        return []
    direct_adsb = (sv.position_source or "adsb").startswith("adsb")
    if direct_adsb:
        title = "Kinematically impossible position jump (possible spoofing/injection)"
        sev = Severity.CRITICAL if f.implied_gs_kt > 2 * MAX_PLAUSIBLE_GS_KT else Severity.HIGH
        cat = Category.SECURITY
    else:  # MLAT / TIS-B solutions jump when receiver geometry is poor; that is not a forged message
        title = f"Impossible position jump on a {sv.position_source} solution (multilateration / relay error)"
        sev = Severity.MEDIUM
        cat = Category.DATA_QUALITY
    return [
        _mk(
            "SEC-010", title, sev, cat, sv,
            {
                "implied_gs_kt": round(f.implied_gs_kt, 1),
                "reported_gs_kt": f.reported_gs_kt,
                "jump_nm": round(f.dist_nm, 2),
                "dt_s": round(f.dt_s, 1),
            },
            ["FAA AC 20-165B (ADS-B Out install/performance)", "ICAO Annex 17 (aviation security)",
             "RTCA DO-260B (ADS-B MOPS)"],
            "Treat as untrusted: check whether both fixes came from the same receiver, whether "
            "an ICAO address collision exists, and whether MLAT corroborates the position.",
        )
    ]


@rule("SEC-011")
def speed_mismatch(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    if (
        f is None
        or f.gs_mismatch_kt is None
        or f.dt_s < MIN_DT_FOR_KINEMATICS_S
        or sv.on_ground
        or f.implied_gs_kt > MAX_PLAUSIBLE_GS_KT  # SEC-010 already covers it
    ):
        return []
    src = (sv.position_source or "adsb").split("_")[0]
    tolerance = GS_MISMATCH_KT * GS_MISMATCH_FACTOR_BY_SOURCE.get(src, 1.0)
    if abs(f.gs_mismatch_kt) <= tolerance:
        return []
    return [
        _mk(
            "SEC-011", "Reported ground speed inconsistent with position-derived speed",
            Severity.MEDIUM if src == "adsb" else Severity.LOW, Category.SECURITY, sv,
            {
                "implied_gs_kt": round(f.implied_gs_kt, 1),
                "reported_gs_kt": f.reported_gs_kt,
                "mismatch_kt": round(f.gs_mismatch_kt, 1),
                "tolerance_kt": round(tolerance, 0),
                "dt_s": round(f.dt_s, 1),
            },
            ["RTCA DO-260B (velocity vs position message consistency)"],
            "Velocity and position are separate ADS-B messages; inconsistency indicates a "
            "receiver merge issue, stale data, or a crude injection that forged only one.",
        )
    ]


@rule("SEC-018")
def altitude_inconsistency(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    """Altitude jumped between fixes in a way the reported vertical rate cannot explain."""
    if f is None or f.implied_vrate_fpm is None or f.dt_s < MIN_DT_FOR_VRATE_S or sv.on_ground:
        return []
    implied = f.implied_vrate_fpm
    mismatch = implied - sv.vrate_fpm if sv.vrate_fpm is not None else None
    impossible = abs(implied) > MAX_IMPLIED_VRATE_FPM
    inconsistent = mismatch is not None and abs(mismatch) > VRATE_MISMATCH_FPM
    if not (impossible or inconsistent):
        return []
    direct_adsb = (sv.position_source or "adsb").startswith("adsb")
    return [
        _mk(
            "SEC-018",
            "Altitude change inconsistent with reported vertical rate (possible altitude forgery)"
            if direct_adsb else f"Altitude jump on a {sv.position_source} solution (relay / merge error)",
            (Severity.HIGH if impossible else Severity.MEDIUM) if direct_adsb else Severity.LOW,
            Category.SECURITY if direct_adsb else Category.DATA_QUALITY, sv,
            {
                "implied_vrate_fpm": round(implied, 0),
                "reported_vrate_fpm": sv.vrate_fpm,
                "mismatch_fpm": round(mismatch, 0) if mismatch is not None else None,
                "dt_s": round(f.dt_s, 1),
            },
            ["RTCA DO-260B (altitude vs vertical-rate consistency)", "ICAO Annex 17"],
            "Altitude and vertical rate come from different messages; a forged altitude leaves the "
            "vertical rate untouched. Corroborate with the second feed and Mode C if available.",
        )
    ]


@rule("SEC-012")
def low_integrity(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    if sv.nic is None and sv.nac_p is None and sv.sil is None:
        return []
    if sv.on_ground or not (sv.position_source or "").startswith("adsb"):
        return []  # 91.227 governs ADS-B Out; TIS-B/MLAT tracks carry NIC/NACp/SIL = 0 by design
    problems = []
    if sv.nic is not None and sv.nic < MIN_NIC:
        problems.append(f"NIC {sv.nic} < {MIN_NIC}")
    if sv.nac_p is not None and sv.nac_p < MIN_NACP:
        problems.append(f"NACp {sv.nac_p} < {MIN_NACP}")
    if sv.sil is not None and sv.sil < MIN_SIL:
        problems.append(f"SIL {sv.sil} < {MIN_SIL}")
    if not problems:
        return []
    sev = Severity.MEDIUM if (sv.sil == 0 or (sv.nic is not None and sv.nic <= 4)) else Severity.LOW
    return [
        _mk(
            "SEC-012", "ADS-B position integrity/accuracy below rule-airspace minimums",
            sev, Category.DATA_QUALITY, sv,
            {"nic": sv.nic, "nac_p": sv.nac_p, "sil": sv.sil, "problems": problems},
            ["14 CFR 91.227(c) (NACp/NIC/SIL performance)", "RTCA DO-260B Table 2-70 ff."],
            "Position may be off by > 0.2 nm. Flag for avionics maintenance if persistent; "
            "downgrade trust of this aircraft's positions in downstream analytics.",
        )
    ]


@rule("SEC-013")
def identity_gap(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    if sv.on_ground or (sv.baro_alt_ft or 0) < 10000 or (sv.callsign or "").strip():
        return []
    return [
        _mk(
            "SEC-013", "Airborne above 10,000 ft with no callsign/flight ID", Severity.LOW,
            Category.SECURITY, sv, {"registration": sv.registration, "type": sv.aircraft_type},
            ["ICAO Doc 4444 (flight identification)", "FAA AC 90-114 (ADS-B operations)"],
            "Missing Flight ID hampers surveillance correlation; verify FMS/transponder config.",
        )
    ]


@batch_rule("SEC-014")
def duplicate_icao(batch: Batch, ctx: RuleContext) -> list[Finding]:
    seen: dict[str, StateVector] = {}
    out: list[Finding] = []
    for sv in batch.states:
        if not sv.has_position:
            continue
        other = seen.get(sv.icao24)
        if other is None:
            seen[sv.icao24] = sv
            continue
        sep = haversine_nm(other.lat, other.lon, sv.lat, sv.lon)  # type: ignore[arg-type]
        if sep >= DUPLICATE_ICAO_MIN_SEP_NM:
            out.append(
                _mk(
                    "SEC-014", "Same ICAO 24-bit address reported at two distant positions",
                    Severity.HIGH, Category.SECURITY, sv,
                    {"separation_nm": round(sep, 1), "other_lat": other.lat, "other_lon": other.lon},
                    ["ICAO Annex 10 Vol III (24-bit address allocation)"],
                    "Address collision or ghost aircraft; check registry and receiver provenance.",
                )
            )
    return out


@batch_rule("SAF-004")
def proximity(batch: Batch, ctx: RuleContext) -> list[Finding]:
    """Pairs of airborne aircraft above 3,000 ft closer than separation-like thresholds after dead
    reckoning both fixes to the batch time. Indicative: ATC radar and TCAS are authoritative."""
    import math

    pts: list[tuple[StateVector, float, float]] = []
    for sv in batch.states:
        if not (sv.has_position and sv.airborne) or (sv.baro_alt_ft or 0) < PROX_MIN_ALT_FT:
            continue
        age = batch.ts - sv.ts
        if age < 0 or age > PROX_MAX_FIX_AGE_S:
            continue
        lat, lon = sv.lat, sv.lon  # type: ignore[assignment]
        if sv.gs_kt is not None and sv.track_deg is not None and age > 0:
            d_nm = sv.gs_kt * age / 3600.0
            t = math.radians(sv.track_deg)
            lat = lat + d_nm * math.cos(t) / 60.0
            lon = lon + d_nm * math.sin(t) / (60.0 * max(math.cos(math.radians(lat)), 0.1))
        pts.append((sv, lat, lon))
    cell = 0.06  # degrees; > 3 nm at any latitude in longitude terms up to ~60 deg
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (_, lat, lon) in enumerate(pts):
        grid.setdefault((int(lat // cell), int(lon // cell)), []).append(i)
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for (cx, cy), idxs in grid.items():
        cand = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((cx + dx, cy + dy), [])]
        for i in idxs:
            a, alat, alon = pts[i]
            for j in cand:
                if j <= i:
                    continue
                b, blat, blon = pts[j]
                if a.icao24 == b.icao24 or (a.icao24, b.icao24) in seen:
                    continue
                dalt = abs((a.baro_alt_ft or 0) - (b.baro_alt_ft or 0))
                if dalt >= PROX_VERTICAL_FT:
                    continue
                sep = haversine_nm(alat, alon, blat, blon)
                if sep >= PROX_LATERAL_NM:
                    continue
                seen.add((a.icao24, b.icao24))
                close = sep < PROX_CLOSE_NM and dalt < PROX_CLOSE_FT
                out.append(
                    _mk(
                        "SAF-004", "Close proximity between airborne aircraft (indicative separation check)",
                        Severity.MEDIUM if close else Severity.INFO, Category.SAFETY, a,
                        {
                            "other_icao24": b.icao24, "other_callsign": (b.callsign or "").strip() or None,
                            "lateral_nm": round(sep, 2), "vertical_ft": round(dalt, 0),
                            "other_baro_alt_ft": b.baro_alt_ft, "fix_age_s": round(batch.ts - a.ts, 1),
                        },
                        ["ICAO Doc 4444 (separation minima: 3 nm terminal / 5 nm en route, 1,000 ft vertical)",
                         "ICAO Annex 11 (ATS)"],
                        "Indicative only: fixes are asynchronous and dead-reckoned. Formation flights, "
                        "parallel approaches above 3,000 ft, and stale feeds produce pairs; confirm with ATC/TCAS.",
                    )
                )
    return out


# ---- operations / process ------------------------------------------------------------------
@rule("OPS-001")
def stale_contact(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    age = ctx.batch_ts - sv.ts
    if sv.on_ground or age <= STALE_CONTACT_S:
        return []
    return [
        _mk(
            "OPS-001", "Surveillance coverage gap (stale position)", Severity.INFO,
            Category.OPERATIONS, sv, {"age_s": round(age, 1)},
            ["ICAO Doc 9924 (surveillance manual)"],
            "Persistent gaps in the same sector indicate receiver coverage holes worth mapping.",
        )
    ]


def _is_orbiting(sv: StateVector, f: TrackFeatures | None) -> bool:
    return (
        f is not None
        and not sv.on_ground
        and f.n_fixes >= HOLD_MIN_FIXES
        and abs(f.window_heading_sum_deg) >= HOLD_HEADING_DEG
        and f.window_net_nm <= HOLD_MAX_NET_NM
    )


def _orbit_evidence(f: TrackFeatures) -> dict[str, Any]:
    return {
        "heading_change_deg": round(f.window_heading_sum_deg, 0),
        "net_displacement_nm": round(f.window_net_nm, 2),
        "path_nm": round(f.window_path_nm, 2),
        "span_s": round(f.window_span_s, 0),
    }


@rule("OPS-002")
def holding_pattern(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    """Airline-style holding: orbiting at or above hold altitudes and speeds. Feeds the impact model."""
    if not _is_orbiting(sv, f) or (sv.baro_alt_ft or 0) < HOLD_MIN_ALT_FT or (sv.gs_kt or 0) < HOLD_MIN_GS_KT:
        return []
    return [
        _mk(
            "OPS-002", "Holding / orbiting detected (airborne delay, fuel burn)", Severity.LOW,
            Category.OPERATIONS, sv, _orbit_evidence(f),  # type: ignore[arg-type]
            ["ICAO Doc 4444 (holding procedures)", "ICAO Doc 9750 GANP / ASBU (ATFM efficiency)"],
            "Aggregate by hour and runway config; sustained holding without weather cause points "
            "at arrival-rate/flow-management inefficiency.",
        )
    ]


@rule("OPS-003")
def low_altitude_orbiting(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    """Pattern work, survey, helicopter or training orbits: normal activity, tracked for airspace density."""
    if not _is_orbiting(sv, f) or ((sv.baro_alt_ft or 0) >= HOLD_MIN_ALT_FT and (sv.gs_kt or 0) >= HOLD_MIN_GS_KT):
        return []
    return [
        _mk(
            "OPS-003", "Low-altitude / low-speed orbiting (pattern work, survey, helicopter)", Severity.INFO,
            Category.OPERATIONS, sv, _orbit_evidence(f),  # type: ignore[arg-type]
            ["FAA AC 90-66C (traffic patterns)"],
            "Normal activity; useful as an airspace-density and noise-exposure signal, not a delay signal.",
        )
    ]


@rule("SAF-003")
def excessive_vrate(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    vr = sv.vrate_fpm
    if vr is None or abs(vr) <= MAX_VRATE_FPM or sv.on_ground:
        return []
    return [
        _mk(
            "SAF-003", "Excessive vertical rate", Severity.MEDIUM, Category.SAFETY, sv,
            {"vrate_fpm": vr, "implied_vrate_fpm": f.implied_vrate_fpm if f else None},
            ["ICAO Annex 6 (operations)", "Operator SOPs / FOQA thresholds"],
            "Compare with FOQA/FDM event thresholds; if implied rate disagrees, suspect bad data.",
        )
    ]


@rule("OPS-004")
def altitude_deviation(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    if (
        sv.on_ground
        or sv.selected_alt_ft is None
        or sv.baro_alt_ft is None
        or sv.baro_alt_ft < ALT_DEV_MIN_ALT_FT
        or abs(sv.vrate_fpm or 0) > LEVEL_VRATE_FPM  # climbing/descending toward target is normal
    ):
        return []
    dev = sv.baro_alt_ft - sv.selected_alt_ft
    if abs(dev) <= ALT_DEV_FT:
        return []
    recent: list[StateVector] = []
    for r in reversed(ctx.track(sv.icao24)):  # smallest suffix with >= N fixes spanning >= 60 s
        recent.insert(0, r)
        if len(recent) >= ALT_DEV_MIN_FIXES and recent[-1].ts - recent[0].ts >= ALT_DEV_MIN_PERSIST_S:
            break
    else:
        return []  # not enough history yet
    if not all(
        r.selected_alt_ft is not None
        and r.baro_alt_ft is not None
        and abs(r.baro_alt_ft - r.selected_alt_ft) > ALT_DEV_FT
        and abs(r.vrate_fpm or 0) <= LEVEL_VRATE_FPM
        for r in recent
    ):
        return []  # single-snapshot deviations are usually a pending clearance, not a bust
    likely_bust = abs(dev) <= ALT_DEV_PRESELECT_FT
    return [
        _mk(
            "OPS-004",
            "Persistent level flight away from autopilot-selected altitude"
            + ("" if likely_bust else " (large gap: likely pre-selected next level)"),
            Severity.LOW if likely_bust else Severity.INFO,
            Category.SAFETY, sv,
            {"selected_alt_ft": sv.selected_alt_ft, "deviation_ft": round(dev, 0), "vrate_fpm": sv.vrate_fpm,
             "persisted_fixes": len(recent), "persisted_s": round(recent[-1].ts - recent[0].ts, 0)},
            ["ICAO Doc 4444 (level bust reporting)", "EUROCONTROL level bust toolkit"],
            "May be a pending clearance; if persistent, review as potential level bust.",
        )
    ]


@rule("OPS-005")
def vfr_code_in_class_a(sv: StateVector, f: TrackFeatures | None, ctx: RuleContext) -> list[Finding]:
    if sv.on_ground or sv.squawk != "1200" or (sv.baro_alt_ft or 0) < CLASS_A_FLOOR_FT:
        return []
    return [
        _mk(
            "OPS-005", "VFR code 1200 above FL180 (Class A requires assigned code)", Severity.LOW,
            Category.OPERATIONS, sv, {"squawk": sv.squawk},
            ["14 CFR 91.135 (Class A operations)", "FAA AIM 4-1-20"],
            "US-specific; outside the US the VFR code differs (e.g. 7000 in ICAO/Europe).",
        )
    ]


# ---- catalog (for docs, coverage tests, and CLI help) ----------------------------------------
RULE_CATALOG: dict[str, tuple[str, str]] = {
    "SEC-001": ("security", "Squawk 7700 general emergency"),
    "SEC-002": ("security", "Squawk 7600 radio failure"),
    "SEC-003": ("security", "Squawk 7500 unlawful interference"),
    "SEC-004": ("security", "Emergency status subfield set"),
    "SEC-010": ("security", "Kinematically impossible position jump"),
    "SEC-011": ("security", "Reported vs implied ground speed mismatch"),
    "SEC-012": ("data-quality", "NIC/NACp/SIL below rule-airspace minimums (ADS-B sources only)"),
    "SEC-013": ("security", "Airborne above 10,000 ft without flight ID"),
    "SEC-014": ("security", "Same ICAO24 at two distant positions in one batch"),
    "SEC-015": ("security", "Cross-feed position disagreement (corroboration)"),
    "SEC-016": ("security", "New-address burst (flooding indicator)"),
    "SEC-017": ("security", "Coverage collapse (jamming / feed outage indicator)"),
    "SEC-018": ("security", "Altitude change inconsistent with reported vertical rate"),
    "SEC-020": ("security", "Watchlist match"),
    "OPS-001": ("operations", "Surveillance coverage gap (stale position)"),
    "OPS-002": ("operations", "Airline-style holding (>= 3,000 ft and >= 150 kt)"),
    "OPS-003": ("operations", "Low-altitude / low-speed orbiting (pattern work, survey, helicopter)"),
    "OPS-004": ("safety", "Persistent level flight away from selected altitude"),
    "OPS-005": ("operations", "VFR code 1200 above FL180 (US)"),
    "SAF-003": ("safety", "Excessive vertical rate"),
    "SAF-004": ("safety", "Close proximity between airborne aircraft (indicative separation check)"),
    "ML-001": ("ml", "IsolationForest kinematic anomaly"),
    "OPS-VIS-001": ("operations", "Apron zone over planned capacity"),
    "OPS-VIS-002": ("operations", "Apron zone unoccupied"),
}
