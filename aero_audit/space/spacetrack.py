"""Space-Track.org client: the authoritative public catalogue and the ``cdm_public`` conjunction
summaries, behind a free account. Credentials come from ``SPACETRACK_USER`` / ``SPACETRACK_PASS``
in the environment (never from arguments, never logged). Every call is rate-limited by the site
(roughly 30 requests a minute; 300 an hour), so the client caches to ``data/space/spacetrack/``.

Not exercised live in the test suite; the parsing and ledger paths are tested with fixtures.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

BASE = "https://www.space-track.org"
CACHE = Path("data/space/spacetrack")


class SpaceTrackError(RuntimeError):
    pass


def credentials() -> tuple[str, str]:
    user, pw = os.getenv("SPACETRACK_USER", ""), os.getenv("SPACETRACK_PASS", "")
    if not user or not pw:
        raise SpaceTrackError("set SPACETRACK_USER and SPACETRACK_PASS (free account at space-track.org); never pass them on the command line")
    return user, pw


class SpaceTrack:
    def __init__(self, client: httpx.Client | None = None, cache: Path = CACHE) -> None:
        self.client = client or httpx.Client(base_url=BASE, timeout=60, headers={"User-Agent": settings.user_agent}, follow_redirects=True)
        self.cache = cache
        self._logged_in = False

    def login(self) -> None:
        user, pw = credentials()
        r = self.client.post("/ajaxauth/login", data={"identity": user, "password": pw})
        if r.status_code != 200 or "Failed" in r.text[:200]:
            raise SpaceTrackError(f"login refused (HTTP {r.status_code})")
        self._logged_in = True

    def query(self, path: str, use_cache_s: float = 3600.0) -> list[dict[str, Any]]:
        """GET a basicspacedata query path (after /basicspacedata/query/), JSON format, cached."""
        self.cache.mkdir(parents=True, exist_ok=True)
        key = self.cache / (path.strip("/").replace("/", "_")[:150] + ".json")
        if key.is_file() and time.time() - key.stat().st_mtime < use_cache_s:
            return json.loads(key.read_text())
        if not self._logged_in:
            self.login()
        r = self.client.get(f"/basicspacedata/query/{path.strip('/')}/format/json")
        if r.status_code != 200:
            raise SpaceTrackError(f"HTTP {r.status_code} for {path}")
        rows = r.json()
        key.write_text(json.dumps(rows))
        key.with_suffix(".provenance.json").write_text(json.dumps({"source": f"{BASE}/basicspacedata/query/{path}", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                                     "rows": len(rows), "terms": "Space-Track user agreement; no redistribution of bulk data"}, indent=1))
        return rows

    def cdm_public(self, days: int = 7, min_pc: float = 1e-7) -> list[dict[str, Any]]:
        """Recent public conjunction summaries above a probability of collision."""
        return self.query(f"class/cdm_public/TCA/>now-{days}/PC/>{min_pc}/orderby/TCA asc")

    def gp(self, norad_ids: list[int]) -> list[dict[str, Any]]:
        ids = ",".join(str(int(n)) for n in norad_ids[:200])
        return self.query(f"class/gp/NORAD_CAT_ID/{ids}/orderby/NORAD_CAT_ID asc")


__all__ = ["BASE", "CACHE", "SpaceTrack", "SpaceTrackError", "credentials"]
