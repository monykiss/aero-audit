"""NOAA Aviation Weather Center METAR feed (no key). Weather is context for ops findings:
a holding pattern in a thunderstorm is expected; one in CAVOK conditions is a process smell."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .http import get_json

URL = "https://aviationweather.gov/api/data/metar"


async def fetch_metars(stations: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    if not stations:
        return []
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": settings.user_agent}) as c:
        return await get_json(c, URL, params={"ids": ",".join(stations), "format": "json"})


def summarize_metar(m: dict[str, Any]) -> str:
    wind = f"{m.get('wdir', '?')}/{m.get('wspd', '?')}kt"
    gust = f"G{m['wgst']}" if m.get("wgst") else ""
    return (
        f"{m.get('icaoId')}: {m.get('temp')}C wind {wind}{gust} vis {m.get('visib')}sm "
        f"cover {m.get('cover')} QNH {m.get('altim')} | {m.get('rawOb', '')}"
    )
