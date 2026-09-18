"""CelesTrak SATCAT: the public satellite catalogue with names, types, owners, orbit and decay dates. Keyless.

This is the open replacement for two things people reach for Space-Track for: object identity (what
is NORAD 48274, who owns it, payload or debris) and decay records (DECAY_DATE per object). One CSV,
about 60,000 rows, refreshed daily; cached with a provenance sidecar and re-read from disk.
CelesTrak asks to be cited (Dr. T.S. Kelso); the data carries no redistribution restriction.

Findings: ORB-008 element set in use for an object the catalogue records as decayed (data quality).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..audit.findings import Category, Finding, Severity
from ..config import settings

URL = "https://celestrak.org/pub/satcat.csv"
CACHE_DIR = Path("data/space/satcat")
MAX_AGE_S = 24 * 3600.0


async def fetch(dest_dir: str | Path = CACHE_DIR) -> Path:
    """Download the catalogue (a few MB) with a provenance sidecar; keyless, once a day is plenty."""
    from ..ingest.http import using_curl

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    text = ""
    if not using_curl():
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(URL, headers={"User-Agent": settings.user_agent})
                r.raise_for_status()
                text = r.text
        except (httpx.ConnectError, httpx.ConnectTimeout):
            text = ""
    if not text:
        from .orbital import _curl_text

        text = await _curl_text(URL)
    if not text.startswith("OBJECT_NAME,"):
        raise ValueError("unexpected SATCAT response (no CSV header)")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    p = dest / f"satcat_{stamp}.csv"
    p.write_text(text)
    p.with_suffix(".csv.provenance.json").write_text(json.dumps({"source": URL, "fetched_at": stamp, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                                                  "rows": text.count("\n") - 1, "terms": "CelesTrak SATCAT, cite CelesTrak (Dr. T.S. Kelso); no redistribution restriction"}, indent=1))
    return p


def latest(dest_dir: str | Path = CACHE_DIR) -> Path | None:
    files = sorted(Path(dest_dir).glob("satcat_*.csv")) if Path(dest_dir).is_dir() else []
    return files[-1] if files else None


def load(path: str | Path | None = None) -> dict[int, dict[str, Any]]:
    """NORAD id -> record. With no path, the newest cached file; an empty dict when nothing is cached."""
    p = Path(path) if path else latest()
    if p is None or not Path(p).is_file():
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in csv.DictReader(io.StringIO(Path(p).read_text())):
        try:
            nid = int(row["NORAD_CAT_ID"])
        except (KeyError, ValueError):
            continue
        out[nid] = {"name": row.get("OBJECT_NAME"), "intl": row.get("OBJECT_ID"), "type": row.get("OBJECT_TYPE"), "status": row.get("OPS_STATUS_CODE"), "owner": row.get("OWNER"),
                    "launch_date": row.get("LAUNCH_DATE"), "launch_site": row.get("LAUNCH_SITE"), "decay_date": row.get("DECAY_DATE") or None, "period_min": _f(row.get("PERIOD")), "inclination_deg": _f(row.get("INCLINATION")),
                    "apogee_km": _f(row.get("APOGEE")), "perigee_km": _f(row.get("PERIGEE")), "rcs_m2": _f(row.get("RCS")), "orbit_type": row.get("ORBIT_TYPE")}
    return out


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def enrich(norad_ids: list[int], cat: dict[int, dict[str, Any]] | None = None) -> dict[int, dict[str, Any]]:
    cat = cat if cat is not None else load()
    return {n: cat.get(int(n), {}) for n in norad_ids}


def recent_decays(days: float = 30.0, cat: dict[int, dict[str, Any]] | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    cat = cat if cat is not None else load()
    ts = (now or datetime.now(UTC)).timestamp()
    out = []
    for nid, r in cat.items():
        d = r.get("decay_date")
        if not d:
            continue
        try:
            dts = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        if 0 <= ts - dts <= days * 86400:
            out.append({"norad": nid, **r})
    return sorted(out, key=lambda r: r["decay_date"], reverse=True)


def findings_for_elements(norad_ids: list[int], cat: dict[int, dict[str, Any]] | None = None, stream: str = "elements", now: datetime | None = None) -> list[Finding]:
    """ORB-008: an element set still in the screen for an object the catalogue says has decayed."""
    cat = cat if cat is not None else load()
    ts = (now or datetime.now(UTC)).timestamp()
    out = []
    for nid in norad_ids:
        r = cat.get(int(nid))
        if r and r.get("decay_date"):
            out.append(Finding(rule_id="ORB-008", title=f"{r.get('name') or nid}: catalogued as decayed on {r['decay_date']} but still in the element set", severity=Severity.LOW,
                               category=Category.DATA_QUALITY, callsign=r.get("name"), ts=ts, evidence={"stream": stream, "norad": int(nid), "decay_date": r["decay_date"], "type": r.get("type")},
                               controls=["CCSDS 502.0-B"], recommendation="Drop the object from the screen; a decayed object's elements are stale by definition."))
    return out


def summary(cat: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    cat = cat if cat is not None else load()
    by_type: dict[str, int] = {}
    on_orbit = 0
    for r in cat.values():
        by_type[r.get("type") or "?"] = by_type.get(r.get("type") or "?", 0) + 1
        if not r.get("decay_date"):
            on_orbit += 1
    p = latest()
    return {"objects": len(cat), "on_orbit": on_orbit, "decayed": len(cat) - on_orbit, "by_type": by_type, "file": p.name if p else None,
            "age_h": round((time.time() - p.stat().st_mtime) / 3600, 1) if p else None}


__all__ = ["CACHE_DIR", "MAX_AGE_S", "URL", "enrich", "fetch", "findings_for_elements", "latest", "load", "recent_decays", "summary"]
