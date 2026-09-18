"""Apron / gate zone occupancy from detections -> process-optimization findings.

Zones are polygons in normalized image coordinates so the same config works across camera
resolutions. Capacity is the planned number of stands in the zone; exceeding it is a
congestion signal, zero occupancy over time is under-utilization.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from .detect import Detection


@dataclass
class Zone:
    name: str
    polygon: list[tuple[float, float]]  # normalized (x, y) vertices
    capacity: int = 1
    meta: dict = field(default_factory=dict)


DEFAULT_ZONES: list[Zone] = [
    Zone("left-half", [(0, 0), (0.5, 0), (0.5, 1), (0, 1)], capacity=2),
    Zone("right-half", [(0.5, 0), (1, 0), (1, 1), (0.5, 1)], capacity=2),
]


def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def occupancy(dets: list[Detection], zones: list[Zone]) -> dict[str, int]:
    counts = {z.name: 0 for z in zones}
    for d in dets:
        for z in zones:
            if point_in_polygon(d.cx, d.cy, z.polygon):
                counts[z.name] += 1
    return counts


def zones_from_json(path: str | Path) -> list[Zone]:
    """[{name, polygon: [[x, y], ...] normalised, capacity}]: the declared stands per zone for one camera view."""
    rows = json.loads(Path(path).read_text())
    return [Zone(z["name"], [tuple(p) for p in z["polygon"]], int(z.get("capacity", 1)), dict(z.get("meta") or {})) for z in rows]


def detections_from_json(path: str | Path) -> list[Detection]:
    """Detections from any source (a detector run, or hand annotations): rows with normalised cx, cy and optional w, h,
    label, conf; pixel boxes are filled in when the file names the image size."""
    d = json.loads(Path(path).read_text())
    rows = d.get("detections", d) if isinstance(d, dict) else d
    w_px, h_px = (d.get("width"), d.get("height")) if isinstance(d, dict) else (None, None)
    out = []
    for r in rows:
        cx, cy = float(r["cx"]), float(r["cy"])
        w, h = float(r.get("w", 0.0)), float(r.get("h", 0.0))
        x1, y1, x2, y2 = (int((cx - w / 2) * w_px), int((cy - h / 2) * h_px), int((cx + w / 2) * w_px), int((cy + h / 2) * h_px)) if w_px and h_px else (0, 0, 0, 0)
        out.append(Detection(str(r.get("label", "airplane")), float(r.get("conf", 1.0)), x1, y1, x2, y2, cx, cy))
    return out


def evaluate(dets: list[Detection], truth: list[Detection], max_dist: float = 0.03) -> dict[str, Any]:
    """Greedy centre matching within a normalised distance: recall and precision of a detector against annotations,
    so the capacity check states how much of the apron it actually saw."""
    unmatched = list(range(len(truth)))
    matched = 0
    for d in sorted(dets, key=lambda x: -x.conf):
        best, best_d = None, max_dist
        for i in unmatched:
            t = truth[i]
            dist = math.hypot(d.cx - t.cx, d.cy - t.cy)
            if dist <= best_d:
                best, best_d = i, dist
        if best is not None:
            unmatched.remove(best)
            matched += 1
    return {"truth": len(truth), "detected": len(dets), "matched": matched, "recall": round(matched / len(truth), 3) if truth else None,
            "precision": round(matched / len(dets), 3) if dets else None, "max_dist": max_dist}


def zone_findings(counts: dict[str, int], zones: list[Zone], image: str, ts: float) -> list[Finding]:
    out: list[Finding] = []
    for z in zones:
        n = counts.get(z.name, 0)
        if n > z.capacity:
            out.append(
                Finding(
                    rule_id="OPS-VIS-001",
                    title=f"Zone '{z.name}' over planned capacity ({n}/{z.capacity})",
                    severity=Severity.MEDIUM,
                    category=Category.OPERATIONS,
                    ts=ts,
                    evidence={"image": image, "zone": z.name, "count": n, "capacity": z.capacity},
                    controls=["ICAO Annex 14 (aerodrome apron management)", "A-CDM milestone tracking"],
                    recommendation="Congested stand group; review stand allocation and turnaround SLAs.",
                )
            )
        elif n == 0:
            out.append(
                Finding(
                    rule_id="OPS-VIS-002",
                    title=f"Zone '{z.name}' unoccupied",
                    severity=Severity.INFO,
                    category=Category.OPERATIONS,
                    ts=ts,
                    evidence={"image": image, "zone": z.name, "capacity": z.capacity},
                    controls=["A-CDM stand utilization KPIs"],
                    recommendation="Track over time; persistent idle stands are an allocation inefficiency.",
                )
            )
    return out
