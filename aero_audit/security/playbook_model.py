"""The playbook record, in its own module so the air and space catalogues can both import it without a cycle."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Playbook:
    rule_id: str
    title: str
    triage: tuple[str, ...]
    verify: tuple[str, ...]
    escalate: str
    contain: tuple[str, ...]
    sla_minutes: int

__all__ = ["Playbook"]
