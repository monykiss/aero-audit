"""adsb.lol community feed (readsb JSON). No API key; please poll politely (>= 5 s)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import Region, settings
from ..models import Batch, Source, StateVector
from .http import get_json

BASE = "https://api.adsb.lol/v2"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def map_aircraft(ac: dict[str, Any], now_s: float) -> StateVector:
    on_ground = ac.get("alt_baro") == "ground"
    seen_pos = _num(ac.get("seen_pos")) or 0.0
    src_type = str(ac.get("type", ""))
    pos_src = "adsb" if src_type.startswith("adsb") else src_type or None
    return StateVector(
        icao24=str(ac.get("hex", "")).lower(),
        callsign=(ac.get("flight") or None),
        registration=ac.get("r"),
        aircraft_type=ac.get("t"),
        ts=now_s - seen_pos,
        lat=_num(ac.get("lat")),
        lon=_num(ac.get("lon")),
        baro_alt_ft=None if on_ground else _num(ac.get("alt_baro")),  # "ground" carries no altitude; 0 ft would be a lie at high-elevation airports
        geo_alt_ft=_num(ac.get("alt_geom")),
        gs_kt=_num(ac.get("gs")),
        track_deg=_num(ac.get("track")),
        vrate_fpm=_num(ac.get("baro_rate")) or _num(ac.get("geom_rate")),
        squawk=ac.get("squawk"),
        on_ground=on_ground,
        emergency=ac.get("emergency"),
        selected_alt_ft=_num(ac.get("nav_altitude_mcp")),
        nic=int(ac["nic"]) if isinstance(ac.get("nic"), int) else None,
        nac_p=int(ac["nac_p"]) if isinstance(ac.get("nac_p"), int) else None,
        sil=int(ac["sil"]) if isinstance(ac.get("sil"), int) else None,
        position_source=pos_src,
        source=Source.ADSBLOL,
        raw=ac,
    )


class AdsbLolProvider:
    name = "adsblol"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=15, headers={"User-Agent": settings.user_agent, "Accept": "application/json"}
        )

    async def fetch(self, region: Region) -> Batch:
        if region.endpoint:
            payload = await get_json(self._client, f"{BASE}/{region.endpoint}")
        else:
            radius = min(region.radius_nm, 250)
            payload = await get_json(self._client, f"{BASE}/point/{region.lat}/{region.lon}/{radius}")
        now_s = (payload.get("now") or time.time() * 1000) / 1000.0
        states = [map_aircraft(ac, now_s) for ac in payload.get("ac", []) if ac.get("hex")]
        return Batch(ts=now_s, provider=self.name, region=region.key, states=states)

    async def aclose(self) -> None:
        await self._client.aclose()
