"""Risk register: threats turned into owned, scored, mitigated risks.

Scoring is the common 5x5 likelihood x impact matrix. Baseline likelihoods come from the threat
catalog; `assess()` moves them using what the audit actually observed (findings per 1,000
aircraft-hours is the evidence rate). That is the bridge from 'detections' to 'risk posture'.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from ..security.threats import THREATS, Coverage

CONTROL_EFFECTIVENESS = {Coverage.COVERED: 0.6, Coverage.PARTIAL: 0.35, Coverage.GAP: 0.0}

RATING_BANDS = [(15, "critical"), (10, "high"), (5, "medium"), (0, "low")]


def score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def rating(value: int) -> str:
    for floor, label in RATING_BANDS:
        if value >= floor:
            return label
    return "low"


@dataclass(frozen=True)
class Risk:
    id: str
    title: str
    threat_ids: tuple[str, ...]
    likelihood: int
    impact: int
    existing_controls: tuple[str, ...]
    planned_mitigations: tuple[str, ...]
    evidence_rules: tuple[str, ...]  # rule ids whose observed rate moves the likelihood
    owner: str = "security lead (unassigned)"
    status: str = "open"

    @property
    def inherent(self) -> int:
        return score(self.likelihood, self.impact)

    @property
    def rating(self) -> str:
        return rating(self.inherent)

    @property
    def control_effectiveness(self) -> float:
        """Mean detective-control effectiveness across the risk's threats (from coverage)."""
        vals = [CONTROL_EFFECTIVENESS[_t(t).coverage] for t in self.threat_ids]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def residual(self) -> int:
        return max(1, round(self.inherent * (1.0 - self.control_effectiveness)))


def _t(tid: str):
    return next(t for t in THREATS if t.id == tid)


RISK_REGISTER: list[Risk] = [
    Risk("R01", "Surveillance picture poisoned by injected or modified ADS-B", ("T01", "T02", "T07"),
         2, 5,
         ("Kinematic rules SEC-010/011/014", "Cross-feed corroboration SEC-015", "Trust ledger"),
         ("Ingest a third independent feed / MLAT", "Sequence models over full tracks",
          "Receiver-level RSSI analysis"),
         ("SEC-010", "SEC-014", "SEC-015")),
    Risk("R02", "False security response triggered by spoofed emergency codes", ("T04",),
         1, 5,
         ("SEC-001..004 with corroboration guidance", "Playbook mandates voice/ACARS confirmation"),
         ("Automated cross-feed check on every emergency code before alerting",),
         ("SEC-001", "SEC-002", "SEC-003", "SEC-004")),
    Risk("R03", "Loss of surveillance through flooding or jamming", ("T05", "T06"),
         1, 5,
         ("SEC-016 new-address burst", "SEC-017 coverage collapse", "OPS-001 stale contact"),
         ("Alert routing to RF monitoring", "Second feed as automatic fallback"),
         ("SEC-016", "SEC-017")),  # OPS-001 is coverage planning, not jamming evidence
    Risk("R04", "Decisions built on low-integrity positions", ("T09",),
         4, 2,
         ("SEC-012 integrity thresholds", "Trust ledger weighting"),
         ("Per-operator integrity scorecards", "Exclude low-trust tracks from KPIs"),
         ("SEC-012",)),
    Risk("R05", "Identity confusion (wrong aircraft attributed)", ("T08",),
         2, 3,
         ("SEC-013 identity gap", "SEC-014 duplicate address", "SEC-020 watchlist"),
         ("Registry cross-check ICAO24 <-> registration <-> type",),
         ("SEC-013", "SEC-014")),  # SEC-020 needs a configured watchlist; its silence is not evidence
    Risk("R06", "Upstream feed compromise propagates to every consumer", ("T10",),
         2, 4,
         ("Two independent feeds", "TLS", "Raw batch recordings for forensics"),
         ("Feed health SLOs", "Automatic quarantine of a disagreeing feed"),
         ("SEC-015", "SEC-017")),
    Risk("R07", "Privacy harm from tracking sensitive flights", ("T11",),
         3, 3,
         ("Watchlist protect mode", "Passive-only design"),
         ("Retention limits on recordings", "Access control on reports"),
         ()),  # a policy risk: nothing in the feeds can raise or lower it
    Risk("R08", "Toolchain compromise silently degrades detection", ("T12",),
         2, 4,
         ("uv lockfile", "Test suite pins rule behaviour", "Model card"),
         ("Weight checksum verification", "Dependency audit in CI", "Signed releases"),
         ()),
    Risk("R09", "Operational inefficiency (holding, taxi, apron congestion) goes unmeasured",
         ("T09",), 4, 2,
         ("OPS-002 holding", "OPS-VIS-001 apron capacity", "METAR context"),
         ("Airport geometry for taxi/runway occupancy", "Fine-tuned aerial detector"),
         ("OPS-002", "OPS-VIS-001")),
]


MIN_AIRCRAFT_FOR_REDUCTION = 500  # below this sample size, zero observations prove nothing


def wilson_lower(k: float, n: int, z: float = 1.96) -> float:
    """Lower bound of the 95% Wilson interval for a proportion k/n (k may be fractional)."""
    if n <= 0:
        return 0.0
    p = min(1.0, max(0.0, k / n))
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def observed_likelihood(baseline: int, rate_per_1000: float, aircraft: int = MIN_AIRCRAFT_FOR_REDUCTION) -> int:
    """Map an observed evidence rate (per 1,000 aircraft) onto the 1-5 scale.

    Callers pass the *lower confidence bound* of the rate, so a handful of hits on a small sample
    does not escalate. Deliberately asymmetric: evidence can raise likelihood by up to two bands,
    but can lower it by one band only when the sample is large enough that silence is meaningful.
    """
    if rate_per_1000 >= 50:
        bump = 2
    elif rate_per_1000 >= 10:
        bump = 1
    elif rate_per_1000 > 0 or aircraft < MIN_AIRCRAFT_FOR_REDUCTION:
        bump = 0
    else:
        bump = -1
    return max(1, min(5, baseline + bump))


def merge_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine per-recording audit summaries. Each recording must be audited in its own engine:
    concatenating recordings through one engine makes every region switch look like an address
    burst (SEC-016) and a coverage collapse (SEC-017)."""
    by_rule: dict[str, int] = {}
    aircraft = 0
    findings = 0
    batches = 0
    for s in summaries:
        for k, v in s.get("by_rule", {}).items():
            by_rule[k] = by_rule.get(k, 0) + v
        aircraft += int(s.get("unique_aircraft") or 0)
        findings += int(s.get("findings_total") or 0)
        batches += int(s.get("batches") or 0)
    return {"by_rule": by_rule, "unique_aircraft": aircraft, "findings_total": findings, "batches": batches,
            "recordings": len(summaries)}


def assess(summary: dict[str, Any] | None, rule_precision: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Re-score the register using an audit summary (by_rule counts + unique_aircraft).

    Evidence hits are weighted by each rule's measured precision (from `aero evaluate`) to give
    expected true positives, converted to a rate with a Wilson lower bound before mapping to a
    likelihood band. Pass None for the baseline register (no evidence applied)."""
    if rule_precision is None:
        from ..audit.policy import RULE_PRECISION

        rule_precision = RULE_PRECISION
    n = max(1, int((summary or {}).get("unique_aircraft") or 1))
    by_rule: dict[str, int] = (summary or {}).get("by_rule", {})
    rows = []
    for r in RISK_REGISTER:
        hits = sum(by_rule.get(rid, 0) for rid in r.evidence_rules)
        expected_true = sum(by_rule.get(rid, 0) * rule_precision.get(rid, 1.0) for rid in r.evidence_rules)
        rate = 1000.0 * expected_true / n
        rate_lb = 1000.0 * wilson_lower(expected_true, n)
        lk = observed_likelihood(r.likelihood, rate_lb, n) if (summary and r.evidence_rules) else r.likelihood
        adj = replace(r, likelihood=lk)
        rows.append({
            "id": r.id, "title": r.title, "threats": ", ".join(r.threat_ids),
            "baseline_L": r.likelihood, "observed_hits": hits, "expected_true": round(expected_true, 1),
            "rate_per_1000": round(rate, 1), "rate_lb_per_1000": round(rate_lb, 1),
            "L": lk, "I": r.impact, "score": adj.inherent, "rating": adj.rating,
            "control_effectiveness": round(adj.control_effectiveness, 2),
            "residual": adj.residual, "residual_rating": rating(adj.residual),
            "controls": r.existing_controls, "mitigations": r.planned_mitigations, "owner": r.owner,
        })
    return sorted(rows, key=lambda x: -x["score"])


def heatmap(rows: list[dict[str, Any]], key_l: str = "L") -> str:
    grid = {(lk, im): [] for lk in range(1, 6) for im in range(1, 6)}
    for r in rows:
        grid[(r[key_l], r["I"])].append(r["id"])
    lines = ["| L \\ I | 1 | 2 | 3 | 4 | 5 |", "|---|---|---|---|---|---|"]
    for lk in range(5, 0, -1):
        cells = [", ".join(grid[(lk, im)]) or " " for im in range(1, 6)]
        lines.append(f"| {lk} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(rows: list[dict[str, Any]], title: str = "Risk register") -> str:
    lines = [f"# {title}", "",
             (
                 "Inherent score = likelihood x impact (1-5 each); rating bands: >=15 critical, >=10 high, >=5 medium. "
                 "Residual = inherent x (1 - detective control effectiveness from threat coverage). Evidence hits are "
                 "weighted by measured rule precision and converted to a Wilson 95% lower-bound rate before moving likelihood."
             ), "",
             "| ID | Risk | Threats | L (base->obs) | I | Inherent | Rating | Ctrl eff. | Residual | Res. rating | Hits (exp. true) | rate / 1,000 (lower bound) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['title']} | {r['threats']} | {r['baseline_L']}->{r['L']} | {r['I']} | {r['score']} | **{r['rating']}** | "
                     f"{r['control_effectiveness']:.2f} | {r['residual']} | {r['residual_rating']} | {r['observed_hits']} ({r['expected_true']}) | "
                     f"{r['rate_per_1000']} ({r['rate_lb_per_1000']}) |")
    lines += ["", "## Inherent heat map (rows = likelihood, columns = impact)", "", heatmap(rows), "",
              "## Controls and mitigations", ""]
    for r in rows:
        lines += [f"### {r['id']} {r['title']}", f"- Owner: {r['owner']}",
                  "- Existing controls: " + "; ".join(r["controls"]),
                  "- Planned mitigations: " + "; ".join(r["mitigations"]), ""]
    return "\n".join(lines)
