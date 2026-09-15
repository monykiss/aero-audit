"""Micro-benchmarks for the space and UAS hot paths, on bundled or synthetic inputs so any machine can run them.

Each case reports best and median wall time over ``rounds`` and a rate in the unit that matters (pair-samples,
projections, triangles, pairs, granules per second). docs/PERFORMANCE.md records the numbers before and after the
vectorised rewrites; ``aero bench --suite space`` reproduces them.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np


def _timed(fn: Any, rounds: int) -> tuple[float, float, Any]:
    ts = []
    out = None
    for _ in range(rounds):
        t0 = time.perf_counter()
        out = fn()
        ts.append(time.perf_counter() - t0)
    return min(ts), statistics.median(ts), out


def sphere_mesh(nu: int = 200, nv: int = 100) -> tuple[np.ndarray, np.ndarray]:
    th = 2 * np.pi * np.arange(nu) / nu
    ph = np.pi * (np.arange(nv) + 0.5) / nv
    TH, PH = np.meshgrid(th, ph, indexing="ij")
    v = np.stack([np.sin(PH) * np.cos(TH), np.cos(PH), np.sin(PH) * np.sin(TH)], axis=-1).reshape(-1, 3)
    faces = []
    for i in range(nu):
        for j in range(nv - 1):
            a, b = i * nv + j, ((i + 1) % nu) * nv + j
            faces.append([a, b, b + 1])
            faces.append([a, b + 1, a + 1])
    return v, np.asarray(faces, dtype=np.int64)


def synthetic_elements(n: int = 120) -> list[Any]:
    """A shell of near-circular LEO objects with varied RAAN and mean anomaly (valid checksums), for the screen benchmark."""
    from .space.orbital import parse_tle

    def cs(line: str) -> str:
        s = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
        return line[:68] + str(s % 10)

    rng = np.random.default_rng(7)
    text = []
    for k in range(n):
        norad = 90000 + k
        raan, ma = rng.uniform(0, 360), rng.uniform(0, 360)
        n_rev = 15.05 + rng.uniform(-0.02, 0.02)
        l1 = f"1 {norad:05d}U 26001A   26250.50000000 +.00001000  00000-0  10000-3 0  9990"
        l2 = f"2 {norad:05d}  53.0000 {raan:8.4f} 0001000  90.0000 {ma:8.4f} {n_rev:11.8f}    10"
        text.append(f"BENCH {k}\n{cs(l1)}\n{cs(l2)}")
    return parse_tle("\n".join(text) + "\n")


def run_suite(recording: Path | None, rounds: int = 3) -> list[dict[str, Any]]:
    from datetime import UTC, datetime

    from .governance import catalog
    from .space import render
    from .space.orbital import screen
    from .uas.encounters import extract_encounters, summarize_encounters
    from .uas.wellclear import ALERT_LEVELS, time_to_violation

    rows: list[dict[str, Any]] = []
    if recording and Path(recording).is_file():
        best, med, ex = _timed(lambda: extract_encounters(recording, max_batches=12), rounds)
        samples = sum(len(v) for v in ex["pairs"].values())
        rows.append({"case": "encounters.extract (12 batches)", "input": Path(recording).name, "best_s": best, "median_s": med, "rate": f"{samples / max(best, 1e-9):,.0f} pair-samples/s"})
        best, med, _ = _timed(lambda: summarize_encounters(ex), rounds)
        rows.append({"case": "encounters.summarize", "input": f"{len(ex['pairs'])} pairs", "best_s": best, "median_s": med, "rate": f"{len(ex['pairs']) / max(best, 1e-9):,.0f} pairs/s"})
    rng = np.random.default_rng(1)
    geoms = [((float(rng.uniform(-60000, 60000)), float(rng.uniform(-60000, 60000))), (float(rng.uniform(-700, 700)), float(rng.uniform(-700, 700))), float(rng.uniform(-3000, 3000)), float(rng.uniform(-30, 30))) for _ in range(2000)]

    def proj() -> int:
        return sum(1 for s, v, dz, vz in geoms for p in ALERT_LEVELS if time_to_violation(s, v, dz, vz, p, p.alerting_time_s) is not None)

    best, med, _ = _timed(proj, rounds)
    rows.append({"case": "wellclear.time_to_violation x3 levels", "input": "2,000 random geometries", "best_s": best, "median_s": med, "rate": f"{6000 / max(best, 1e-9):,.0f} projections/s"})
    v, f = sphere_mesh()
    best, med, _ = _timed(lambda: render.rasterise(v, f, 256, 30, 20), rounds)
    rows.append({"case": "render.rasterise 256px", "input": f"{len(f):,} triangles", "best_s": best, "median_s": med, "rate": f"{len(f) / max(best, 1e-9):,.0f} triangles/s"})
    sets = synthetic_elements(120)
    start = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    best, med, res = _timed(lambda: screen(sets, start, 6.0, 10.0, max_sets=120), rounds)
    rows.append({"case": "orbital.screen 6 h", "input": f"{len(sets)} objects, {res['pairs']} pairs", "best_s": best, "median_s": med, "rate": f"{res['pairs'] / max(best, 1e-9):,.0f} pairs/s"})
    best, med, cat = _timed(lambda: catalog.build_catalog("."), rounds)
    rows.append({"case": "catalog.build (hash cache warm)", "input": f"{cat['granules_total']} granules", "best_s": best, "median_s": med, "rate": f"{cat['granules_total'] / max(best, 1e-9):,.0f} granules/s"})
    return rows


__all__ = ["run_suite", "sphere_mesh", "synthetic_elements"]
