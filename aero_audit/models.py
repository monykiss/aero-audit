"""Normalized data model shared by every provider.

Every feed (OpenSky, adsb.lol, replayed recordings, synthetic generators) is mapped into
`StateVector` so the audit rules and ML features never care where the data came from.
Units are aviation-native: feet, knots, degrees, feet/min, epoch seconds.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Source(StrEnum):
    OPENSKY = "opensky"
    ADSBLOL = "adsblol"
    REPLAY = "replay"
    SYNTHETIC = "synthetic"


class StateVector(BaseModel):
    icao24: str
    callsign: str | None = None
    registration: str | None = None
    aircraft_type: str | None = None
    ts: float  # epoch seconds of the position fix
    lat: float | None = None
    lon: float | None = None
    baro_alt_ft: float | None = None
    geo_alt_ft: float | None = None
    gs_kt: float | None = None
    track_deg: float | None = None
    vrate_fpm: float | None = None
    squawk: str | None = None
    on_ground: bool = False
    emergency: str | None = None
    selected_alt_ft: float | None = None  # autopilot-selected altitude (adsb.lol nav_altitude_mcp)
    # ADS-B integrity/accuracy indicators (DO-260B). Only some feeds carry these.
    nic: int | None = None  # Navigation Integrity Category (0-11)
    nac_p: int | None = None  # Navigation Accuracy Category for Position (0-11)
    sil: int | None = None  # Source Integrity Level (0-3)
    position_source: str | None = None  # adsb | mlat | tisb | adsc | asterix | flarm
    source: Source
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def airborne(self) -> bool:
        return not self.on_ground

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def label(self) -> str:
        cs = (self.callsign or "").strip()
        return f"{self.icao24}{' ' + cs if cs else ''}"


class Batch(BaseModel):
    """One polling snapshot of a region."""

    ts: float
    provider: str
    region: str
    states: list[StateVector]
    schema_version: int = 1

    def __len__(self) -> int:
        return len(self.states)
