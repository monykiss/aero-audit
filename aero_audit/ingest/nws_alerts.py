"""Live crisis extents from the National Weather Service alerts API (keyless, US Government public domain).

``api.weather.gov/alerts/active`` returns GeoJSON features with the warning polygon for flood, tornado,
hurricane, wildfire-related and other events. Saved as a FeatureCollection with a provenance sidecar,
it is exactly the input the crisis-overlay study (ST-11, airports inside an extent) expects, so the
study runs on a real extent whenever there is one, and the sample export otherwise.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from .http import get_json

API = "https://api.weather.gov/alerts/active"
CACHE_DIR = Path("data/crisis")
DEFAULT_EVENTS = ("Flood Warning", "Flash Flood Warning", "Tornado Warning", "Hurricane Warning", "Red Flag Warning")


async def fetch(events: tuple[str, ...] = DEFAULT_EVENTS, dest_dir: str | Path = CACHE_DIR, area: str | None = None) -> Path:
    """One request per event type; only features with geometry are kept (zone-based alerts without a polygon are counted)."""
    features: list[dict[str, Any]] = []
    skipped = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for ev in events:
            params = {"event": ev, "status": "actual"}
            if area:
                params["area"] = area
            payload = await get_json(client, API, params, {"User-Agent": settings.user_agent, "Accept": "application/geo+json"})
            for f in payload.get("features", []):
                if f.get("geometry"):
                    p = f.get("properties", {})
                    features.append({"type": "Feature", "geometry": f["geometry"],
                                     "properties": {k: p.get(k) for k in ("id", "event", "severity", "certainty", "urgency", "areaDesc", "headline", "onset", "expires", "senderName")}
                                     | {"name": f"{p.get('event')}: {str(p.get('areaDesc') or '')[:48]}"}})
                else:
                    skipped += 1
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features, "properties": {"source": API, "events": list(events), "fetched_at": stamp, "without_geometry": skipped, "area": area}}
    text = json.dumps(fc)
    p = dest / f"nws_alerts_{stamp}.geojson"
    p.write_text(text)
    p.with_suffix(".geojson.provenance.json").write_text(json.dumps({"source": API, "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(), "features": len(features),
                                                                      "terms": "NWS alerts are US Government works in the public domain; cite NOAA/NWS"}, indent=1))
    return p


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = [f for f in sorted(Path(dest_dir).glob("nws_alerts_*.geojson"))] if Path(dest_dir).is_dir() else []
    return files[-1] if files else None


def summary(path: str | Path) -> dict[str, Any]:
    fc = json.loads(Path(path).read_text())
    feats = fc.get("features", [])
    by_event: dict[str, int] = {}
    for f in feats:
        ev = f.get("properties", {}).get("event") or "?"
        by_event[ev] = by_event.get(ev, 0) + 1
    return {"file": Path(path).name, "features": len(feats), "by_event": by_event, "fetched_at": fc.get("properties", {}).get("fetched_at"), "without_geometry": fc.get("properties", {}).get("without_geometry")}


__all__ = ["API", "CACHE_DIR", "DEFAULT_EVENTS", "fetch", "latest", "summary"]
