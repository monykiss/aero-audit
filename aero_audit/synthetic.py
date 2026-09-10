"""Synthetic traffic generator with injected anomalies for offline practice and tests.

Produces a JSONL recording in the same format as the live recorder, so every downstream
command (audit, train) treats it identically to real data.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from .config import get_region
from .models import Batch, Source, StateVector
from .stream import JsonlRecorder


def _step(lat: float, lon: float, gs_kt: float, track_deg: float, dt_s: float) -> tuple[float, float]:
    d_nm = gs_kt * dt_s / 3600.0
    t = math.radians(track_deg)
    lat2 = lat + d_nm * math.cos(t) / 60.0
    lon2 = lon + d_nm * math.sin(t) / (60.0 * max(math.cos(math.radians(lat)), 0.1))
    return lat2, lon2


class _Plane:
    def __init__(self, rng: random.Random, icao: str, cs: str, lat: float, lon: float) -> None:
        self.icao, self.cs = icao, cs
        self.lat, self.lon = lat, lon
        self.alt = rng.choice([4000, 8000, 12000, 24000, 31000, 35000, 37000, 39000])
        self.gs = rng.uniform(220, 470) if self.alt > 10000 else rng.uniform(160, 250)
        self.track = rng.uniform(0, 360)
        self.vr = rng.choice([0, 0, 0, 1200, -1500, 800])
        self.squawk = f"{rng.randint(1000, 7000):04d}".replace("8", "1").replace("9", "2")
        self.nic, self.nacp, self.sil = 8, 9, 3
        self.selected = None
        self.anomaly: str | None = None
        self.turn = 0.0

    def advance(self, dt: float) -> None:
        self.track = (self.track + self.turn * dt) % 360
        self.lat, self.lon = _step(self.lat, self.lon, self.gs, self.track, dt)
        self.alt = max(0.0, self.alt + self.vr * dt / 60.0)

    def state(self, ts: float) -> StateVector:
        return StateVector(
            icao24=self.icao, callsign=self.cs, ts=ts, lat=self.lat, lon=self.lon,
            baro_alt_ft=self.alt, geo_alt_ft=self.alt + 150, gs_kt=self.gs, track_deg=self.track,
            vrate_fpm=self.vr, squawk=self.squawk, on_ground=False, emergency="none",
            selected_alt_ft=self.selected, nic=self.nic, nac_p=self.nacp, sil=self.sil,
            position_source="adsb", source=Source.SYNTHETIC,
        )


def generate(
    out: str | Path,
    region_key: str = "nyc",
    n_aircraft: int = 40,
    polls: int = 30,
    interval_s: float = 10.0,
    seed: int = 7,
    start_ts: float = 1_700_000_000.0,
) -> Path:
    rng = random.Random(seed)
    reg = get_region(region_key)
    planes: list[_Plane] = []
    for i in range(n_aircraft):
        lat = reg.lat + rng.uniform(-0.8, 0.8)
        lon = reg.lon + rng.uniform(-1.0, 1.0)
        planes.append(_Plane(rng, f"a{i:05x}", f"SYN{i:03d}", lat, lon))

    # Injected anomalies (indices are stable thanks to the seed)
    spoof, emerg, hold, lownic, steep, vfr, blank = planes[:7]
    spoof.anomaly = "teleport"
    emerg.anomaly = "squawk7700"
    hold.anomaly = "holding"; hold.turn = 3.0; hold.gs = 210; hold.vr = 0  # 3 deg/s standard-rate turn
    lownic.anomaly = "lownic"; lownic.nic, lownic.nacp, lownic.sil = 4, 5, 0
    steep.anomaly = "steep"; steep.vr = 8000
    vfr.anomaly = "vfr_class_a"; vfr.squawk = "1200"; vfr.alt = 35000; vfr.vr = 0
    blank.anomaly = "blank_callsign"; blank.cs = ""; blank.alt = 33000
    # a normal aircraft in level flight with a selected altitude that disagrees (level bust)
    bust = planes[7]; bust.vr = 0; bust.alt = 31000; bust.selected = 30000

    rec = JsonlRecorder(out)
    ts = start_ts
    for k in range(polls):
        for p in planes:
            if k > 0:
                p.advance(interval_s)
            if p.anomaly == "teleport" and k == polls // 2:
                p.lat += 0.6  # ~36 nm jump inside one 10 s poll
            if p.anomaly == "squawk7700" and k >= polls // 3:
                p.squawk = "7700"
        batch = Batch(ts=ts, provider="synthetic", region=reg.key, states=[p.state(ts) for p in planes])
        rec.write(batch)
        ts += interval_s
    rec.close()
    return Path(out)
