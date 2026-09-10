"""Thread-safe live state: the engine, the latest batch, trails, events, and demo injections."""

from __future__ import annotations

import math
import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from ..audit.engine import AuditEngine
from ..audit.findings import SEVERITY_ORDER, Finding
from ..ecosystem import Enriched, enrich, summarize
from ..models import Batch, Source, StateVector
from ..security.playbooks import playbook_for

RECENT_WINDOW_S = 600.0
TRAIL_LEN = 24


@dataclass
class Injection:
    kind: str
    icao24: str | None
    remaining: int
    started_ts: float
    ghost: dict[str, Any] = field(default_factory=dict)
    label: str = ""


INJECTION_KINDS = {
    "teleport": "Position replacement: target shifted 30 nm north (SEC-010)",
    "squawk_7500": "Hijack code 7500 on the target (SEC-003; unconfirmed, then confirmed)",
    "altitude_forge": "Target altitude +6,000 ft, vertical rate untouched (SEC-018)",
    "velocity_forge": "Target reported speed halved (SEC-011 / ML-001)",
    "ghost_perfect": "Fabricated aircraft with consistent physics (known gap: nothing fires)",
    "ghost_jumpy": "Fabricated aircraft that jumps 20 nm every third poll (SEC-010)",
    "flood": "60 never-seen addresses appear at once (SEC-016)",
    "collapse": "60% of the region's aircraft vanish (SEC-017)",
}


class LiveState:
    def __init__(self, engine: AuditEngine, mode: str, provider: str, region: str, demo: bool) -> None:
        self.lock = threading.Lock()
        self.engine = engine
        self.mode, self.provider, self.region, self.demo = mode, provider, region, demo
        self.started_at = time.time()
        self.last_batch: Batch | None = None
        self.last_ingest_wall: float | None = None
        self.batches = 0
        self.feed_latency_ms: float | None = None
        self.errors: deque[str] = deque(maxlen=20)
        self.trails: dict[str, deque[tuple[float, float, float, float]]] = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
        self.events: deque[dict[str, Any]] = deque(maxlen=200)
        self.counts: deque[tuple[float, str, int]] = deque(maxlen=120)
        self.injections: list[Injection] = []
        self.injected_ids: set[str] = set()
        self.metars: list[dict[str, Any]] = []
        self.faa_status: dict[str, Any] = {"updated": None, "entries": []}
        self.enriched: dict[str, Enriched] = {}
        self.eco: dict[str, Any] = {}
        self.rng = random.Random(7)
        self.center: tuple[float, float] | None = None
        self.stop = threading.Event()

    # ---- ingestion -------------------------------------------------------------------------
    def ingest(self, batch: Batch, latency_ms: float | None = None) -> list[Finding]:
        with self.lock:
            batch = self._apply_injections(batch)
            new = self.engine.process_batch(batch)
            self.last_batch = batch
            self.last_ingest_wall = time.time()
            self.batches += 1
            self.feed_latency_ms = latency_ms
            self.counts.append((batch.ts, batch.region, len(batch)))
            for sv in batch.states:
                if sv.has_position:
                    self.trails[sv.icao24].append((sv.ts, sv.lat, sv.lon, sv.baro_alt_ft or 0.0))
            self.enriched = {sv.icao24: enrich(sv) for sv in batch.states if sv.has_position}
            self.eco = summarize(batch, self.enriched, self._recent_by_aircraft(batch.ts), self.faa_status.get("entries"))
            self.eco["updated_ts"] = batch.ts
            for f in new:
                self.events.appendleft(self._finding_json(f))
            if self.center is None and batch.states:
                lats = [s.lat for s in batch.states if s.has_position]
                lons = [s.lon for s in batch.states if s.has_position]
                if lats:
                    self.center = (sum(lats) / len(lats), sum(lons) / len(lons))
            return new

    # ---- demo injections -------------------------------------------------------------------
    def inject(self, kind: str, icao24: str | None = None, batches: int = 6) -> Injection:
        if kind not in INJECTION_KINDS:
            raise ValueError(f"unknown injection '{kind}'; known: {', '.join(INJECTION_KINDS)}")
        with self.lock:
            if kind in ("teleport", "squawk_7500", "altitude_forge", "velocity_forge") and not icao24:
                icao24 = self._pick_target()
            ts = self.last_batch.ts if self.last_batch else time.time()
            inj = Injection(kind, icao24, batches, ts, label=INJECTION_KINDS[kind])
            if kind.startswith("ghost"):
                inj.icao24 = f"gh{self.rng.randrange(0, 0xFFFF):04x}"
                lat, lon = self.center or (40.7, -74.0)
                inj.ghost = {"lat": lat + self.rng.uniform(-0.6, 0.6), "lon": lon + self.rng.uniform(-0.8, 0.8),
                             "track": self.rng.uniform(0, 360), "gs": 450.0, "alt": 35000.0, "ts": ts, "n": 0}
                inj.remaining = 40
            if kind == "flood":
                inj.remaining = 3
            if kind == "collapse":
                inj.remaining = 2
            self.injections.append(inj)
            if inj.icao24:
                self.injected_ids.add(inj.icao24)
            return inj

    def reset_tracks(self) -> None:
        """Forget track memory and stream history (replay loop boundary): the next batch is a fresh
        picture, not a 20-minute jump for every aircraft."""
        from ..features import TrackStore

        with self.lock:
            self.engine.store = TrackStore(window=self.engine.store.window)
            self.engine._new_per_batch.clear()
            self.engine._count_hist.clear()
            self.engine._ml_flags.clear()
            self.trails.clear()
            self.engine.trust = type(self.engine.trust)()

    def clear_injections(self) -> None:
        with self.lock:
            self.injections.clear()
            self.injected_ids.clear()

    def _pick_target(self) -> str | None:
        if not self.last_batch:
            return None
        cands = [s for s in self.last_batch.states if s.has_position and s.airborne and (s.baro_alt_ft or 0) > 8000
                 and (s.gs_kt or 0) > 200 and (s.position_source or "adsb").startswith("adsb") and s.icao24 not in self.injected_ids
                 and (self.last_batch.ts - s.ts) < 40]
        return self.rng.choice(cands).icao24 if cands else None

    def _apply_injections(self, batch: Batch) -> Batch:
        if not self.injections:
            return batch
        states: list[StateVector] = []
        active = [i for i in self.injections if i.remaining > 0]
        by_target = {i.icao24: i for i in active if i.icao24 and not i.kind.startswith("ghost") and i.kind not in ("flood", "collapse")}
        collapse = next((i for i in active if i.kind == "collapse"), None)
        for sv in batch.states:
            inj = by_target.get(sv.icao24)
            if inj is not None:
                if inj.kind == "teleport":
                    sv = sv.model_copy(update={"lat": sv.lat + 0.5})
                elif inj.kind == "squawk_7500":
                    sv = sv.model_copy(update={"squawk": "7500"})
                elif inj.kind == "altitude_forge":
                    sv = sv.model_copy(update={"baro_alt_ft": (sv.baro_alt_ft or 0) + 6000.0})
                elif inj.kind == "velocity_forge":
                    sv = sv.model_copy(update={"gs_kt": (sv.gs_kt or 0) * 0.5})
            if collapse is not None and self.rng.random() < 0.6:
                continue
            states.append(sv)
        for inj in active:
            if inj.kind.startswith("ghost"):
                states.append(self._advance_ghost(inj, batch.ts))
            elif inj.kind == "flood":
                lat, lon = self.center or (40.7, -74.0)
                for k in range(60):
                    states.append(StateVector(
                        icao24=f"fl{inj.started_ts % 1000:03.0f}{k:02d}", callsign=f"FLD{k:03d}", ts=batch.ts,
                        lat=lat + self.rng.uniform(-0.5, 0.5), lon=lon + self.rng.uniform(-0.7, 0.7),
                        baro_alt_ft=self.rng.uniform(8000, 36000), gs_kt=self.rng.uniform(250, 450),
                        track_deg=self.rng.uniform(0, 360), vrate_fpm=0.0, squawk="2000", position_source="adsb",
                        nic=8, nac_p=9, sil=3, source=Source.SYNTHETIC))
        for inj in active:
            inj.remaining -= 1
        self.injections = [i for i in self.injections if i.remaining > 0]
        return Batch(ts=batch.ts, provider=batch.provider, region=batch.region, states=states)

    def _advance_ghost(self, inj: Injection, ts: float) -> StateVector:
        g = inj.ghost
        dt = max(0.0, ts - g["ts"])
        d_nm = g["gs"] * dt / 3600.0
        t = math.radians(g["track"])
        g["lat"] += d_nm * math.cos(t) / 60.0
        g["lon"] += d_nm * math.sin(t) / (60.0 * max(math.cos(math.radians(g["lat"])), 0.1))
        g["ts"] = ts
        g["n"] += 1
        if inj.kind == "ghost_jumpy" and g["n"] % 3 == 0:
            g["lat"] += 0.33  # 20 nm jump every third poll
        return StateVector(
            icao24=inj.icao24 or "gh0000", callsign=f"GHO{(inj.icao24 or '0000')[-3:].upper()}", ts=ts, lat=g["lat"], lon=g["lon"],
            baro_alt_ft=g["alt"], geo_alt_ft=g["alt"] + 200, gs_kt=g["gs"], track_deg=g["track"], vrate_fpm=0.0,
            squawk="2000", emergency="none", nic=8, nac_p=9, sil=3, position_source="adsb", source=Source.SYNTHETIC,
        )

    # ---- snapshots -------------------------------------------------------------------------
    def _finding_json(self, f: Finding) -> dict[str, Any]:
        pb = playbook_for(f.rule_id)
        e = self.enriched.get(f.icao24 or "")
        return {
            "operator": e.operator if e else None, "operator_code": e.operator_code if e else None,
            "type": e.type_code if e else None, "phase": e.phase if e else None, "airport": e.airport if e else None,
            "id": f.id, "rule": f.rule_id, "severity": f.severity.value, "category": f.category.value,
            "icao24": f.icao24, "callsign": f.callsign, "ts": f.ts, "title": f.title, "risk": round(f.risk_score, 2),
            "occurrences": f.occurrences, "evidence": {k: v for k, v in f.evidence.items() if k != "feed"},
            "playbook": pb.triage[0] if pb else None, "injected": bool(f.icao24 and f.icao24 in self.injected_ids),
        }

    def _recent_by_aircraft(self, now_ts: float) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = defaultdict(list)
        for f in self.engine.findings:
            if f.icao24 and now_ts - f.ts <= RECENT_WINDOW_S:
                out[f.icao24].append(f)
        return out

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            b = self.last_batch
            s = self.engine.summary()
            now_ts = b.ts if b else time.time()
            recent = self._recent_by_aircraft(now_ts)
            aircraft = []
            if b:
                for sv in b.states:
                    if not sv.has_position:
                        continue
                    fs = recent.get(sv.icao24, [])
                    top = min(fs, key=lambda f: SEVERITY_ORDER.index(f.severity)) if fs else None
                    emergency = sv.squawk in ("7500", "7600", "7700") or (sv.emergency not in (None, "none", ""))
                    e = self.enriched.get(sv.icao24)
                    aircraft.append({
                        "operator_code": e.operator_code if e else None, "operator": e.operator if e else None,
                        "operator_cat": e.operator_cat if e else None, "type_name": e.type_name if e else None,
                        "type_cat": e.type_cat if e else None, "phase": e.phase if e else None,
                        "airport": e.airport if e else None, "airport_nm": e.airport_nm if e else None, "agl": e.agl_ft if e else None,
                        "ts": sv.ts,
                        "icao24": sv.icao24, "callsign": (sv.callsign or "").strip() or None, "reg": sv.registration,
                        "type": sv.aircraft_type, "lat": sv.lat, "lon": sv.lon, "alt": sv.baro_alt_ft, "gs": sv.gs_kt,
                        "track": sv.track_deg, "vrate": sv.vrate_fpm, "squawk": sv.squawk, "ground": sv.on_ground,
                        "src": sv.position_source, "age": round(now_ts - sv.ts, 0),
                        "trust": round(self.engine.trust.score(sv.icao24), 2),
                        "sev": top.severity.value if top else None, "rules": sorted({f.rule_id for f in fs}),
                        "emergency": emergency, "injected": sv.icao24 in self.injected_ids,
                    })
            ranked = sorted(self.engine.findings, key=lambda f: f.risk_score, reverse=True)[:60]
            return {
                "mode": self.mode, "provider": self.provider, "region": self.region, "demo": self.demo,
                "batch_ts": b.ts if b else None, "batch_region": b.region if b else None, "batches": self.batches,
                "uptime_s": round(time.time() - self.started_at), "feed_latency_ms": self.feed_latency_ms,
                "last_ingest_age_s": round(time.time() - self.last_ingest_wall, 1) if self.last_ingest_wall else None,
                "center": self.center, "aircraft": aircraft,
                "kpis": {
                    "tracked": len(aircraft), "airborne": sum(1 for a in aircraft if not a["ground"]),
                    "unique_aircraft": s["unique_aircraft"], "findings_total": s["findings_total"],
                    "by_severity": s["by_severity"], "by_rule": s["by_rule"],
                    "compliance": s.get("adsb_compliance_rate"), "compliance_fixes": s.get("adsb_airborne_fixes"),
                    "low_trust": s["low_trust_aircraft"], "emergencies": [a for a in aircraft if a["emergency"]],
                    "alerts_sent": s.get("alerts_sent", 0),
                },
                "ranked": [self._finding_json(f) for f in ranked],
                "events": list(self.events)[:60],
                "counts": [{"ts": t, "region": r, "n": n} for t, r, n in self.counts],
                "injections": [{"kind": i.kind, "icao24": i.icao24, "remaining": i.remaining, "label": i.label} for i in self.injections],
                "injection_kinds": INJECTION_KINDS,
                "metars": self.metars,
                "faa_updated": self.faa_status.get("updated"),
                "phases": self.eco.get("phases", {}),
                "errors": list(self.errors),
            }

    def flights(self, **filters: Any) -> dict[str, Any]:
        """Every aircraft in the current picture with enrichment, filtered and sorted (server-side)."""
        snap = self.snapshot()
        rows = snap["aircraft"]
        f = {k: v for k, v in filters.items() if v}
        band = f.get("altband")
        bands = {"ground": (None, None), "low": (0, 10000), "mid": (10000, 25000), "high": (25000, 100000)}
        out = []
        q = (f.get("q") or "").lower()
        for a in rows:
            if f.get("operator") and a["operator_code"] != f["operator"]:
                continue
            if f.get("category") and a["operator_cat"] != f["category"]:
                continue
            if f.get("type_cat") and a["type_cat"] != f["type_cat"]:
                continue
            if f.get("phase") and a["phase"] != f["phase"]:
                continue
            if f.get("airport") and a["airport"] != f["airport"].upper():
                continue
            if f.get("severity") and a["sev"] != f["severity"]:
                continue
            if f.get("source") and (a["src"] or "") != f["source"]:
                continue
            if band == "ground" and not a["ground"]:
                continue
            if band in ("low", "mid", "high"):
                lo, hi = bands[band]
                if a["ground"] or a["alt"] is None or not (lo <= a["alt"] < hi):
                    continue
            if q and q not in f"{a['callsign'] or ''} {a['icao24']} {a['reg'] or ''} {a['type'] or ''} {a['operator'] or ''} {a['airport'] or ''}".lower():
                continue
            out.append(a)
        sort = f.get("sort") or "alt"
        desc = not sort.startswith("+")
        key = sort.lstrip("+-")
        out.sort(key=lambda a: (a.get(key) is None, a.get(key) if a.get(key) is not None else 0), reverse=desc)
        facets = {
            "operators": sorted({(a["operator_code"], a["operator"]) for a in rows if a["operator_code"]}, key=lambda x: x[1] or ""),
            "phases": sorted({a["phase"] for a in rows if a["phase"]}),
            "airports": sorted({a["airport"] for a in rows if a["airport"]}),
            "type_cats": sorted({a["type_cat"] for a in rows if a["type_cat"]}),
            "categories": sorted({a["operator_cat"] for a in rows if a["operator_cat"]}),
            "sources": sorted({a["src"] for a in rows if a["src"]}),
            "severities": [s.value for s in SEVERITY_ORDER],
        }
        limit = int(f.get("limit") or 1000)
        return {"total": len(out), "items": out[:limit], "facets": facets, "batch_ts": snap["batch_ts"], "provider": snap["provider"]}

    def aircraft_detail(self, icao24: str) -> dict[str, Any] | None:
        with self.lock:
            b = self.last_batch
            sv = next((x for x in b.states if x.icao24 == icao24), None) if b else None
            fs = [f for f in self.engine.findings if f.icao24 == icao24]
            trail = [{"ts": t, "lat": la, "lon": lo, "alt": al} for t, la, lo, al in self.trails.get(icao24, [])]
            if sv is None and not fs and not trail:
                return None
            state = sv.model_dump(exclude={"raw"}) if sv else None
            e = self.enriched.get(icao24)
            return {
                "icao24": icao24, "state": state, "trust": round(self.engine.trust.score(icao24), 2), "trail": trail,
                "enrichment": e.to_dict() if e else None,
                "findings": [self._finding_json(f) for f in sorted(fs, key=lambda f: f.ts, reverse=True)][:30],
                "injected": icao24 in self.injected_ids,
                "playbooks": {f.rule_id: playbook_for(f.rule_id).__dict__ for f in fs if playbook_for(f.rule_id)},
            }
