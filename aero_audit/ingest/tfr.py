"""FAA temporary flight restrictions (keyless, US Government public domain): the published airspace
side of every launch and reentry.

``tfr.faa.gov`` lists the active TFRs as JSON and serves each one as an XNOTAM XML document with the
merged geometry (a polygon of great-circle vertices, or a circle) and the vertical limits. Space
operations are issued under 14 CFR 91.143, so those are the ones the launch and reentry joins read;
the other types (hazards, VIP, security, air shows) are kept in the same product because the
traffic join works for any of them. Every product carries a provenance sidecar; the geometry is
stored in decimal degrees so the join never re-parses XML.

Passive only: the list and detail endpoints are read; nothing is ever submitted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

LIST_URL = "https://tfr.faa.gov/tfrapi/getTfrList"
DETAIL_URL = "https://tfr.faa.gov/download/detail_{gid}.xml"
CACHE_DIR = Path("data/airspace")
SPACE_TYPES = ("SPACE OPERATIONS",)
STALE_S = 6 * 3600.0
NM_PER_DEG = 60.0
FL_TO_FT = 100.0
_MAX_DETAILS = 40  # detail fetches per product; the space list is usually under ten


def _coord(text: str | None) -> float | None:
    """'41.12848197N' / '119.0425W' -> signed decimal degrees."""
    if not text:
        return None
    m = re.fullmatch(r"\s*([0-9.]+)\s*([NSEW])\s*", text)
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2) in "SW" else v


def _find_text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    el = node.find(f".//{tag}")
    return el.text.strip() if el is not None and el.text else None


def _alt_ft(node: ET.Element | None, which: str) -> float | None:
    """Vertical limit in feet; FL values are hundreds of feet; 'UNL' and missing values are None (unlimited)."""
    val = _find_text(node, f"valDistVer{which}")
    uom = (_find_text(node, f"uomDistVer{which}") or "FT").upper()
    if val is None:
        return None
    try:
        v = float(val)
    except ValueError:
        return None
    return v * FL_TO_FT if uom == "FL" else v


TZ_OFFSETS_H = {"UTC": 0, "GMT": 0, "Z": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10, "AST": -4, "ChST": 10}


def _utc(stamp: str | None, tz: str | None = "UTC") -> float | None:
    """'2026-09-20T14:00:00' in the document's codeTimeZone -> epoch. Space operations are issued in UTC; the US zone
    abbreviations cover the local-time TFRs; an unknown zone is read as UTC and flagged by the caller."""
    if not stamp:
        return None
    try:
        naive = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None
    return naive - TZ_OFFSETS_H.get((tz or "UTC").strip(), 0) * 3600.0


def parse_detail(xml_text: str, listing: dict[str, Any] | None = None) -> dict[str, Any]:
    """One XNOTAM document -> one feature: identity, times, vertical limits, and the merged geometry as a polygon
    ([[lat, lon], ...]) and/or a circle ({lat, lon, radius_nm}). Composite areas keep the merged polygon the FAA
    already resolved; a lone CIR vertex becomes the circle."""
    root = ET.fromstring(xml_text.lstrip("\ufeff"))
    not_ = root.find(".//Not")
    tfr = root.find(".//TfrNot")
    reg = tfr.find("codeType") if tfr is not None else None  # the regulation sits directly under TfrNot; deeper codeType values are shape kinds
    regulation = reg.text.strip() if reg is not None and reg.text else None
    area = root.find(".//abdMergedArea")
    if area is None:
        area = root.find(".//Abd")
    polygon: list[list[float]] = []
    circle: dict[str, float] | None = None
    if area is not None:
        for avx in area.findall("Avx"):
            lat, lon = _coord(_find_text(avx, "geoLat")), _coord(_find_text(avx, "geoLong"))
            if lat is None or lon is None:
                continue
            if (_find_text(avx, "codeType") or "").upper() == "CIR":
                r = _find_text(avx, "valRadiusArc")
                circle = {"lat": lat, "lon": lon, "radius_nm": float(r) if r else 0.0}
            else:
                polygon.append([lat, lon])
    if len(polygon) < 3:
        polygon = []
    tz = _find_text(not_, "codeTimeZone") or "UTC"
    tz_exp = _find_text(not_, "codeExpirationTimeZone") or tz
    feat = {
        "notam_id": _find_text(not_, "txtLocalName") or (listing or {}).get("notam_id"),
        "type": (listing or {}).get("type") or ("SPACE OPERATIONS" if regulation == "91.143" else regulation),
        "regulation": regulation,
        "facility": _find_text(not_, "codeFacility") or (listing or {}).get("facility"),
        "state": (listing or {}).get("state") or _find_text(not_, "txtNameUSState"),
        "place": _find_text(not_, "txtNameCity"),
        "purpose": _find_text(not_, "txtDescrPurpose"),
        "description": (listing or {}).get("description"),
        "issued": _find_text(not_, "dateIssued"),
        "effective": _find_text(not_, "dateEffective"),
        "expire": _find_text(not_, "dateExpire"),
        "effective_ts": _utc(_find_text(not_, "dateEffective"), tz),
        "expire_ts": _utc(_find_text(not_, "dateExpire"), tz_exp),
        "time_zone": tz,
        "time_zone_assumed_utc": tz.strip() not in TZ_OFFSETS_H or tz_exp.strip() not in TZ_OFFSETS_H,
        "lower_ft": _alt_ft(tfr, "Lower"),
        "upper_ft": _alt_ft(tfr, "Upper"),
        "polygon": polygon,
        "circle": circle,
        "vertices": len(polygon),
    }
    if polygon:
        lats, lons = [p[0] for p in polygon], [p[1] for p in polygon]
        feat["centroid"] = [round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)]
    elif circle:
        feat["centroid"] = [circle["lat"], circle["lon"]]
    else:
        feat["centroid"] = None
    return feat


async def fetch(types: tuple[str, ...] | None = SPACE_TYPES, dest_dir: str | Path = CACHE_DIR, max_details: int = _MAX_DETAILS) -> Path:
    """The list, then one detail document per TFR of the requested types (None: every type). Listing rows whose
    detail cannot be fetched or parsed are kept without geometry and counted, so the product says what it lacks."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        r = await client.get(LIST_URL)
        r.raise_for_status()
        listing = r.json()
        wanted = [row for row in listing if types is None or (row.get("type") or "").upper() in {t.upper() for t in types}]
        features: list[dict[str, Any]] = []
        failed = 0
        for row in wanted[:max_details]:
            gid = str(row.get("gid") or row.get("notam_id") or "").replace("/", "_")
            try:
                d = await client.get(DETAIL_URL.format(gid=gid))
                d.raise_for_status()
                features.append(parse_detail(d.text, row))
            except (httpx.HTTPError, ET.ParseError, ValueError):
                failed += 1
                features.append({"notam_id": row.get("notam_id"), "type": row.get("type"), "facility": row.get("facility"), "state": row.get("state"),
                                 "description": row.get("description"), "polygon": [], "circle": None, "vertices": 0, "centroid": None, "detail_error": True})
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    payload = {"features": features, "fetched_at": stamp, "source": LIST_URL, "types": list(types) if types else None, "listed_total": len(listing),
               "listed_by_type": _count_types(listing), "detail_failures": failed, "truncated": max(0, len(wanted) - max_details)}
    text = json.dumps(payload, indent=1)
    p = dest / f"tfr_{stamp}.json"
    p.write_text(text)
    p.with_suffix(".json.provenance.json").write_text(json.dumps({"source": LIST_URL, "detail": DETAIL_URL, "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                                                   "terms": "FAA tfr.faa.gov: US Government work, public domain; NOTAM text is authoritative, this product is derived"}, indent=1))
    return p


def _count_types(listing: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in listing:
        t = row.get("type") or "?"
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items()))


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = sorted(Path(dest_dir).glob("tfr_*.json")) if Path(dest_dir).is_dir() else []
    files = [f for f in files if not f.name.endswith(".provenance.json")]
    return files[-1] if files else None


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _dist_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * NM_PER_DEG
    dlon = (lon2 - lon1) * NM_PER_DEG * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Even-odd ray casting in the lat/lon plane: TFRs are tens of miles across, so the planar test is exact enough."""
    inside = False
    n = len(polygon)
    for i in range(n):
        y1, x1 = polygon[i]
        y2, x2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_at:
                inside = not inside
    return inside


def inside(lat: float, lon: float, feature: dict[str, Any], alt_ft: float | None = None) -> bool:
    """Horizontally inside the geometry and, when an altitude is given and the TFR has limits, vertically inside too."""
    if alt_ft is not None:
        lo, hi = feature.get("lower_ft"), feature.get("upper_ft")
        if (lo is not None and alt_ft < lo) or (hi is not None and alt_ft > hi):
            return False
    poly = feature.get("polygon") or []
    if len(poly) >= 3 and point_in_polygon(lat, lon, poly):
        return True
    c = feature.get("circle")
    return bool(c) and _dist_nm(lat, lon, c["lat"], c["lon"]) <= c["radius_nm"]


def active(feature: dict[str, Any], ts: float) -> bool:
    e0, e1 = feature.get("effective_ts"), feature.get("expire_ts")
    return (e0 is None or ts >= e0) and (e1 is None or ts <= e1)


def summary(path: str | Path) -> dict[str, Any]:
    payload = load(path)
    feats = payload.get("features", [])
    return {"file": Path(path).name, "fetched_at": payload.get("fetched_at"), "features": len(feats), "with_geometry": sum(1 for f in feats if f.get("polygon") or f.get("circle")),
            "listed_total": payload.get("listed_total"), "listed_by_type": payload.get("listed_by_type"), "detail_failures": payload.get("detail_failures"),
            "rows": [{k: f.get(k) for k in ("notam_id", "type", "facility", "state", "place", "effective", "expire", "lower_ft", "upper_ft", "vertices", "centroid")} for f in feats]}


__all__ = ["CACHE_DIR", "DETAIL_URL", "LIST_URL", "SPACE_TYPES", "STALE_S", "TZ_OFFSETS_H", "active", "fetch", "inside", "latest", "load", "parse_detail", "point_in_polygon", "summary"]
