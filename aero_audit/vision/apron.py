"""Apron / gate zone occupancy from detections -> process-optimization findings.

Zones are polygons in normalized image coordinates so the same config works across camera
resolutions. Capacity is the planned number of stands in the zone; exceeding it is a
congestion signal, zero occupancy over time is under-utilization.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
