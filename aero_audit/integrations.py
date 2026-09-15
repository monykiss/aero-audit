"""External services this programme can use, what each unlocks, and whether it is configured.

Credentials live only in the environment (a git-ignored .env is the local convention); nothing
here prints a value. Every integration has a keyless path or a stated reason it cannot, so the
tool degrades to "what is public" rather than failing.
"""

from __future__ import annotations

import os
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


def status() -> list[dict[str, Any]]:
    return [i.to_dict() for i in INTEGRATIONS.values()]


def missing() -> list[str]:
    return [i.key for i in INTEGRATIONS.values() if i.env and not i.configured()]


__all__ = ["INTEGRATIONS", "Integration", "missing", "status"]
