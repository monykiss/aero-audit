from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.INFO: 1,
    Severity.LOW: 2,
    Severity.MEDIUM: 4,
    Severity.HIGH: 8,
    Severity.CRITICAL: 16,
}
SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


class Category(StrEnum):
    SECURITY = "security"
    SAFETY = "safety"
    OPERATIONS = "operations"
    DATA_QUALITY = "data-quality"
    ML = "ml"


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    rule_id: str
    title: str
    severity: Severity
    category: Category
    icao24: str | None = None
    callsign: str | None = None
    ts: float
    evidence: dict[str, Any] = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=list)  # standards / regs this maps to
    recommendation: str = ""
    risk_score: float = 0.0
    occurrences: int = 1
