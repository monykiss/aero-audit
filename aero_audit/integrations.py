"""External services this programme can use, what each unlocks, and whether it is configured.

Credentials live only in the environment (a git-ignored .env is the local convention); nothing
here prints a value. Every integration has a keyless path or a stated reason it cannot, so the
tool degrades to "what is public" rather than failing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    env: tuple[str, ...]  # variables that must all be present
    signup: str
    unlocks: str
    keyless: str  # what works without it
    domains: tuple[str, ...]
    optional_env: tuple[str, ...] = ()

    def configured(self) -> bool:
        return all(os.getenv(v) for v in self.env) if self.env else True

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "env": list(self.env), "optional_env": list(self.optional_env), "signup": self.signup, "unlocks": self.unlocks,
                "keyless": self.keyless, "domains": list(self.domains), "configured": self.configured(), "required": bool(self.env)}


INTEGRATIONS: dict[str, Integration] = {i.key: i for i in (
    Integration("adsblol", "adsb.lol", (), "none", "Primary ADS-B feed (readsb JSON with NIC/NACp/SIL).", "fully keyless", ("air-surveillance", "air-operations", "uas-utm")),
    Integration("opensky", "OpenSky Network", ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"), "https://opensky-network.org (free account, then an API client under your profile)",
                "Higher request quota and the second feed for corroboration studies (ST-10).", "anonymous quota (a few hundred calls per day)", ("air-surveillance",)),
    Integration("celestrak", "CelesTrak", (), "none", "GP element sets for conjunction screening.", "fully keyless; be polite (cache for hours)", ("space-orbital",)),
    Integration("spacetrack", "Space-Track.org", ("SPACETRACK_USER", "SPACETRACK_PASS"), "https://www.space-track.org/auth/createAccount (free; approval takes a day or two)",
                "Public conjunction summaries (cdm_public), GP history, decay and TIP messages.", "none (CelesTrak covers elements)", ("space-orbital",)),
    Integration("nasa_api", "api.nasa.gov", (), "https://api.nasa.gov (instant key by email)", "DONKI space-weather notifications, Mars rover photos, APOD, EPIC at 1,000 requests per hour.",
                "DEMO_KEY (30 per hour, 50 per day); NASA image library and 3D resources need no key at all", ("space-assets", "space-environment"), ("NASA_API_KEY",)),
    Integration("swpc", "NOAA SWPC", (), "none", "Space weather scales, Kp, alerts.", "fully keyless", ("space-environment", "air-operations")),
    Integration("ll2", "The Space Devs Launch Library 2", (), "https://thespacedevs.com (paid tiers raise the limit)", "Launch windows and pads.", "15 requests per hour keyless", ("space-launch",)),
    Integration("github", "GitHub API", (), "https://github.com/settings/tokens (fine-grained, public repositories read-only)", "NASA-3D-Resources tree at 5,000 requests per hour and Dependabot/Scorecard checks.",
                "60 requests per hour anonymous", ("space-assets",), ("GITHUB_TOKEN",)),
    Integration("noaa_awc", "NOAA Aviation Weather Center", (), "none", "METAR/TAF for airport context.", "fully keyless", ("air-operations",)),
    Integration("faa_nas", "FAA NAS status", (), "none", "Airport programmes and delays.", "fully keyless", ("air-operations",)),
)}


PROBES: dict[str, tuple[str, str]] = {  # key -> (url, what a 200 proves); authenticated ones are handled in probe()
    "adsblol": ("https://api.adsb.lol/v2/lat/40.7/lon/-74/dist/5", "keyless feed answers"),
    "celestrak": ("https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle", "keyless element fetch answers"),
    "swpc": ("https://services.swpc.noaa.gov/products/noaa-scales.json", "keyless scales product answers"),
    "ll2": ("https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=1", "keyless launch list answers (15/h)"),
    "noaa_awc": ("https://aviationweather.gov/api/data/metar?ids=KJFK&format=json", "keyless METAR answers"),
    "faa_nas": ("https://nasstatus.faa.gov/api/airport-status-information", "keyless NAS status answers"),
    "github": ("https://api.github.com/rate_limit", "rate limit endpoint answers (token raises the quota)"),
    "nasa_api": ("https://api.nasa.gov/DONKI/notifications", "key (or DEMO_KEY) accepted by the DONKI endpoint the tool uses"),
}


def probe(get: Any = None, timeout: float = 30.0) -> list[dict[str, Any]]:
    """One harmless read per service, authenticated where credentials exist; reports ok / status without printing any value.
    ``get(url, headers, params, auth)`` may be injected for tests; the default uses httpx with the curl fallback disabled."""
    import httpx

    from .config import settings

    def default_get(url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None, auth: Any = None) -> tuple[int, str]:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as c:  # feeds refuse anonymous agents
            r = c.get(url, headers=headers, params=params, auth=auth)
            return r.status_code, r.text[:200]

    get = get or default_get
    rows = []
    for key, integ in INTEGRATIONS.items():
        row: dict[str, Any] = {"key": key, "name": integ.name, "configured": integ.configured(), "required": bool(integ.env)}
        try:
            if key == "spacetrack":
                if not integ.configured():
                    row.update(ok=None, detail="not configured: set SPACETRACK_USER / SPACETRACK_PASS")
                else:
                    from .space.spacetrack import SpaceTrack

                    st = SpaceTrack()
                    st.login()
                    n = len(st.query("class/boxscore/limit/1", use_cache_s=0.0))
                    row.update(ok=True, detail=f"login accepted; boxscore query returned {n} row(s)")
            elif key == "opensky":
                if not integ.configured():
                    row.update(ok=None, detail="not configured: anonymous quota applies")
                else:
                    import asyncio

                    from .ingest.opensky import OpenSkyProvider

                    async def tok() -> bool:
                        c = OpenSkyProvider()
                        try:
                            h = await c._auth_headers()
                            return bool(h.get("Authorization"))
                        finally:
                            await c.aclose()

                    row.update(ok=asyncio.run(tok()), detail="OAuth2 client credentials accepted")
            elif key == "nasa_api":
                k = os.getenv("NASA_API_KEY", "").strip() or "DEMO_KEY"
                today = time.strftime("%Y-%m-%d", time.gmtime())
                code, _ = get(PROBES[key][0], None, {"api_key": k, "startDate": today, "endDate": today, "type": "all"}, None)
                row.update(ok=code == 200, detail=f"HTTP {code} with {'your key' if k != 'DEMO_KEY' else 'DEMO_KEY'}")
            elif key == "github":
                tokv = os.getenv("GITHUB_TOKEN", "").strip()
                code, _body = get(PROBES[key][0], {"Authorization": f"Bearer {tokv}"} if tokv else None, None, None)
                row.update(ok=code == 200, detail=f"HTTP {code} ({'token' if tokv else 'anonymous'})")
            elif key in PROBES:
                code, _ = get(PROBES[key][0], None, None, None)
                row.update(ok=code == 200, detail=f"HTTP {code}: {PROBES[key][1]}")
            else:
                row.update(ok=None, detail="no probe defined")
        except Exception as e:  # noqa: BLE001 - a probe reports, never raises
            row.update(ok=False, detail=f"{type(e).__name__}: {str(e)[:120]}")
        rows.append(row)
    return rows


def status() -> list[dict[str, Any]]:
    return [i.to_dict() for i in INTEGRATIONS.values()]


def missing() -> list[str]:
    return [i.key for i in INTEGRATIONS.values() if i.env and not i.configured()]


__all__ = ["INTEGRATIONS", "PROBES", "Integration", "missing", "probe", "status"]
