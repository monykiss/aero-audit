"""Per-aircraft trust ledger: a running score that findings erode and clean fixes restore.

This turns 'downgrade trust of this aircraft's positions' from a recommendation into a number
that downstream analytics can actually use. Scores live in [0, 1]; 1.0 is fully trusted.
"""

from __future__ import annotations

from collections import defaultdict

from ..audit.findings import Finding, Severity

PENALTY: dict[Severity, float] = {
    Severity.CRITICAL: 0.60,
    Severity.HIGH: 0.35,
    Severity.MEDIUM: 0.15,
    Severity.LOW: 0.05,
    Severity.INFO: 0.01,
}
# Data-quality findings speak about equipment, not intent; they erode trust more slowly.
CATEGORY_FACTOR = {"security": 1.0, "safety": 0.6, "ml": 0.5, "operations": 0.2, "data-quality": 0.4}


class TrustLedger:
    def __init__(self, recovery_per_clean_fix: float = 0.02, floor: float = 0.0) -> None:
        self.recovery = recovery_per_clean_fix
        self.floor = floor
        self._score: dict[str, float] = defaultdict(lambda: 1.0)
        self._hits: dict[str, int] = defaultdict(int)

    def score(self, icao24: str) -> float:
        return self._score[icao24]

    def penalize(self, finding: Finding) -> float:
        if not finding.icao24:
            return 1.0
        pen = PENALTY[finding.severity] * CATEGORY_FACTOR.get(finding.category.value, 0.5)
        self._score[finding.icao24] = max(self.floor, self._score[finding.icao24] - pen)
        self._hits[finding.icao24] += 1
        return self._score[finding.icao24]

    def observe_clean(self, icao24: str) -> float:
        if icao24 in self._score and self._score[icao24] < 1.0:
            self._score[icao24] = min(1.0, self._score[icao24] + self.recovery)
        return self._score[icao24]

    def low_trust(self, threshold: float = 0.5) -> list[tuple[str, float, int]]:
        rows = [(k, v, self._hits[k]) for k, v in self._score.items() if v < threshold]
        return sorted(rows, key=lambda r: r[1])

    def __len__(self) -> int:
        return len(self._score)
