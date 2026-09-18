"""NASA DONKI space-weather notifications (api.nasa.gov), the second opinion next to NOAA SWPC.

DONKI publishes the notifications the Community Coordinated Modeling Center sends out: geomagnetic
storms (GST), flares (FLR), solar energetic particles (SEP), CMEs and radiation-belt enhancements.
With ``NASA_API_KEY`` set the quota is 1,000 requests per hour; without it ``DEMO_KEY`` gives 30
per hour, which is plenty for one poll per schedule interval. The cross-check pairs the SWPC
assessment's ICAO conditions with DONKI notifications of the matching type inside a window: agreement
raises confidence, a DONKI notification with no SWPC condition (or the reverse) is listed, never
turned into a finding, because the two products describe events differently.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..ingest.http import get_json

API = "https://api.nasa.gov/DONKI/notifications"
CACHE_DIR = Path("data/space/donki")
WINDOW_S = 48 * 3600.0
# SWPC scale -> DONKI message types that describe the same physics
MATCH = {"G": ("GST", "CME"), "R": ("FLR",), "S": ("SEP", "RBE")}


def api_key() -> tuple[str, bool]:
    key = os.getenv("NASA_API_KEY", "").strip()
    return (key, True) if key else ("DEMO_KEY", False)


async def fetch(days: int = 7, dest_dir: str | Path = CACHE_DIR) -> Path:
    key, own = api_key()
    end = time.strftime("%Y-%m-%d", time.gmtime())
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    async with httpx.AsyncClient(timeout=30) as client:  # the key travels in a header (api.data.gov accepts X-Api-Key), never in the URL or the cache
        rows = await get_json(client, API, {"startDate": start, "endDate": end, "type": "all"}, {"User-Agent": settings.user_agent, "X-Api-Key": key})
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    payload = {"notifications": parse(rows if isinstance(rows, list) else []), "fetched_at": stamp, "source": API, "days": days, "own_key": own}
    text = json.dumps(payload, indent=1)
    p = dest / f"donki_{stamp}.json"
    p.write_text(text)
    p.with_suffix(".json.provenance.json").write_text(json.dumps({"source": API, "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(), "own_key": own,
                                                                   "terms": "NASA open data; DEMO_KEY is rate-limited to 30 requests per hour"}, indent=1))
    return p


def parse(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        body = str(r.get("messageBody") or "")
        first = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("##")), "")
        out.append({"id": r.get("messageID"), "type": r.get("messageType"), "issued": r.get("messageIssueTime"), "url": r.get("messageURL"), "headline": first[:200]})
    return out


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = [f for f in sorted(Path(dest_dir).glob("donki_*.json")) if not f.name.endswith(".provenance.json")] if Path(dest_dir).is_dir() else []
    return files[-1] if files else None


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    import calendar

    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return calendar.timegm(time.strptime(iso, fmt))
        except ValueError:
            continue
    return None


def crosscheck(swx_summary: dict[str, Any], notifications: list[dict[str, Any]], now: float | None = None, window_s: float = WINDOW_S) -> dict[str, Any]:
    """Per SWPC effect: the ICAO condition SWPC reports and the DONKI notifications of matching type within the window."""
    ts = now if now is not None else time.time()
    recent = [n for n in notifications if (t := _ts(n.get("issued"))) is not None and ts - t <= window_s]
    conditions = swx_summary.get("icao_advisory_conditions", {})
    effects = {}
    for scale, types in MATCH.items():
        hits = [n for n in recent if n.get("type") in types]
        cond = conditions.get(scale)
        effects[scale] = {"swpc_condition": cond, "donki_notifications": len(hits), "types": sorted({n["type"] for n in hits}),
                          "agreement": "both" if (cond and hits) else ("swpc-only" if cond else ("donki-only" if hits else "quiet")),
                          "latest": max((n.get("issued") or "" for n in hits), default=None)}
    return {"window_h": window_s / 3600, "recent_notifications": len(recent), "effects": effects,
            "note": "DONKI notifications and NOAA scales describe events differently; disagreement is listed, not scored"}


__all__ = ["API", "CACHE_DIR", "MATCH", "WINDOW_S", "api_key", "crosscheck", "fetch", "latest", "parse"]
