"""Regions, unit conversions, and environment-driven settings."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

FT_PER_M = 3.28084
KT_PER_MPS = 1.943844
FPM_PER_MPS = 196.8504
NM_PER_KM = 0.539957
EARTH_RADIUS_NM = 3440.065


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    lat: float
    lon: float
    radius_nm: float
    metar_stations: tuple[str, ...] = ()
    custom_bbox: tuple[float, float, float, float] | None = None  # exact box for bbox providers
    endpoint: str | None = None  # provider-specific global feed instead of a geographic query

    def bbox(self) -> tuple[float, float, float, float]:
        """(lamin, lomin, lamax, lomax); exact if custom_bbox is set, else approximating the circle."""
        if self.custom_bbox:
            return self.custom_bbox
        dlat = self.radius_nm / 60.0
        dlon = self.radius_nm / (60.0 * max(math.cos(math.radians(self.lat)), 0.1))
        return (self.lat - dlat, self.lon - dlon, self.lat + dlat, self.lon + dlon)


REGIONS: dict[str, Region] = {
    "nyc": Region("nyc", "New York terminal area", 40.64, -73.78, 60, ("KJFK", "KLGA", "KEWR")),
    "sfo": Region("sfo", "San Francisco Bay", 37.62, -122.38, 60, ("KSFO", "KOAK", "KSJC")),
    "lax": Region("lax", "Los Angeles basin", 33.94, -118.41, 60, ("KLAX", "KBUR", "KLGB")),
    "ord": Region("ord", "Chicago", 41.98, -87.90, 60, ("KORD", "KMDW")),
    "atl": Region("atl", "Atlanta", 33.64, -84.43, 60, ("KATL",)),
    "dfw": Region("dfw", "Dallas-Fort Worth", 32.90, -97.04, 60, ("KDFW", "KDAL")),
    "lhr": Region("lhr", "London", 51.47, -0.46, 60, ("EGLL", "EGKK", "EGSS")),
    "fra": Region("fra", "Frankfurt", 50.03, 8.57, 60, ("EDDF",)),
    "ams": Region("ams", "Amsterdam", 52.31, 4.76, 60, ("EHAM",)),
    "dxb": Region("dxb", "Dubai", 25.25, 55.36, 60, ("OMDB", "OMDW")),
    "sin": Region("sin", "Singapore", 1.36, 103.99, 60, ("WSSS",)),
    "hnd": Region("hnd", "Tokyo", 35.55, 139.78, 60, ("RJTT", "RJAA")),
    # adsb.lol global feeds (not geographic): military-flagged, FAA LADD, and PIA-address traffic
    "mil": Region("mil", "adsb.lol global military-flagged", 0.0, 0.0, 0, endpoint="mil"),
    "ladd": Region("ladd", "adsb.lol FAA LADD programme aircraft", 0.0, 0.0, 0, endpoint="ladd"),
    "pia": Region("pia", "adsb.lol privacy ICAO address traffic", 0.0, 0.0, 0, endpoint="pia"),
}


def get_region(key: str) -> Region:
    try:
        return REGIONS[key.lower()]
    except KeyError as e:
        raise KeyError(f"Unknown region '{key}'. Known: {', '.join(REGIONS)}") from e


def parse_regions(spec: str, radius_nm: float | None = None) -> list[Region]:
    """'nyc,lhr' -> regions, optionally overriding the radius (adsb.lol allows up to 250 nm)."""
    import dataclasses

    regions = [get_region(k.strip()) for k in spec.split(",") if k.strip()]
    if radius_nm:
        regions = [dataclasses.replace(r, radius_nm=radius_nm) for r in regions]
    return regions


def bbox_region(spec: str, key: str = "bbox") -> Region:
    """'lamin,lomin,lamax,lomax' -> a Region with an exact bounding box."""
    lamin, lomin, lamax, lomax = (float(v) for v in spec.split(","))
    lat, lon = (lamin + lamax) / 2, (lomin + lomax) / 2
    half_diag_nm = 60.0 * math.hypot((lamax - lamin) / 2, ((lomax - lomin) / 2) * math.cos(math.radians(lat)))
    return Region(key, f"custom box {spec}", lat, lon, min(half_diag_nm, 250.0), (), (lamin, lomin, lamax, lomax))


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("AERO_PROVIDER", "adsblol")
    region: str = os.getenv("AERO_REGION", "nyc")
    poll_interval: float = float(os.getenv("AERO_POLL_INTERVAL", "15"))
    opensky_client_id: str | None = os.getenv("OPENSKY_CLIENT_ID") or None
    opensky_client_secret: str | None = os.getenv("OPENSKY_CLIENT_SECRET") or None
    user_agent: str = "aero-audit/0.1 (research; passive ADS-B auditing)"


settings = Settings()
