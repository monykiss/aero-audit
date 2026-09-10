"""OpenSky Network REST API. Anonymous access works (rate-limited); OAuth2 raises limits."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import FPM_PER_MPS, FT_PER_M, KT_PER_MPS, Region, settings
from ..models import Batch, Source, StateVector
from .http import get_json

STATES_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
POSITION_SOURCE = {0: "adsb", 1: "asterix", 2: "mlat", 3: "flarm"}


def _f(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def map_row(row: list[Any], now_s: float) -> StateVector:
    baro_m, geo_m, vel, vr = _f(row[7]), _f(row[13]), _f(row[9]), _f(row[11])
    on_ground = bool(row[8])
    return StateVector(
        icao24=str(row[0]).lower(),
        callsign=row[1] or None,
        ts=float(row[3] or row[4] or now_s),
        lat=_f(row[6]),
        lon=_f(row[5]),
        baro_alt_ft=baro_m * FT_PER_M if baro_m is not None else None,  # keep field elevation; SLC is 4,227 ft
        geo_alt_ft=geo_m * FT_PER_M if geo_m is not None else None,
        gs_kt=vel * KT_PER_MPS if vel is not None else None,
        track_deg=_f(row[10]),
        vrate_fpm=vr * FPM_PER_MPS if vr is not None else None,
        squawk=row[14],
        on_ground=on_ground,
        position_source=POSITION_SOURCE.get(row[16]) if len(row) > 16 else None,
        source=Source.OPENSKY,
        raw={"row": row},
    )


class OpenSkyProvider:
    name = "opensky"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.user_agent})
        self._token: str | None = None
        self._token_exp = 0.0

    async def _auth_headers(self) -> dict[str, str]:
        cid, sec = settings.opensky_client_id, settings.opensky_client_secret
        if not (cid and sec):
            return {}
        if self._token and time.time() < self._token_exp - 30:
            return {"Authorization": f"Bearer {self._token}"}
        r = await self._client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec},
        )
        r.raise_for_status()
        tok = r.json()
        self._token = tok["access_token"]
        self._token_exp = time.time() + float(tok.get("expires_in", 1800))
        return {"Authorization": f"Bearer {self._token}"}

    async def fetch(self, region: Region) -> Batch:
        if region.endpoint:
            raise ValueError(f"Region '{region.key}' is an adsb.lol-only feed; use --provider adsblol")
        lamin, lomin, lamax, lomax = region.bbox()
        params = {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax, "extended": 1}
        payload = await get_json(self._client, STATES_URL, params=params, headers=await self._auth_headers())
        now_s = float(payload.get("time") or time.time())
        states = [map_row(row, now_s) for row in (payload.get("states") or [])]
        return Batch(ts=now_s, provider=self.name, region=region.key, states=states)

    async def aclose(self) -> None:
        await self._client.aclose()
