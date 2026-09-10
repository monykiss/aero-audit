"""Runs rules (and optionally an ML model) over a batch stream, de-duplicates, and scores."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..features import TrackStore
from ..models import Batch
from ..security.trust import TrustLedger
from .findings import SEVERITY_ORDER, Category, Finding, Severity
from .policy import SOURCE_TRUST, ScoringContext, risk_score
from .rules import BATCH_RULES, RULES, RuleContext

if TYPE_CHECKING:
    from ..alerts import Alerter
    from ..ml.anomaly import KinematicAnomalyModel
    from ..security.watchlist import Watchlist

# ---- stream-level thresholds (need history across batches, so they live in the engine) ----
BURST_MIN_NEW = 25  # never flag bursts smaller than this
BURST_FACTOR = 4.0  # new addresses > factor x rolling mean of new addresses per batch
COLLAPSE_FRACTION = 0.5  # aircraft count < fraction x rolling mean for the same region
COLLAPSE_MIN_BASELINE = 20  # ignore tiny regions
HISTORY = 8
ML_MIN_FLAGS, ML_FLAG_WINDOW_S = 2, 600.0  # an ML finding needs >= 2 flagged fixes within 10 min
# Slow-moving conditions should fire once per episode, not every default cooldown window.
COOLDOWN_OVERRIDES_S: dict[str, float] = {
    "OPS-001": 900.0,  # coverage gap: one note per aircraft per 15 min
    "OPS-002": 600.0,  # a hold lasts minutes; count it once, occurrences tracks persistence
    "OPS-003": 900.0,
    "OPS-004": 600.0,
    "SEC-012": 900.0,  # equipment integrity does not change mid-flight
    "SEC-013": 900.0,
    "OPS-005": 900.0,
    "ML-001": 300.0,
    "SAF-004": 300.0,
}


class AuditEngine:
    def __init__(
        self,
        ml_model: KinematicAnomalyModel | None = None,
        cooldown_s: float = 120.0,
        window: int = 12,
        watchlist: Watchlist | None = None,
        alerter: Alerter | None = None,
        trust: TrustLedger | None = None,
    ) -> None:
        self.store = TrackStore(window=window)
        self.ml_model = ml_model
        self.watchlist = watchlist
        self.alerter = alerter
        self.trust = trust or TrustLedger()
        self.cooldown_s = cooldown_s
        self._known: set[str] = set()
        self._adsb_airborne_fixes = 0
        self._adsb_compliant_fixes = 0
        self._ml_flags: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=8))
        self._new_per_batch: deque[int] = deque(maxlen=HISTORY)
        self._count_hist: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=HISTORY))
        self.findings: list[Finding] = []
        self._last_fired: dict[tuple[str, str | None], float] = {}
        self._last_sev: dict[tuple[str, str | None], Severity] = {}
        self._counts: dict[tuple[str, str | None], int] = defaultdict(int)
        self._first_seen: dict[tuple[str, str | None], float] = {}
        self.batches = 0
        self.states_seen = 0
        self.aircraft: set[str] = set()
        self.first_ts: float | None = None
        self.last_ts: float | None = None
        self.provider: str | None = None
        self.region: str | None = None

    def process_batch(self, batch: Batch) -> list[Finding]:
        self.batches += 1
        self.states_seen += len(batch.states)
        self.aircraft.update(sv.icao24 for sv in batch.states)
        self.first_ts = batch.ts if self.first_ts is None else self.first_ts
        self.last_ts = batch.ts
        self.provider, self.region = batch.provider, batch.region
        for sv in batch.states:  # KPI: share of airborne ADS-B fixes meeting 91.227 minimums
            if sv.airborne and (sv.position_source or "").startswith("adsb") and sv.nic is not None:
                self._adsb_airborne_fixes += 1
                if (sv.nic or 0) >= 7 and (sv.nac_p or 0) >= 8 and (sv.sil or 0) >= 3:
                    self._adsb_compliant_fixes += 1
        feats = self.store.update(batch)
        ctx = RuleContext(
            batch_ts=batch.ts, provider=batch.provider, region=batch.region, track=self.store.track
        )
        by_icao = {f.icao24: f for f in feats}

        candidates: list[Finding] = []
        for sv in batch.states:
            f = by_icao.get(sv.icao24)
            for _, fn in RULES:
                candidates.extend(fn(sv, f, ctx))
            if self.watchlist is not None:
                candidates.extend(self.watchlist.check(sv))
        for _, bfn in BATCH_RULES:
            candidates.extend(bfn(batch, ctx))
        candidates.extend(self._stream_checks(batch))
        if self.ml_model is not None and feats:
            for fd in self.ml_model.findings(feats, ctx):
                flags = self._ml_flags[fd.icao24 or ""]
                flags.append(fd.ts)
                recent = [t for t in flags if fd.ts - t <= ML_FLAG_WINDOW_S]
                if len(recent) >= ML_MIN_FLAGS:  # single flagged fixes are jitter; persistence is signal
                    fd.evidence["flagged_fixes_10min"] = len(recent)
                    candidates.append(fd)

        accepted: list[Finding] = []
        for fd in candidates:
            key = (fd.rule_id, fd.icao24)
            self._counts[key] += 1
            self._first_seen.setdefault(key, batch.ts)
            last = self._last_fired.get(key)
            escalated = key in self._last_sev and SEVERITY_ORDER.index(fd.severity) < SEVERITY_ORDER.index(self._last_sev[key])
            if last is not None and not escalated and batch.ts - last < COOLDOWN_OVERRIDES_S.get(fd.rule_id, self.cooldown_s):
                continue  # de-duplicate, unless the finding got *more* severe (e.g. a confirmed 7500)
            self._last_fired[key] = batch.ts
            self._last_sev[key] = fd.severity
            fd.occurrences = self._counts[key]
            fd.risk_score = risk_score(
                fd,
                ScoringContext(
                    repeat_count=self._counts[key],
                    source_trust=SOURCE_TRUST.get(fd.evidence.get("position_source"), 0.5),
                    seconds_since_first=batch.ts - self._first_seen[key],
                ),
            )
            accepted.append(fd)
        self.findings.extend(accepted)

        flagged = {fd.icao24 for fd in candidates if fd.icao24}
        for sv in batch.states:
            if sv.icao24 not in flagged:
                self.trust.observe_clean(sv.icao24)
        for fd in accepted:
            self.trust.penalize(fd)
            fd.evidence["trust_after"] = round(self.trust.score(fd.icao24), 2) if fd.icao24 else None
        if self.alerter is not None:
            self.alerter.dispatch(accepted)
        return accepted

    def _stream_checks(self, batch: Batch) -> list[Finding]:
        """SEC-016 new-address burst and SEC-017 coverage collapse; both need cross-batch memory."""
        out: list[Finding] = []
        addrs = {sv.icao24 for sv in batch.states}
        new = addrs - self._known
        n_new = len(new)
        if len(self._new_per_batch) >= 3:
            mean_new = sum(self._new_per_batch) / len(self._new_per_batch)
            if n_new >= BURST_MIN_NEW and n_new > BURST_FACTOR * max(mean_new, 1.0):
                out.append(Finding(
                    rule_id="SEC-016", title="Burst of never-seen ICAO addresses (flooding indicator)",
                    severity=Severity.HIGH, category=Category.SECURITY, icao24=None, ts=batch.ts,
                    evidence={"new_addresses": n_new, "rolling_mean_new": round(mean_new, 1),
                              "region": batch.region, "sample": sorted(new)[:10], "feed": batch.provider},
                    controls=["ICAO Doc 9924 (surveillance integrity)", "ICAO Annex 17"],
                    recommendation="Check whether the new addresses have plausible kinematics and "
                    "registrations; a receiver coming online looks similar but its traffic is realistic.",
                ))
        self._new_per_batch.append(n_new)
        self._known |= addrs

        hist = self._count_hist[batch.region]
        if len(hist) >= 3:
            mean_n = sum(hist) / len(hist)
            if mean_n >= COLLAPSE_MIN_BASELINE and len(batch) < COLLAPSE_FRACTION * mean_n:
                out.append(Finding(
                    rule_id="SEC-017", title="Coverage collapse (jamming or feed outage indicator)",
                    severity=Severity.HIGH, category=Category.SECURITY, icao24=None, ts=batch.ts,
                    evidence={"aircraft_now": len(batch), "rolling_mean": round(mean_n, 1),
                              "region": batch.region, "feed": batch.provider},
                    controls=["ICAO Doc 9924", "ICAO Annex 10 Vol IV (surveillance systems)"],
                    recommendation="Compare with the second feed: a drop on one feed only is a feeder "
                    "outage; a simultaneous drop on independent feeds near an airport is an RF event.",
                ))
        hist.append(len(batch))
        return out

    def run(self, batches: Iterable[Batch]) -> list[Finding]:
        for b in batches:
            self.process_batch(b)
        return self.findings

    def summary(self) -> dict[str, Any]:
        by_sev = {s.value: 0 for s in SEVERITY_ORDER}
        by_cat: dict[str, int] = defaultdict(int)
        by_rule: dict[str, int] = defaultdict(int)
        per_aircraft: dict[str, float] = defaultdict(float)
        for f in self.findings:
            by_sev[f.severity.value] += 1
            by_cat[f.category.value] += 1
            by_rule[f.rule_id] += 1
            if f.icao24:
                per_aircraft[f.icao24] += f.risk_score
        top = sorted(per_aircraft.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return {
            "provider": self.provider,
            "region": self.region,
            "batches": self.batches,
            "state_vectors": self.states_seen,
            "unique_aircraft": len(self.aircraft),
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "findings_total": len(self.findings),
            "by_severity": by_sev,
            "by_category": dict(by_cat),
            "by_rule": dict(sorted(by_rule.items())),
            "top_aircraft_by_risk": top,
            "low_trust_aircraft": self.trust.low_trust(0.5)[:15],
            "adsb_compliance_rate": (
                round(self._adsb_compliant_fixes / self._adsb_airborne_fixes, 4)
                if self._adsb_airborne_fixes else None
            ),
            "adsb_airborne_fixes": self._adsb_airborne_fixes,
            "alerts_sent": self.alerter.sent if self.alerter else 0,
        }
