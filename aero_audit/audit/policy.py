"""Risk-scoring policy: the one place that encodes the auditor's risk appetite.

Every accepted finding gets `risk_score()`; reports, alerts, and the register rank by it.

The default policy is an expected-value model:

    score = severity_weight
          x repeat_factor        1 + 0.5 * log2(repeat_count): persistence compounds, with diminishing returns
          x evidence_quality     security findings from MLAT/TIS-B positions are weaker spoofing evidence
          x rule_precision       measured by `aero evaluate` (injected scenarios on real traffic); default 1
    capped for ML findings at the MEDIUM weight so a model never outranks a HIGH hard rule.

Precision weights are read from models/evaluation.json when present, so re-running the
evaluation after a rule change re-calibrates the ranking without touching this file.
Invariants pinned by tests/test_policy.py: monotonic in severity, non-negative and finite,
repeats never lower a score, ML never exceeds the MEDIUM weight.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from .findings import SEVERITY_WEIGHT, Category, Finding, Severity

SOURCE_TRUST: dict[str | None, float] = {
    "adsb": 1.0,
    "asterix": 0.9,
    "mlat": 0.7,
    "tisb": 0.6,
    "adsc": 0.6,
    "flarm": 0.6,
    None: 0.5,
}
REPEAT_GAIN = 0.5
PRECISION_FLOOR = 0.2  # a rule with zero measured precision still keeps 20% weight (evidence, not proof)
ML_CAP = SEVERITY_WEIGHT[Severity.MEDIUM]
EVALUATION_PATH = Path(os.getenv("AERO_EVALUATION_PATH", "models/evaluation.json"))


def _load_precision(path: Path = EVALUATION_PATH) -> dict[str, float]:
    try:
        data = json.loads(path.read_text())
        return {k: float(v) for k, v in data.get("rule_precision", {}).items() if v is not None}
    except (OSError, ValueError):
        return {}


RULE_PRECISION: dict[str, float] = _load_precision()


@dataclass(frozen=True)
class ScoringContext:
    repeat_count: int
    source_trust: float
    seconds_since_first: float


def repeat_factor(repeat_count: int) -> float:
    return 1.0 + REPEAT_GAIN * math.log2(max(1, repeat_count))


def evidence_quality(finding: Finding, ctx: ScoringContext) -> float:
    if finding.category is Category.SECURITY:
        return 0.6 + 0.4 * max(0.0, min(1.0, ctx.source_trust))
    return 1.0


def precision_weight(rule_id: str) -> float:
    return max(PRECISION_FLOOR, RULE_PRECISION.get(rule_id, 1.0))


def risk_score(finding: Finding, ctx: ScoringContext) -> float:
    """Return a non-negative number; higher = look at this first."""
    base = float(SEVERITY_WEIGHT[finding.severity])
    score = base * repeat_factor(ctx.repeat_count) * evidence_quality(finding, ctx) * precision_weight(finding.rule_id)
    if finding.category is Category.ML:
        score = min(score, ML_CAP)
    return max(0.0, score)
