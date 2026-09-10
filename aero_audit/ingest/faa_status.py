"""FAA National Airspace System status: ground stops, ground delay programs, closures, delays.

Public XML feed, no key: https://nasstatus.faa.gov/api/airport-status-information
Each entry names an airport by IATA code and a reason; we normalise the four list types into
one flat record so the Airports view can show 'why' next to the traffic it sees.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..config import settings
from . import http as _http
from .http import (
    get_json,  # noqa: F401  (kept for symmetry; XML fetched with the same client rules)
)

URL = "https://nasstatus.faa.gov/api/airport-status-information"
KINDS = {
    "Ground_Delay": "ground delay program", "Ground_Stop": "ground stop", "Program": "ground stop",
    "Airport": "closure", "Airport_Closure": "closure", "Delay": "arrival/departure delay",
}


def parse_status(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    out: list[dict[str, Any]] = []
    for el in root.iter():
        arpt = el.find("ARPT")
        if arpt is None or not (arpt.text or "").strip():
            continue
        kind = KINDS.get(el.tag, el.tag.lower())
        rec: dict[str, Any] = {"airport": arpt.text.strip().upper(), "kind": kind}
        for child in el:
            if child.tag == "ARPT":
                continue
            if child.tag == "Arrival_Departure":
                rec["direction"] = child.get("Type", "").lower()
                for c in child:
                    rec[c.tag.lower()] = (c.text or "").strip()
            elif len(child) == 0:
                rec[child.tag.lower()] = (child.text or "").strip()
        out.append(rec)
    upd = root.findtext("Update_Time") or ""
    return {"updated": upd, "entries": out}


async def _curl_text(url: str) -> str:
    import asyncio

    proc = await asyncio.create_subprocess_exec("curl", "-sS", "-m", "20", "-A", settings.user_agent, url,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise httpx.ConnectError(err.decode(errors="replace"))
    return out.decode(errors="replace")


async def fetch_status() -> dict[str, Any]:
    """Same transport policy as the JSON feeds: httpx unless curl is forced or has already been needed."""
    if _http._use_curl:
        return parse_status(await _curl_text(URL))
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.user_agent}) as c:
        try:
            r = await c.get(URL)
            r.raise_for_status()
            return parse_status(r.text)
        except (httpx.ConnectTimeout, httpx.ConnectError):
            _http._use_curl = True
            return parse_status(await _curl_text(URL))
