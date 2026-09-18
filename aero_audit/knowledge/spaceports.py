"""Launch, landing and recovery sites with coordinates: the ground truth that ties a launch record, a
space-operations TFR, the SATCAT launch-site code and the airports next door to one place.

Coordinates are site reference points to ~0.01 degree, enough for "which spaceport is this pad" and
"which airports sit within 50 nm", not for surveying. `satcat_site` is CelesTrak's SATCAT
LAUNCH_SITE code where it is known, so objects catalogued from a launch can be matched to the site.
`kind` is vertical (orbital pads), horizontal (runway-launched or landed vehicles), reentry (capsule
recovery ranges and landing runways) or range (experimental and sounding-rocket ranges under
14 CFR 91.143 TFRs). Licensing notes are descriptive; the FAA's Office of Commercial Space
Transportation is the authority on which sites hold a licence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .airports import AIRPORTS, Airport


@dataclass(frozen=True)
class Spaceport:
    code: str
    name: str
    country: str
    lat: float
    lon: float
    kind: str  # vertical | horizontal | reentry | range
    satcat_site: str | None = None
    note: str = ""


_ROWS = [
    # code, name, country, lat, lon, kind, satcat_site, note
    ("CCSFS", "Cape Canaveral Space Force Station", "US", 28.49, -80.57, "vertical", "AFETR", "SLC-40, SLC-41, SLC-37, SLC-46; Eastern Range"),
    ("KSC", "Kennedy Space Center", "US", 28.61, -80.60, "vertical", "AFETR", "LC-39A, LC-39B; Shuttle Landing Facility for reentry"),
    ("VSFB", "Vandenberg Space Force Base", "US", 34.74, -120.57, "vertical", "AFWTR", "SLC-4E, SLC-6, SLC-2W; Western Range"),
    ("WFF", "Wallops Flight Facility / Mid-Atlantic Regional Spaceport", "US", 37.84, -75.48, "vertical", "WLPIS", "Pad 0A, 0B, 0C; sounding rockets"),
    ("PSCA", "Pacific Spaceport Complex Alaska (Kodiak)", "US", 57.44, -152.34, "vertical", "KODAK", "Alaska Aerospace"),
    ("SPAM", "Spaceport America", "US", 32.99, -106.97, "horizontal", None, "Virgin Galactic; vertical pads for suborbital"),
    ("MHV", "Mojave Air and Space Port", "US", 35.06, -118.15, "horizontal", None, "first FAA-licensed inland spaceport"),
    ("CECIL", "Cecil Spaceport (Jacksonville)", "US", 30.22, -81.88, "horizontal", None, ""),
    ("HOUSP", "Houston Spaceport (Ellington)", "US", 29.61, -95.16, "horizontal", None, ""),
    ("OKSP", "Oklahoma Air and Space Port (Burns Flat)", "US", 35.34, -99.20, "horizontal", None, ""),
    ("MAF", "Midland International Air and Space Port", "US", 31.94, -102.20, "horizontal", None, ""),
    ("CASP", "Colorado Air and Space Port", "US", 39.79, -104.54, "horizontal", None, ""),
    ("STARB", "Starbase (Boca Chica)", "US", 26.00, -97.16, "vertical", None, "SpaceX Starship; launch and return"),
    ("LSONE", "Launch Site One (Corn Ranch, Van Horn)", "US", 31.42, -104.76, "vertical", None, "Blue Origin New Shepard; suborbital, capsule and booster return"),
    ("BLKRK", "Black Rock Desert launch area", "US", 40.88, -119.04, "range", None, "experimental and high-power rocketry under 91.143 TFRs"),
    ("PFRR", "Poker Flat Research Range", "US", 65.13, -147.48, "range", None, "sounding rockets"),
    ("UTTR", "Utah Test and Training Range", "US", 40.50, -113.50, "reentry", None, "sample-return capsule recoveries (Stardust, Genesis, OSIRIS-REx)"),
    ("EDW", "Edwards Air Force Base", "US", 34.91, -117.88, "reentry", None, "runway landings (Shuttle, X-37B)"),
    ("TYMSC", "Baikonur Cosmodrome", "KZ", 45.92, 63.34, "vertical", "TYMSC", ""),
    ("PLMSC", "Plesetsk Cosmodrome", "RU", 62.93, 40.58, "vertical", "PLMSC", ""),
    ("VOSTO", "Vostochny Cosmodrome", "RU", 51.88, 128.33, "vertical", "VOSTO", ""),
    ("CSG", "Guiana Space Centre (Kourou)", "GF", 5.24, -52.77, "vertical", "FRGUI", "ELA-4, ELV, ELS"),
    ("TNSC", "Tanegashima Space Center", "JP", 30.40, 130.97, "vertical", "TANSC", ""),
    ("USC", "Uchinoura Space Center", "JP", 31.25, 131.08, "vertical", "KSCUT", ""),
    ("SDSC", "Satish Dhawan Space Centre (Sriharikota)", "IN", 13.72, 80.23, "vertical", "SRILR", ""),
    ("JSLC", "Jiuquan Satellite Launch Center", "CN", 40.96, 100.29, "vertical", "JSC", ""),
    ("XSLC", "Xichang Satellite Launch Center", "CN", 28.25, 102.03, "vertical", "XICLF", ""),
    ("TSLC", "Taiyuan Satellite Launch Center", "CN", 38.85, 111.61, "vertical", "TAISC", ""),
    ("WSLS", "Wenchang Space Launch Site", "CN", 19.61, 110.95, "vertical", "WENCH", ""),
    ("NARO", "Naro Space Center", "KR", 34.43, 127.54, "vertical", "NSC", ""),
    ("ANDOY", "Andøya Spaceport", "NO", 69.29, 16.02, "vertical", "ANDOY", "sounding rockets and small orbital"),
    ("ESRAN", "Esrange Space Center", "SE", 67.89, 21.10, "range", "ESRAN", "sounding rockets; orbital pad in preparation"),
    ("SAXA", "SaxaVord Spaceport (Unst)", "GB", 60.82, -0.77, "vertical", None, ""),
    ("CNWL", "Spaceport Cornwall (Newquay)", "GB", 50.44, -5.00, "horizontal", None, ""),
    ("ALCA", "Alcântara Launch Center", "BR", -2.37, -44.40, "vertical", None, ""),
    ("SEMLS", "Imam Khomeini Spaceport (Semnan)", "IR", 35.23, 53.92, "vertical", "SEMLS", ""),
    ("PALM", "Palmachim Airbase", "IL", 31.88, 34.68, "vertical", None, ""),
    ("SOHAE", "Sohae Satellite Launching Station", "KP", 39.66, 124.71, "vertical", None, ""),
    ("RLLB", "Rocket Lab Launch Complex 1 (Mahia)", "NZ", -39.26, 177.86, "vertical", "RLLB", ""),
    ("WHWAY", "Whalers Way Orbital Launch Complex", "AU", -34.94, 135.63, "vertical", None, ""),
]

SPACEPORTS: dict[str, Spaceport] = {r[0]: Spaceport(*r) for r in _ROWS}
SATCAT_SITES: dict[str, str] = {s.satcat_site: s.code for s in SPACEPORTS.values() if s.satcat_site}


def _nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 60.0
    dlon = (lon2 - lon1) * 60.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def nearest_spaceport(lat: float, lon: float, max_nm: float = 60.0) -> tuple[Spaceport, float] | None:
    best: tuple[Spaceport, float] | None = None
    for s in SPACEPORTS.values():
        d = _nm(lat, lon, s.lat, s.lon)
        if d <= max_nm and (best is None or d < best[1]):
            best = (s, d)
    return best


def airports_near(lat: float, lon: float, max_nm: float = 50.0) -> list[tuple[Airport, float]]:
    """Airports from the knowledge table within the radius, nearest first: the airspace neighbours of a pad."""
    rows = [(a, _nm(lat, lon, a.lat, a.lon)) for a in AIRPORTS.values()]
    return sorted([(a, round(d, 1)) for a, d in rows if d <= max_nm], key=lambda x: x[1])


__all__ = ["SATCAT_SITES", "SPACEPORTS", "Spaceport", "airports_near", "nearest_spaceport"]
