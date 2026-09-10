"""Unified register: air risks with their evidence-adjusted likelihoods, space and UAS risks with
residuals derived from control status until their detectors exist. One table, one rating scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..risk.register import assess, rating, score
from .controls import CONTROLS, STATUS_EFFECTIVENESS


@dataclass(frozen=True)
class DomainRisk:
    id: str
    domain: str
    title: str
    likelihood: int
    impact: int
    controls: tuple[str, ...]
    evidence_rules: tuple[str, ...] = ()
    owner: str = "programme lead"
    status: str = "open"
    notes: str = ""

    @property
    def inherent(self) -> int:
        return score(self.likelihood, self.impact)

    @property
    def control_effectiveness(self) -> float:
        vals = [STATUS_EFFECTIVENESS[CONTROLS[c].status] for c in self.controls if c in CONTROLS]
        return max(vals) if vals else 0.0  # the strongest control in place bounds the residual

    @property
    def residual(self) -> int:
        return max(1, round(self.inherent * (1.0 - self.control_effectiveness)))

    def to_row(self) -> dict[str, Any]:
        return {"id": self.id, "domain": self.domain, "title": self.title, "baseline_L": self.likelihood, "L": self.likelihood,
                "I": self.impact, "score": self.inherent, "rating": rating(self.inherent), "residual": self.residual,
                "residual_rating": rating(self.residual), "control_effectiveness": round(self.control_effectiveness, 2),
                "controls": list(self.controls), "evidence": list(self.evidence_rules), "observed_hits": None,
                "rate_lb_per_1000": None, "owner": self.owner, "status": self.status, "notes": self.notes}


SPACE_RISKS: tuple[DomainRisk, ...] = (
    DomainRisk("S01", "space-launch", "Launch telemetry stream manipulated, spliced or replayed", 3, 4, ("C-08",), ("SPC-001", "SPC-002", "SPC-004"),
               notes="Detection exists on supplied streams; no live source yet."),
    DomainRisk("S02", "space-launch", "Telemetry dropout hides an in-flight event", 3, 3, ("C-08",), ("SPC-003",)),
    DomainRisk("S03", "space-assets", "Tampered or substituted external asset (model, texture, imagery) enters analysis or training", 2, 3, ("C-33", "C-24"),
               notes="Blob and SHA-256 verification with provenance sidecars."),
    DomainRisk("S04", "space-assets", "NASA media or NOSA terms breached (insignia, endorsement, attribution)", 2, 2, ("C-28",)),
    DomainRisk("S05", "space-orbital", "Conjunction not screened or screened on stale elements", 3, 5, ("C-09",),
               notes="Planned: SGP4 propagation, CDM ingest, Pc thresholds."),
    DomainRisk("S06", "space-orbital", "Mission design non-compliant with debris mitigation rules", 2, 4, ("C-10",)),
    DomainRisk("S07", "space-orbital", "Unauthenticated space data link accepted as truth", 2, 4, ("C-32",),
               notes="Expect SDLS-protected links; treat unauthenticated telemetry like ADS-B: physics and corroboration."),
    DomainRisk("U01", "uas-utm", "Well-clear violation undetected or alerted too late", 3, 5, ("C-11",)),
    DomainRisk("U02", "uas-utm", "UTM exchanges non-conformant with the published API contracts", 2, 3, ("C-12",)),
    DomainRisk("G01", "space-launch", "Flight-software class and assurance level not established before use", 2, 4, ("C-31",)),
)


def unified_register(summary: dict[str, Any] | None = None, rule_precision: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Air rows from the evidence-adjusted register, then the domain risks, on the same scale."""
    rows: list[dict[str, Any]] = []
    for r in assess(summary, rule_precision):
        row = dict(r)
        row["domain"] = "air-surveillance" if r["id"] not in ("R09",) else "air-operations"
        row.setdefault("controls", [])
        rows.append(row)
    rows += [r.to_row() for r in SPACE_RISKS]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda r: (order[r["residual_rating"]], -r["residual"], r["id"]))
    return rows


def by_rating(rows: list[dict[str, Any]], key: str = "residual_rating") -> dict[str, int]:
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in rows:
        out[r[key]] += 1
    return out


def render_markdown(rows: list[dict[str, Any]], title: str = "Unified risk register") -> str:
    lines = [f"# {title}", "", "| Id | Domain | Risk | L | I | Inherent | Residual | Controls / evidence |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ctl = ", ".join(r.get("controls") or []) or ", ".join(r.get("evidence") or []) or "-"
        lines.append(f"| {r['id']} | {r['domain']} | {r['title']} | {r['L']} | {r['I']} | {r['score']} {r['rating']} | {r['residual']} {r['residual_rating']} | {ctl} |")
    return "\n".join(lines) + "\n"


__all__ = ["SPACE_RISKS", "DomainRisk", "by_rating", "render_markdown", "unified_register"]
