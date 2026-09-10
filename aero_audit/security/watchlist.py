"""Watchlist: addresses, callsign prefixes, or registrations that must always raise a finding.

Two uses: *detection* (known-bad or suspicious addresses seen in prior incidents) and
*protection* (sensitive flights whose appearance in reports must be restricted). The entry's
`mode` decides how the finding is labelled; reporting policy for protected entries belongs to
the consumer of the findings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..audit.findings import Category, Finding, Severity
from ..models import StateVector


@dataclass(frozen=True)
class WatchEntry:
    label: str
    reason: str
    icao24: str | None = None
    callsign_prefix: str | None = None
    registration: str | None = None
    severity: str = "high"
    mode: str = "detect"  # detect | protect

    def matches(self, sv: StateVector) -> bool:
        if self.icao24 and sv.icao24.lower() == self.icao24.lower():
            return True
        if self.callsign_prefix and (sv.callsign or "").strip().upper().startswith(self.callsign_prefix.upper()):
            return True
        return bool(self.registration and (sv.registration or "").upper() == self.registration.upper())


class Watchlist:
    def __init__(self, entries: list[WatchEntry] | None = None) -> None:
        self.entries = entries or []

    @classmethod
    def load(cls, path: str | Path) -> Watchlist:
        data = json.loads(Path(path).read_text())
        return cls([WatchEntry(**e) for e in data])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([asdict(e) for e in self.entries], indent=2))

    def check(self, sv: StateVector) -> list[Finding]:
        out: list[Finding] = []
        for e in self.entries:
            if e.matches(sv):
                out.append(
                    Finding(
                        rule_id="SEC-020",
                        title=f"Watchlist match ({e.mode}): {e.label}",
                        severity=Severity(e.severity),
                        category=Category.SECURITY,
                        icao24=sv.icao24,
                        callsign=(sv.callsign or "").strip() or None,
                        ts=sv.ts,
                        evidence={
                            "lat": sv.lat, "lon": sv.lon, "baro_alt_ft": sv.baro_alt_ft,
                            "position_source": sv.position_source, "feed": str(sv.source),
                            "reason": e.reason, "mode": e.mode, "registration": sv.registration,
                            "type": sv.aircraft_type,
                        },
                        controls=["Organisation watchlist policy", "ICAO Annex 17 (security programme)"],
                        recommendation="Follow the handling instructions attached to the watchlist entry.",
                    )
                )
        return out

    def __len__(self) -> int:
        return len(self.entries)
