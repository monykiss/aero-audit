"""CCSDS Conjunction Data Messages (508.0-B, KVN form) and a probability of collision.

A CDM is what an owner or operator receives from a screening centre: time of closest approach,
miss distance, relative state, and for each object a state vector and a position covariance in
its own RTN (radial, transverse, normal) frame. With covariance the question "how likely is a
collision" has a defensible answer; without it (TLEs) it does not, which is why ``orbital.py``
stops at distance.

``pc_2d`` implements the standard short-encounter probability: rotate each RTN covariance to the
inertial frame using that object's state, add them, project the sum and the miss vector onto the
plane perpendicular to the relative velocity, and integrate the 2D Gaussian over a circle whose
radius is the combined hard-body radius. The integral is done on a polar grid, plainly, so the
result can be checked by hand. Rules:

- ORB-004 probability of collision above ``PC_ALERT`` (HIGH) or ``PC_WATCH`` (MEDIUM).
- ORB-005 CDM internal inconsistency: stated miss distance vs the state vectors disagree by more
  than ``MISS_TOLERANCE``, or a covariance is not positive definite.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..audit.findings import Category, Finding, Severity

PC_ALERT = 1e-4
PC_WATCH = 1e-7
MISS_TOLERANCE = 0.05  # 5 % between stated miss distance and the state-vector miss
DEFAULT_HBR_M = 20.0   # combined hard-body radius when the message gives no object sizes

_KV = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*(\[[^\]]*\])?\s*$")


@dataclass
class CdmObject:
    designator: str = ""
    name: str = ""
    ref_frame: str = ""
    position_km: tuple[float, float, float] | None = None
    velocity_kms: tuple[float, float, float] | None = None
    cov_rtn_m2: list[list[float]] | None = None  # 3x3 position covariance, RTN, m^2
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class CDM:
    message_id: str = ""
    originator: str = ""
    creation_date: str = ""
    tca: str = ""
    miss_distance_m: float | None = None
    relative_speed_ms: float | None = None
    stated_pc: float | None = None
    objects: list[CdmObject] = field(default_factory=list)
    header: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "originator": self.originator, "creation_date": self.creation_date, "tca": self.tca,
                "miss_distance_m": self.miss_distance_m, "relative_speed_ms": self.relative_speed_ms, "stated_pc": self.stated_pc,
                "objects": [{"designator": o.designator, "name": o.name, "ref_frame": o.ref_frame, "has_state": o.position_km is not None,
                             "has_covariance": o.cov_rtn_m2 is not None} for o in self.objects]}


def parse_cdm(text: str) -> CDM:
    cdm = CDM()
    current: CdmObject | None = None
    for raw in text.splitlines():
        line = raw.split("COMMENT", 1)[0] if raw.strip().startswith("COMMENT") else raw
        m = _KV.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "OBJECT":
            current = CdmObject()
            cdm.objects.append(current)
            current.fields[key] = val
            continue
        if current is None:
            cdm.header[key] = val
            if key == "MESSAGE_ID":
                cdm.message_id = val
            elif key == "ORIGINATOR":
                cdm.originator = val
            elif key == "CREATION_DATE":
                cdm.creation_date = val
            elif key == "TCA":
                cdm.tca = val
            elif key == "MISS_DISTANCE":
                cdm.miss_distance_m = _f(val)
            elif key == "RELATIVE_SPEED":
                cdm.relative_speed_ms = _f(val)
            elif key == "COLLISION_PROBABILITY":
                cdm.stated_pc = _f(val)
            continue
        current.fields[key] = val
        if key == "OBJECT_DESIGNATOR":
            current.designator = val
        elif key == "OBJECT_NAME":
            current.name = val
        elif key == "REF_FRAME":
            current.ref_frame = val
    for o in cdm.objects:
        f = o.fields
        if all(k in f for k in ("X", "Y", "Z")):
            o.position_km = (_f(f["X"]), _f(f["Y"]), _f(f["Z"]))
        if all(k in f for k in ("X_DOT", "Y_DOT", "Z_DOT")):
            o.velocity_kms = (_f(f["X_DOT"]), _f(f["Y_DOT"]), _f(f["Z_DOT"]))
        if all(k in f for k in ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N")):
            crr, ctr, ctt, cnr, cnt, cnn = (_f(f[k]) for k in ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N"))
            o.cov_rtn_m2 = [[crr, ctr, cnr], [ctr, ctt, cnt], [cnr, cnt, cnn]]
    return cdm


def _f(v: str) -> float:
    return float(v.split()[0])


# ---- linear algebra, small and explicit ---------------------------------------------------------
def _sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: tuple[float, ...]) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: tuple[float, ...]) -> tuple[float, float, float]:
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def rtn_basis(r: tuple[float, ...], v: tuple[float, ...]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    R = _unit(r)
    N = _unit(_cross(r, v))
    T = _cross(N, R)
    return R, T, N


def rtn_to_inertial(cov: list[list[float]], r: tuple[float, ...], v: tuple[float, ...]) -> list[list[float]]:
    """M C Mᵀ with M's columns the RTN unit vectors in the inertial frame."""
    R, T, N = rtn_basis(r, v)
    M = [[R[i], T[i], N[i]] for i in range(3)]
    tmp = [[sum(M[i][k] * cov[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [[sum(tmp[i][k] * M[j][k] for k in range(3)) for j in range(3)] for i in range(3)]


def positive_definite(c: list[list[float]]) -> bool:
    a, b, d = c[0][0], c[1][1], c[2][2]
    det2 = c[0][0] * c[1][1] - c[0][1] * c[1][0]
    det3 = (c[0][0] * (c[1][1] * c[2][2] - c[1][2] * c[2][1]) - c[0][1] * (c[1][0] * c[2][2] - c[1][2] * c[2][0])
            + c[0][2] * (c[1][0] * c[2][1] - c[1][1] * c[2][0]))
    return a > 0 and b > 0 and d > 0 and det2 > 0 and det3 > 0


def pc_2d(cdm: CDM, hbr_m: float = DEFAULT_HBR_M, n_r: int = 80, n_theta: int = 180) -> dict[str, Any]:
    """Short-encounter probability of collision from the two states and covariances."""
    if len(cdm.objects) < 2:
        raise ValueError("CDM needs two objects")
    o1, o2 = cdm.objects[0], cdm.objects[1]
    if o1.position_km is None or o2.position_km is None or o1.velocity_kms is None or o2.velocity_kms is None:
        raise ValueError("both objects need state vectors (X, Y, Z, X_DOT, Y_DOT, Z_DOT)")
    if o1.cov_rtn_m2 is None or o2.cov_rtn_m2 is None:
        raise ValueError("both objects need position covariance (CR_R .. CN_N)")
    for o in (o1, o2):
        if not positive_definite(o.cov_rtn_m2):
            raise ValueError(f"covariance of {o.designator or 'object'} is not positive definite")
    rel_km = _sub(o2.position_km, o1.position_km)
    rel_v = _sub(o2.velocity_kms, o1.velocity_kms)
    miss_m = _norm(rel_km) * 1000.0
    rel_speed = _norm(rel_v) * 1000.0
    if rel_speed < 1e-9:
        raise ValueError("relative velocity is zero: not a short encounter")
    c1 = rtn_to_inertial(o1.cov_rtn_m2, o1.position_km, o1.velocity_kms)
    c2 = rtn_to_inertial(o2.cov_rtn_m2, o2.position_km, o2.velocity_kms)
    C = [[c1[i][j] + c2[i][j] for j in range(3)] for i in range(3)]
    # encounter plane: perpendicular to the relative velocity; basis e1 along the in-plane miss, e2 = vhat x e1
    vhat = _unit(rel_v)
    rel_m = tuple(x * 1000.0 for x in rel_km)
    along = _dot(rel_m, vhat)
    in_plane = (rel_m[0] - along * vhat[0], rel_m[1] - along * vhat[1], rel_m[2] - along * vhat[2])
    if _norm(in_plane) < 1e-9:
        e1 = _unit(_cross(vhat, (1.0, 0.0, 0.0) if abs(vhat[0]) < 0.9 else (0.0, 1.0, 0.0)))
    else:
        e1 = _unit(in_plane)
    e2 = _cross(vhat, e1)
    def proj(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return sum(a[i] * C[i][j] * b[j] for i in range(3) for j in range(3))
    s11, s12, s22 = proj(e1, e1), proj(e1, e2), proj(e2, e2)
    det = s11 * s22 - s12 * s12
    if det <= 0:
        raise ValueError("projected covariance is singular")
    mx, my = _dot(in_plane, e1), _dot(in_plane, e2)
    inv11, inv12, inv22 = s22 / det, -s12 / det, s11 / det
    norm = 1.0 / (2.0 * math.pi * math.sqrt(det))
    # integrate the Gaussian centred at the miss vector over the disc of radius hbr at the origin
    total = 0.0
    dr = hbr_m / n_r
    dth = 2.0 * math.pi / n_theta
    for i in range(n_r):
        rr = (i + 0.5) * dr
        for j in range(n_theta):
            th = (j + 0.5) * dth
            x, y = rr * math.cos(th) - mx, rr * math.sin(th) - my
            q = inv11 * x * x + 2 * inv12 * x * y + inv22 * y * y
            total += math.exp(-0.5 * q) * rr * dr * dth
    pc = min(1.0, norm * total)
    return {"pc": pc, "miss_m": miss_m, "in_plane_miss_m": math.hypot(mx, my), "relative_speed_ms": rel_speed, "hbr_m": hbr_m,
            "sigma_plane_m": (math.sqrt(s11), math.sqrt(s22)), "stated_miss_m": cdm.miss_distance_m, "stated_pc": cdm.stated_pc,
            "method": "2D short-encounter, numerical integration on a polar grid"}


def assess(cdm: CDM, hbr_m: float = DEFAULT_HBR_M, now: datetime | None = None) -> tuple[dict[str, Any], list[Finding]]:
    ts = (now or datetime.now(UTC)).timestamp()
    stream = cdm.message_id or "cdm"
    findings: list[Finding] = []
    result: dict[str, Any] = {"cdm": cdm.to_dict()}
    try:
        pc = pc_2d(cdm, hbr_m)
        result["pc"] = pc
    except ValueError as e:
        result["error"] = str(e)
        findings.append(Finding(rule_id="ORB-005", title=f"CDM cannot be assessed: {e}", severity=Severity.MEDIUM, category=Category.DATA_QUALITY,
                                callsign=stream, ts=ts, evidence={"stream": stream, "error": str(e)}, controls=["CCSDS 508.0-B"],
                                recommendation="Ask the originator for a complete message with states and covariances."))
        return result, findings
    if cdm.miss_distance_m is not None and cdm.miss_distance_m > 0:
        rel = abs(pc["miss_m"] - cdm.miss_distance_m) / cdm.miss_distance_m
        result["miss_consistency"] = round(rel, 4)
        if rel > MISS_TOLERANCE:
            findings.append(Finding(rule_id="ORB-005", title=f"CDM inconsistent: stated miss {cdm.miss_distance_m:.0f} m vs state-vector miss {pc['miss_m']:.0f} m",
                                    severity=Severity.MEDIUM, category=Category.DATA_QUALITY, callsign=stream, ts=ts,
                                    evidence={"stream": stream, "stated_miss_m": cdm.miss_distance_m, "state_miss_m": round(pc["miss_m"], 1), "relative_error": round(rel, 4)},
                                    controls=["CCSDS 508.0-B"], recommendation="Do not act on this message until the originator confirms which figure is right."))
    if pc["pc"] >= PC_ALERT:
        sev, title = Severity.HIGH, f"Probability of collision {pc['pc']:.2e} above the manoeuvre threshold"
    elif pc["pc"] >= PC_WATCH:
        sev, title = Severity.MEDIUM, f"Probability of collision {pc['pc']:.2e}: monitor and refresh"
    else:
        sev, title = None, ""
    if sev:
        findings.append(Finding(rule_id="ORB-004", title=title, severity=sev, category=Category.SAFETY, callsign=stream, ts=ts,
                                evidence={"stream": stream, "pc": pc["pc"], "miss_m": round(pc["miss_m"], 1), "hbr_m": hbr_m, "tca": cdm.tca,
                                          "relative_speed_ms": round(pc["relative_speed_ms"], 1), "objects": [o.designator for o in cdm.objects]},
                                controls=["CCSDS 508.0-B", "ISO 24113", "NASA-STD-8719.14"],
                                recommendation="Refresh with the latest CDM before TCA; plan a manoeuvre if Pc stays above threshold and the owner concurs."))
    return result, findings


__all__ = ["CDM", "DEFAULT_HBR_M", "MISS_TOLERANCE", "PC_ALERT", "PC_WATCH", "CdmObject", "assess", "parse_cdm", "pc_2d", "positive_definite", "rtn_to_inertial"]
