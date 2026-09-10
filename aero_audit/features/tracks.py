"""Per-aircraft track memory and kinematic feature extraction.

The central idea for ADS-B security auditing: a transponder can *claim* anything, but two
consecutive position reports imply a ground speed, a climb rate, and a turn rate. Comparing
implied kinematics against reported kinematics (and against physics) is how spoofing,
injection, and corrupted feeds get caught without any cryptography.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from itertools import pairwise

from ..config import EARTH_RADIUS_NM
from ..models import Batch, StateVector


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def heading_delta(a: float, b: float) -> float:
    """Signed smallest rotation from heading a to heading b, in degrees, in (-180, 180]."""
    d = (b - a) % 360.0
    return d - 360.0 if d > 180.0 else d


@dataclass
class TrackFeatures:
    icao24: str
    ts: float
    n_fixes: int
    dt_s: float  # seconds since previous distinct fix
    dist_nm: float  # great-circle distance from previous fix
    implied_gs_kt: float  # dist / dt
    reported_gs_kt: float | None
    gs_mismatch_kt: float | None  # implied - reported
    implied_vrate_fpm: float | None
    reported_vrate_fpm: float | None
    turn_rate_dps: float | None  # degrees per second between the last two fixes
    window_heading_sum_deg: float  # cumulative signed heading change across the window
    window_net_nm: float  # straight-line displacement across the window
    window_path_nm: float  # path length across the window
    window_span_s: float
    baro_alt_ft: float | None
    on_ground: bool
    position_source: str | None = None
    accel_kt_s: float | None = None  # change in reported ground speed per second
    vrate_mismatch_fpm: float | None = None  # implied - reported vertical rate
    gs_mismatch_ratio: float | None = None  # mismatch relative to reported speed
    window_gs_std_kt: float | None = None  # speed variability across the window

    def to_dict(self) -> dict:
        return asdict(self)


class TrackStore:
    """Keeps the last `window` distinct fixes per aircraft and derives features on update."""

    def __init__(self, window: int = 12, max_age_s: float = 600.0) -> None:
        self.window = window
        self.max_age_s = max_age_s
        self._tracks: dict[str, deque[StateVector]] = {}

    def __len__(self) -> int:
        return len(self._tracks)

    def track(self, icao24: str) -> list[StateVector]:
        return list(self._tracks.get(icao24, ()))

    def update(self, batch: Batch) -> list[TrackFeatures]:
        feats: list[TrackFeatures] = []
        for sv in batch.states:
            if not sv.has_position:
                continue
            dq = self._tracks.setdefault(sv.icao24, deque(maxlen=self.window))
            if dq and self._is_duplicate(dq[-1], sv):
                continue
            dq.append(sv)
            f = self.features(sv.icao24)
            if f is not None:
                feats.append(f)
        self._evict(batch.ts)
        return feats

    @staticmethod
    def _is_duplicate(prev: StateVector, cur: StateVector) -> bool:
        dt = cur.ts - prev.ts
        if dt < 0.5:
            return True
        same_pos = prev.lat == cur.lat and prev.lon == cur.lon
        return same_pos and dt < 5.0

    def features(self, icao24: str) -> TrackFeatures | None:
        dq = self._tracks.get(icao24)
        if not dq or len(dq) < 2:
            return None
        cur, prev = dq[-1], dq[-2]
        dt = cur.ts - prev.ts
        if dt <= 0:
            return None
        dist = haversine_nm(prev.lat, prev.lon, cur.lat, cur.lon)  # type: ignore[arg-type]
        implied_gs = dist / dt * 3600.0
        mismatch = implied_gs - cur.gs_kt if cur.gs_kt is not None else None
        # No implied vertical rate across a ground transition: feeds report 0 ft or nothing on the
        # ground, and a departure from a 4,000 ft-elevation airport is not a 4,000 ft jump.
        implied_vr = (
            (cur.baro_alt_ft - prev.baro_alt_ft) / dt * 60.0
            if cur.baro_alt_ft is not None and prev.baro_alt_ft is not None
            and not (cur.on_ground or prev.on_ground)
            else None
        )
        turn = (
            heading_delta(prev.track_deg, cur.track_deg) / dt
            if cur.track_deg is not None and prev.track_deg is not None
            else None
        )
        accel = (
            (cur.gs_kt - prev.gs_kt) / dt if cur.gs_kt is not None and prev.gs_kt is not None else None
        )
        vr_mismatch = (
            implied_vr - cur.vrate_fpm if implied_vr is not None and cur.vrate_fpm is not None else None
        )
        ratio = mismatch / max(cur.gs_kt, 50.0) if mismatch is not None and cur.gs_kt is not None else None
        speeds = [x.gs_kt for x in dq if x.gs_kt is not None]
        gs_std = (
            (sum((v - sum(speeds) / len(speeds)) ** 2 for v in speeds) / (len(speeds) - 1)) ** 0.5
            if len(speeds) >= 2 else None
        )
        hsum = 0.0
        path = 0.0
        for a, b in pairwise(dq):
            if a.track_deg is not None and b.track_deg is not None:
                hsum += heading_delta(a.track_deg, b.track_deg)
            path += haversine_nm(a.lat, a.lon, b.lat, b.lon)  # type: ignore[arg-type]
        first = dq[0]
        net = haversine_nm(first.lat, first.lon, cur.lat, cur.lon)  # type: ignore[arg-type]
        return TrackFeatures(
            icao24=icao24,
            ts=cur.ts,
            n_fixes=len(dq),
            dt_s=dt,
            dist_nm=dist,
            implied_gs_kt=implied_gs,
            reported_gs_kt=cur.gs_kt,
            gs_mismatch_kt=mismatch,
            implied_vrate_fpm=implied_vr,
            reported_vrate_fpm=cur.vrate_fpm,
            turn_rate_dps=turn,
            window_heading_sum_deg=hsum,
            window_net_nm=net,
            window_path_nm=path,
            window_span_s=cur.ts - first.ts,
            baro_alt_ft=cur.baro_alt_ft,
            on_ground=cur.on_ground,
            position_source=cur.position_source,
            accel_kt_s=accel,
            vrate_mismatch_fpm=vr_mismatch,
            gs_mismatch_ratio=ratio,
            window_gs_std_kt=gs_std,
        )

    def _evict(self, now: float) -> None:
        stale = [k for k, dq in self._tracks.items() if dq and now - dq[-1].ts > self.max_age_s]
        for k in stale:
            del self._tracks[k]
