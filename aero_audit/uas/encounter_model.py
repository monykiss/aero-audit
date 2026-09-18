"""An encounter model fitted from observed traffic, and a Monte Carlo estimate of NMAC rates with
and without an alerting horizon.

The MIT Lincoln Laboratory encounter models (em-core lineage) describe encounters statistically,
so that a DAA system can be exercised on millions of synthetic geometries rather than the few
hundred a recording holds. This is the small, honest version of that idea: from the encounter
samples a recording produced (encounters.extract_encounters) it fits the empirical distributions
of relative horizontal speed, initial range, bearing of the relative velocity, vertical
separation and vertical rate, then samples straight-line encounters from them, propagates each
one, and counts NMACs (500 ft / 100 ft). Two numbers come out:

- the unmitigated NMAC probability per encounter (nobody manoeuvres), and
- the mitigated one, where an encounter counts as resolved if the well-clear violation is
  projected at least ``horizon_s`` before it happens (an alerting horizon; the manoeuvre itself
  is assumed to succeed). Their ratio is the model-based risk ratio, next to the observed bound in
  risk.py.

Distributions are empirical (resampled with jitter), not parametric fits; the result depends on
the recording it was fitted from and says so in the manifest.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .encounters import NMAC_H_FT, NMAC_V_FT, extract_encounters
from .wellclear import evaluate

HORIZON_S = 25.0


def fit(ex: dict[str, Any]) -> dict[str, Any]:
    """Empirical marginals from the first sample of every encounter pair (the encounter's initial condition)."""
    firsts = []
    for samples in ex["pairs"].values():
        s0 = min(samples, key=lambda e: e["ts"])
        firsts.append(s0)
    if len(firsts) < 5:
        raise ValueError(f"need at least 5 encounter pairs to fit; got {len(firsts)}")
    rng_ft = np.array([e["range_ft"] for e in firsts])
    dz = np.array([e["dz_ft"] for e in firsts])
    rel_v = np.array([abs(e.get("closure_ftps") or 0.0) for e in firsts])  # closure rate: a lower bound on relative speed
    tau = np.array([e["tau_mod_s"] if e.get("tau_mod_s") is not None else -1.0 for e in firsts])
    return {"n": len(firsts), "recording": ex.get("recording"), "flight_hours": ex.get("flight_hours"),
            "range_ft": rng_ft.tolist(), "dz_ft": dz.tolist(), "rel_speed_fps": rel_v.tolist(), "converging_share": float(np.mean(tau >= 0)),
            "range_ft_q": np.percentile(rng_ft, [10, 50, 90]).round(0).tolist(), "dz_ft_q": np.percentile(np.abs(dz), [10, 50, 90]).round(0).tolist()}


def sample_encounters(model: dict[str, Any], n: int, seed: int = 0) -> list[dict[str, float]]:
    """Straight-line encounters: initial range and vertical offset resampled from the model; relative speed resampled
    (falling back to a 150-500 ft/s spread when the recording gave none); the relative-velocity bearing spread so
    that the horizontal miss distance is uniform on [0, range]."""
    rng = np.random.default_rng(seed)
    r = np.abs(rng.choice(model["range_ft"], n) * rng.normal(1.0, 0.1, n))
    dz = rng.choice(model["dz_ft"], n) * rng.normal(1.0, 0.15, n)
    v = np.abs(np.array(model["rel_speed_fps"]))
    v = v[v > 1.0]
    speed = rng.choice(v, n) * rng.normal(1.0, 0.1, n) if len(v) >= 5 else rng.uniform(150.0, 500.0, n)
    hmd = rng.uniform(0.0, 1.0, n) * r
    vz = rng.normal(0.0, 8.0, n)  # ft/s vertical closure, ~500 fpm sigma
    converging = rng.uniform(0, 1, n) < max(model.get("converging_share", 0.5), 0.05)
    return [{"range_ft": float(r[i]), "dz_ft": float(dz[i]), "speed_fps": float(speed[i]), "hmd_ft": float(hmd[i]), "vz_fps": float(vz[i]), "converging": bool(converging[i])} for i in range(n)]


def _propagate(e: dict[str, float], dt: float = 1.0, max_t: float = 300.0) -> dict[str, Any]:
    """Relative motion in the horizontal plane: intruder starts at (range, 0) and moves so that the closest point of
    approach is hmd; returns NMAC flag, time of minimum range, and the first time well clear is lost."""
    r, hmd, v = e["range_ft"], min(e["hmd_ft"], e["range_ft"]), e["speed_fps"]
    if not e["converging"] or v <= 0:
        return {"nmac": False, "t_min": None, "t_violation": None}
    along = math.sqrt(max(r * r - hmd * hmd, 0.0))
    s = np.array([along, hmd])
    vel = np.array([-v, 0.0])
    dz, vz = e["dz_ft"], e["vz_fps"]
    t_viol: float | None = None
    nmac = False
    t = 0.0
    while t <= max_t:
        st = s + vel * t
        z = dz + vz * t
        ev = evaluate((float(st[0]), float(st[1])), (float(vel[0]), float(vel[1])), z, vz)
        if not ev["well_clear"] and t_viol is None:
            t_viol = t
        if math.hypot(*st) <= NMAC_H_FT and abs(z) <= NMAC_V_FT:
            nmac = True
            break
        if st[0] < -r:  # passed and diverging
            break
        t += dt
    return {"nmac": nmac, "t_min": along / v, "t_violation": t_viol}


def simulate(model: dict[str, Any], n: int = 2000, horizon_s: float = HORIZON_S, seed: int = 0) -> dict[str, Any]:
    encs = sample_encounters(model, n, seed)
    unmit = 0
    mit = 0
    viol = 0
    for e in encs:
        res = _propagate(e)
        if res["t_violation"] is not None:
            viol += 1
        if res["nmac"]:
            unmit += 1
            # resolved if the violation was projected at least horizon_s before the NMAC; otherwise it still happens
            if res["t_violation"] is None or (res["t_min"] - res["t_violation"]) < horizon_s:
                mit += 1
    p_un = unmit / n
    p_mit = mit / n
    per_fh = None
    if model.get("flight_hours"):
        enc_rate = model["n"] / model["flight_hours"]
        per_fh = {"encounters_per_fh": round(enc_rate, 4), "nmac_per_fh_unmitigated": round(enc_rate * p_un, 6), "nmac_per_fh_mitigated": round(enc_rate * p_mit, 6)}
    return {"n": n, "horizon_s": horizon_s, "seed": seed, "violations": viol, "nmac_unmitigated": unmit, "nmac_mitigated": mit,
            "p_nmac_unmitigated": round(p_un, 5), "p_nmac_mitigated": round(p_mit, 5), "risk_ratio": None if unmit == 0 else round(mit / unmit, 3),
            "rates": per_fh, "basis": "straight-line encounters resampled from the fitted recording; manoeuvres assumed to succeed when alerted >= horizon before NMAC"}


def fit_and_simulate(recording: str | Path, n: int = 2000, horizon_s: float = HORIZON_S, seed: int = 0, max_batches: int | None = None) -> dict[str, Any]:
    ex = extract_encounters(recording, max_batches=max_batches)
    model = fit(ex)
    sim = simulate(model, n, horizon_s, seed)
    return {"model": {k: v for k, v in model.items() if k not in ("range_ft", "dz_ft", "rel_speed_fps")}, "simulation": sim}


__all__ = ["HORIZON_S", "fit", "fit_and_simulate", "sample_encounters", "simulate"]
