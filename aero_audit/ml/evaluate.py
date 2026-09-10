"""Evaluation harness: inject known attack scenarios into *real* traffic and measure detection.

An unsupervised detector has no accuracy until something is measured against ground truth.
This module takes a real recording as background, perturbs a sample of genuine aircraft (or
injects fabricated ones) from an onset batch onward, runs the full engine (rules + model), and
reports per-scenario recall, time-to-detect, and the false-positive rate on untouched aircraft.
Per-rule precision from the same runs feeds `audit/policy.py` and `risk/register.py`, which is
how "training" reaches the risk score.

Scenarios marked `known_gap` are expected to evade kinematic detection (a perfect ghost, a slow
drift). They are kept so the report states the gap in numbers instead of prose.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit.engine import AuditEngine
from ..audit.findings import Category
from ..ingest.replay import iter_recording
from ..models import Batch, Source, StateVector

KINEMATIC_SECURITY = ("SEC-010", "SEC-011", "SEC-014", "SEC-018", "ML-001")


@dataclass
class PerturbContext:
    history: dict[str, list[StateVector]]  # original fixes per aircraft seen so far
    rng: random.Random
    bounds: tuple[float, float, float, float]  # lamin, lomin, lamax, lomax of the recording


Perturb = Callable[[StateVector, int, PerturbContext], list[StateVector]]
Inject = Callable[[int, Batch, PerturbContext, list[str]], list[StateVector]]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    expected_rules: tuple[str, ...]
    perturb: Perturb | None = None
    inject: Inject | None = None  # for fabricated aircraft; targets are the injected ids
    known_gap: bool = False
    eligible: Callable[[StateVector], bool] | None = None  # extra target filter (e.g. compliant integrity)


def _compliant(sv: StateVector) -> bool:
    return (sv.nic or 0) >= 7 and (sv.nac_p or 0) >= 8 and (sv.sil or 0) >= 3


# ---- perturbations ------------------------------------------------------------------------
def _teleport(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    return [sv.model_copy(update={"lat": sv.lat + 0.5})]  # ~30 nm north, persisting


def _velocity_forge(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    return [sv.model_copy(update={"gs_kt": (sv.gs_kt or 0) * 0.5})]


def _altitude_forge(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    up = {"baro_alt_ft": (sv.baro_alt_ft or 0) + 6000.0}
    if sv.geo_alt_ft is not None:
        up["geo_alt_ft"] = sv.geo_alt_ft + 6000.0
    return [sv.model_copy(update=up)]


def _squawk_hijack(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    return [sv.model_copy(update={"squawk": "7500"})]


def _integrity_degrade(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    return [sv.model_copy(update={"nic": 4, "nac_p": 3, "sil": 1})]


REPLAY_LAG_S = 120.0  # at >= 150 kt this is >= 5 nm, the SEC-014 duplicate-separation threshold


def _replay(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    hist = ctx.history.get(sv.icao24, [])
    older = [h for h in hist if sv.ts - h.ts >= REPLAY_LAG_S]
    if not older:
        return [sv]
    old = older[-1]  # most recent fix at least REPLAY_LAG_S old, re-transmitted now under the same address
    return [sv, old.model_copy(update={"ts": sv.ts})]


def _slow_drift(sv: StateVector, k: int, ctx: PerturbContext) -> list[StateVector]:
    return [sv.model_copy(update={"lon": sv.lon + 0.004 * (k + 1)})]  # ~0.2 nm per batch, cumulative


_GHOSTS: dict[str, dict[str, float]] = {}


def _ghost_perfect(i: int, batch: Batch, ctx: PerturbContext, targets: list[str]) -> list[StateVector]:
    """Fabricated aircraft with internally consistent kinematics: undetectable without corroboration."""
    lamin, lomin, lamax, lomax = ctx.bounds
    out = []
    for gid in targets:
        g = _GHOSTS.get(gid)
        if g is None:
            g = {"lat": ctx.rng.uniform(lamin, lamax), "lon": ctx.rng.uniform(lomin, lomax),
                 "track": ctx.rng.uniform(0, 360), "gs": 450.0, "alt": 35000.0, "ts": batch.ts}
            _GHOSTS[gid] = g
        dt = batch.ts - g["ts"]
        d_nm = g["gs"] * dt / 3600.0
        t = math.radians(g["track"])
        g["lat"] += d_nm * math.cos(t) / 60.0
        g["lon"] += d_nm * math.sin(t) / (60.0 * max(math.cos(math.radians(g["lat"])), 0.1))
        g["ts"] = batch.ts
        out.append(StateVector(
            icao24=gid, callsign=f"GHO{gid[-3:].upper()}", ts=batch.ts, lat=g["lat"], lon=g["lon"],
            baro_alt_ft=g["alt"], geo_alt_ft=g["alt"] + 200, gs_kt=g["gs"], track_deg=g["track"], vrate_fpm=0.0,
            squawk="2000", on_ground=False, emergency="none", nic=8, nac_p=9, sil=3,
            position_source="adsb", source=Source.SYNTHETIC,
        ))
    return out


SCENARIOS: dict[str, Scenario] = {
    "teleport": Scenario("teleport", "Position of a real aircraft shifted 30 nm from onset (message replacement)",
                         ("SEC-010",), perturb=_teleport),
    "velocity_forge": Scenario("velocity_forge", "Reported ground speed halved; positions untouched",
                               ("SEC-011", "ML-001"), perturb=_velocity_forge),
    "altitude_forge": Scenario("altitude_forge", "Barometric altitude +6,000 ft; vertical rate untouched",
                               ("SEC-018", "ML-001"), perturb=_altitude_forge),
    "replay": Scenario("replay", "A fix from ~5 batches earlier re-transmitted under the same address",
                       ("SEC-014", "SEC-010"), perturb=_replay),
    "squawk_hijack": Scenario("squawk_hijack", "Squawk forced to 7500", ("SEC-003",), perturb=_squawk_hijack),
    "integrity_degrade": Scenario("integrity_degrade", "NIC/NACp/SIL degraded (GNSS spoofing signature) on compliant aircraft",
                                  ("SEC-012",), perturb=_integrity_degrade, eligible=_compliant),
    "slow_drift": Scenario("slow_drift", "Position drifts ~0.2 nm per batch, cumulative (slow modification)",
                           KINEMATIC_SECURITY, perturb=_slow_drift, known_gap=True),
    "ghost_perfect": Scenario("ghost_perfect", "Fabricated aircraft with consistent kinematics and a callsign",
                              KINEMATIC_SECURITY, inject=_ghost_perfect, known_gap=True),
}


# ---- selection and execution ---------------------------------------------------------------
def select_targets(batches: list[Batch], n: int, seed: int, min_alt_ft: float = 3000.0,
                   min_gs_kt: float = 150.0, min_presence: float = 0.6,
                   eligible: Callable[[StateVector], bool] | None = None,
                   onset: int = 0, min_after_onset: int = 3) -> list[str]:
    """Sample genuine aircraft that are airborne, fast, direct ADS-B, present in at least
    `min_presence` of the batches *of their own region* (round-robin recordings interleave regions,
    so presence is measured per region and the best region counts), and still present for at least
    `min_after_onset` fixes after the attack starts, so recall measures detection, not coverage."""
    per_region_batches: Counter[str] = Counter(b.region for b in batches)
    presence: Counter[tuple[str, str]] = Counter()
    after: Counter[str] = Counter()  # *fresh* fixes after onset: a stale re-reported position cannot carry an attack
    last_ts: dict[str, float] = {}
    ok: set[str] = set()
    for i, b in enumerate(batches):
        for sv in b.states:
            if sv.has_position and sv.airborne:
                presence[(sv.icao24, b.region)] += 1
                fresh = sv.ts > last_ts.get(sv.icao24, -1.0) + 0.5
                last_ts[sv.icao24] = max(last_ts.get(sv.icao24, -1.0), sv.ts)
                if i >= onset and fresh:
                    after[sv.icao24] += 1
                if (sv.baro_alt_ft or 0) >= min_alt_ft and (sv.gs_kt or 0) >= min_gs_kt and \
                        (sv.position_source or "adsb").startswith("adsb") and (eligible is None or eligible(sv)):
                    ok.add(sv.icao24)
    best = defaultdict(float)
    for (icao, region), cnt in presence.items():
        best[icao] = max(best[icao], cnt / per_region_batches[region])
    eligible_ids = sorted(a for a in ok if best[a] >= min_presence and after[a] >= min_after_onset)
    rng = random.Random(seed)
    rng.shuffle(eligible_ids)
    return eligible_ids[:n]


def median_revisit_s(batches: list[Batch], targets: list[str]) -> float | None:
    """Median gap between consecutive fixes of the target aircraft: the detection clock."""
    last: dict[str, float] = {}
    gaps: list[float] = []
    tset = set(targets)
    for b in batches:
        for sv in b.states:
            if sv.icao24 in tset and sv.has_position:
                if sv.icao24 in last and sv.ts > last[sv.icao24] + 0.5:
                    gaps.append(sv.ts - last[sv.icao24])
                last[sv.icao24] = sv.ts
    return statistics.median(gaps) if gaps else None


def _bounds(batches: list[Batch]) -> tuple[float, float, float, float]:
    lats = [sv.lat for b in batches[:3] for sv in b.states if sv.has_position]
    lons = [sv.lon for b in batches[:3] for sv in b.states if sv.has_position]
    if not lats:
        return (40.0, -74.5, 41.0, -73.5)
    lats.sort(); lons.sort()
    q = lambda xs, f: xs[int(f * (len(xs) - 1))]
    return (q(lats, 0.1), q(lons, 0.1), q(lats, 0.9), q(lons, 0.9))


def _perturbed_batches(batches: list[Batch], sc: Scenario, targets: list[str], onset: int, seed: int):
    ctx = PerturbContext(history=defaultdict(list), rng=random.Random(seed), bounds=_bounds(batches))
    _GHOSTS.clear()
    tset = set(targets)
    for i, b in enumerate(batches):
        for sv in b.states:
            if sv.icao24 in tset:
                ctx.history[sv.icao24].append(sv)
        if i < onset:
            yield b
            continue
        states: list[StateVector] = []
        for sv in b.states:
            if sc.perturb is not None and sv.icao24 in tset:
                states.extend(sc.perturb(sv, i - onset, ctx))
            else:
                states.append(sv)
        if sc.inject is not None:
            states.extend(sc.inject(i - onset, b, ctx, targets))
        yield Batch(ts=b.ts, provider=b.provider, region=b.region, states=states)


@dataclass
class ScenarioResult:
    name: str
    description: str
    known_gap: bool
    expected_rules: tuple[str, ...]
    targets: int
    detected: int
    recall: float
    any_security_recall: float
    median_ttd_s: float | None
    findings_on_targets: dict[str, int] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    recording: str
    model: str | None
    batches: int
    onset_batch: int
    aircraft: int
    n_targets: int
    seed: int
    baseline_by_rule: dict[str, int]
    results: list[ScenarioResult]
    rule_tp: dict[str, int]
    rule_fp: dict[str, int]
    rule_precision: dict[str, float | None]
    median_revisit_s: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at, "recording": self.recording, "model": self.model,
            "batches": self.batches, "onset_batch": self.onset_batch, "aircraft": self.aircraft,
            "n_targets": self.n_targets, "seed": self.seed, "baseline_by_rule": self.baseline_by_rule,
            "median_revisit_s": self.median_revisit_s,
            "scenarios": [r.__dict__ for r in self.results],
            "rule_tp": self.rule_tp, "rule_fp": self.rule_fp, "rule_precision": self.rule_precision,
        }

    def render_markdown(self) -> str:
        lines = [
            "# Detection evaluation (injected scenarios on real traffic)", "",
            f"- Background: `{self.recording}` ({self.batches} batches, {self.aircraft} aircraft), model: `{self.model or 'none'}`",
            f"- {self.n_targets} target aircraft per scenario, perturbed from batch {self.onset_batch}; seed {self.seed}; {self.created_at}",
            (f"- Median revisit interval of targets: {self.median_revisit_s:.0f} s. One-off jumps are only detectable while "
             f"jump / gap exceeds the plausibility bound, so recall on teleport-style scenarios rises with polling rate."
             if self.median_revisit_s else ""),
            "", "## Recall and time-to-detect", "",
            "| Scenario | Expected rules | Targets | Detected | Recall | Any security/ML | Median TTD (s) | Note |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            ttd = f"{r.median_ttd_s:.0f}" if r.median_ttd_s is not None else "-"
            lines.append(f"| {r.name} | {', '.join(r.expected_rules) if not r.known_gap else 'any kinematic'} | {r.targets} | {r.detected} | "
                         f"{r.recall:.0%} | {r.any_security_recall:.0%} | {ttd} | {'known gap' if r.known_gap else ''} |")
        lines += ["", "## Per-rule precision (true positives on targets vs findings on untouched aircraft)", "",
                  "| Rule | TP (targets) | FP (clean, baseline run) | Precision |", "|---|---|---|---|"]
        for rid in sorted(set(self.rule_tp) | set(self.rule_fp)):
            p = self.rule_precision.get(rid)
            lines.append(f"| {rid} | {self.rule_tp.get(rid, 0)} | {self.rule_fp.get(rid, 0)} | {f'{p:.2f}' if p is not None else 'n/a'} |")
        lines += ["", "Baseline (unperturbed) findings by rule: " + ", ".join(f"{k} {v}" for k, v in sorted(self.baseline_by_rule.items())), "",
                  (
                      "Precision is only computed for rules the scenarios target. Findings on untouched aircraft are counted as false "
                      "positives even though some are genuine real-world anomalies, so these precisions are conservative."
                  ),
                  "Known-gap scenarios document what kinematic checks cannot see; corroboration (SEC-015) is the mitigation."]
        return "\n".join(lines)


def evaluate(recording: str | Path, model_path: str | Path | None = None, n_targets: int = 25, seed: int = 42,
             scenarios: list[str] | None = None, max_batches: int | None = None, onset_fraction: float = 0.4,
             cooldown_s: float = 120.0) -> EvaluationReport:
    batches = list(iter_recording(recording))
    if max_batches:
        batches = batches[:max_batches]
    if len(batches) < 8:
        raise ValueError("need at least 8 batches to evaluate")
    model = None
    if model_path:
        from .anomaly import KinematicAnomalyModel

        model = KinematicAnomalyModel.load(model_path)
    onset = max(3, int(onset_fraction * len(batches)))
    all_aircraft = {sv.icao24 for b in batches for sv in b.states}
    real_targets = select_targets(batches, n_targets, seed, onset=onset)
    if not real_targets:
        raise ValueError("no eligible target aircraft (need airborne >= 3,000 ft, >= 150 kt, ADS-B, present in 60% of batches)")

    def _engine() -> AuditEngine:
        return AuditEngine(ml_model=model, cooldown_s=cooldown_s)

    baseline = _engine()
    baseline.run(batches)
    baseline_by_rule = dict(baseline.summary()["by_rule"])
    fp_by_rule: Counter[str] = Counter(f.rule_id for f in baseline.findings)

    tp_by_rule: Counter[str] = Counter()
    targeted_rules: set[str] = set()
    results: list[ScenarioResult] = []
    revisit = median_revisit_s(batches, real_targets)
    for name in scenarios or list(SCENARIOS):
        sc = SCENARIOS[name]
        if sc.inject:
            targets = [f"ghost{i:03d}" for i in range(len(real_targets))]
        elif sc.eligible is not None:
            targets = select_targets(batches, n_targets, seed, eligible=sc.eligible, onset=onset) or real_targets
        else:
            targets = real_targets
        tset = set(targets)
        eng = _engine()
        onset_ts = batches[onset].ts
        first_hit: dict[str, float] = {}
        any_sec: set[str] = set()
        on_targets: Counter[str] = Counter()
        # Attribute findings by the *batch* in which the engine raised them. Feed position timestamps
        # lag the batch by tens of seconds, so filtering on finding.ts would discard the first
        # perturbed fix, which is exactly where a one-off manipulation is caught.
        for i, pb in enumerate(_perturbed_batches(batches, sc, targets, onset, seed)):
            new = eng.process_batch(pb)
            if i < onset:
                continue
            for f in new:
                if f.icao24 in tset:
                    on_targets[f.rule_id] += 1
                    if f.category in (Category.SECURITY, Category.ML):
                        any_sec.add(f.icao24)
                    if f.rule_id in sc.expected_rules:
                        first_hit[f.icao24] = min(first_hit.get(f.icao24, pb.ts), pb.ts)
        if not sc.known_gap:
            targeted_rules.update(sc.expected_rules)
            for rid in sc.expected_rules:
                tp_by_rule[rid] += on_targets.get(rid, 0)
        ttds = [t - onset_ts for t in first_hit.values()]
        results.append(ScenarioResult(
            name=sc.name, description=sc.description, known_gap=sc.known_gap, expected_rules=sc.expected_rules,
            targets=len(targets), detected=len(first_hit), recall=len(first_hit) / len(targets),
            any_security_recall=len(any_sec) / len(targets),
            median_ttd_s=statistics.median(ttds) if ttds else None,
            findings_on_targets=dict(on_targets),
        ))
    precision: dict[str, float | None] = {}
    for rid in sorted(targeted_rules):
        tp, fp = tp_by_rule.get(rid, 0), fp_by_rule.get(rid, 0)
        if rid == "SEC-012":  # background hits are genuine low-integrity equipment, not false positives
            fp = 0
        precision[rid] = tp / (tp + fp) if (tp + fp) else None
    return EvaluationReport(
        recording=str(recording), model=str(model_path) if model_path else None, batches=len(batches), onset_batch=onset,
        aircraft=len(all_aircraft), n_targets=len(real_targets), seed=seed, baseline_by_rule=baseline_by_rule,
        results=results, rule_tp={k: tp_by_rule.get(k, 0) for k in precision}, rule_fp={k: fp_by_rule.get(k, 0) for k in precision},
        rule_precision=precision, median_revisit_s=revisit,
    )


def write_evaluation(report: EvaluationReport, models_dir: str | Path = "models", reports_dir: str | Path = "reports") -> tuple[Path, Path]:
    models_dir, reports_dir = Path(models_dir), Path(reports_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    jp = models_dir / "evaluation.json"
    jp.write_text(json.dumps(report.to_dict(), indent=2))
    mp = reports_dir / f"evaluation_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    mp.write_text(report.render_markdown())
    reg = models_dir / "registry.json"
    if reg.exists() and report.model:
        entries = json.loads(reg.read_text())
        for e in reversed(entries):
            if e.get("model_path") == report.model:
                e["evaluation"] = {"created_at": report.created_at, "rule_precision": report.rule_precision,
                                   "recall": {r.name: r.recall for r in report.results}}
                break
        reg.write_text(json.dumps(entries, indent=2))
    return jp, mp
