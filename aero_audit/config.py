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
    # more US hubs so a round-robin covers the contiguous states at 250 nm
    "sea": Region("sea", "Seattle", 47.45, -122.31, 60, ("KSEA", "KPDX")),
    "den": Region("den", "Denver", 39.86, -104.67, 60, ("KDEN",)),
    "phx": Region("phx", "Phoenix", 33.43, -112.01, 60, ("KPHX",)),
    "slc": Region("slc", "Salt Lake City", 40.79, -111.98, 60, ("KSLC",)),
    "iah": Region("iah", "Houston", 29.98, -95.34, 60, ("KIAH", "KHOU")),
    "msp": Region("msp", "Minneapolis", 44.88, -93.22, 60, ("KMSP",)),
    "mci": Region("mci", "Kansas City", 39.30, -94.71, 60, ("KMCI",)),
    "mia": Region("mia", "Miami", 25.79, -80.29, 60, ("KMIA", "KFLL")),
    "dca": Region("dca", "Washington DC", 38.85, -77.04, 60, ("KDCA", "KIAD", "KBWI")),
    "bos": Region("bos", "Boston", 42.36, -71.01, 60, ("KBOS",)),
    # whole-country / continent boxes (best with OpenSky; adsb.lol point queries cap at 250 nm)
    "conus": Region("conus", "USA: contiguous states in one box", 38.0, -96.0, 250, ("KJFK", "KORD", "KLAX", "KDFW", "KATL"),
                    custom_bbox=(24.0, -125.0, 50.0, -66.0)),
    "americas": Region("americas", "The Americas in one box", 10.0, -90.0, 250, (), custom_bbox=(-56.0, -170.0, 72.0, -30.0)),
    # adsb.lol global feeds (not geographic): military-flagged, FAA LADD, and PIA-address traffic
    "mil": Region("mil", "adsb.lol global military-flagged", 0.0, 0.0, 0, endpoint="mil"),
    "ladd": Region("ladd", "adsb.lol FAA LADD programme aircraft", 0.0, 0.0, 0, endpoint="ladd"),
    "pia": Region("pia", "adsb.lol privacy ICAO address traffic", 0.0, 0.0, 0, endpoint="pia"),
}


# Named groups expand to several regions for round-robin polling (adsb.lol has no daily quota but
# caps a point query at 250 nm; 15 hubs at 250 nm cover the contiguous United States).
GROUPS: dict[str, tuple[str, ...]] = {
    "usa-hubs": ("sea", "sfo", "lax", "phx", "slc", "den", "dfw", "iah", "msp", "ord", "mci", "atl", "mia", "dca", "nyc"),
    "world-hubs": ("nyc", "ord", "lax", "lhr", "fra", "dxb", "sin", "hnd"),
}
GROUP_NAMES = {"usa-hubs": "USA: 15 hubs round-robin (250 nm each)", "world-hubs": "World: 8 major hubs round-robin"}


def get_region(key: str) -> Region:
    try:
        return REGIONS[key.lower()]
    except KeyError as e:
        raise KeyError(f"Unknown region '{key}'. Known: {', '.join(REGIONS)}") from e


def parse_regions(spec: str, radius_nm: float | None = None) -> list[Region]:
    """'nyc,lhr' -> regions, optionally overriding the radius (adsb.lol allows up to 250 nm)."""
    import dataclasses

    keys: list[str] = []
    grouped = False
    for k in (x.strip().lower() for x in spec.split(",") if x.strip()):
        if k in GROUPS:
            keys.extend(GROUPS[k])
            grouped = True
        else:
            keys.append(k)
    regions = [get_region(k) for k in keys]
    radius = radius_nm or (250.0 if grouped else None)
    if radius:
        regions = [dataclasses.replace(r, radius_nm=radius) for r in regions]
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
