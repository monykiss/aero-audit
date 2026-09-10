"""The local app: versioned JSON API, static front end, jobs, sources, settings, reports, docs.

Everything is standard library on the server side. Add an endpoint with `@router.route(...)`,
a background task with an entry in `JOB_TYPES`, a page in static/app.js.
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import threading
import time
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__, provenance, tuning
from ..audit.findings import SEVERITY_ORDER
from ..audit.report import write_reports
from ..audit.rules import RULE_CATALOG
from ..impact import estimate_holding_impact
from ..ingest.replay import RECORDING_SUFFIXES, iter_recording, open_recording, recording_stem
from ..knowledge import AIRPORTS
from ..risk import assess
from ..security.playbooks import PLAYBOOKS, playbook_for
from ..security.threats import coverage_matrix, load_evaluation
from .audit import AuditLog
from .jobs import Job, JobManager
from .router import Router
from .security import Denied, Guard, safe_path, safe_url
from .sources import (
    RECORDINGS_DIR,
    SAMPLES_DIR,
    SourceManager,
    load_settings,
    region_catalog,
    save_settings,
)
from .tour import DemoTour

STATIC = Path(__file__).with_name("static")
REPORTS = Path("reports")
DOCS = Path("docs")
MODELS = Path("models")
LOGS = Path("logs")
DATA = Path("data")
INVENTORY_CACHE = Path("data/app/inventory.json")
RECORDING_ROOTS = (RECORDINGS_DIR, SAMPLES_DIR)

router = Router()


class App:
    def __init__(self, guard: Guard | None = None) -> None:
        self.guard = guard or Guard()
        self.settings = load_settings()
        self.audit = AuditLog()
        self.sources = SourceManager(self.settings)
        self.jobs = JobManager(self._job_types(), on_finish=lambda j: self.audit.record(
            "job.finish", actor="system", job=j.id, type=j.type, status=j.status, error=j.error))
        self.tour = DemoTour(lambda: self.sources.state, on_inject=lambda kind, icao, n, narration: self.audit.record(
            "inject", actor="tour", kind=kind, icao24=icao, polls=n))
        self.audit.record("app.start", actor="system", version=__version__, security_mode=self.guard.mode)
        self.started = time.time()
        self._inventory: dict[str, dict[str, Any]] = {}
        self._load_inventory_cache()

    # ---- input validation --------------------------------------------------------------------
    @staticmethod
    def recording_path(value: Any) -> Path:
        """A recording parameter may only name a file under data/recordings or data/samples."""
        return safe_path(value, RECORDING_ROOTS, RECORDING_SUFFIXES)

    def source_description(self) -> dict[str, Any]:
        p = self.sources.params
        if p.get("mode") == "replay":
            return provenance.describe_source(recording=p.get("recording"))
        return provenance.describe_source(**{k: v for k, v in p.items() if k in ("mode", "provider", "region", "radius", "interval")})

    # ---- inventory ---------------------------------------------------------------------------
    def _load_inventory_cache(self) -> None:
        try:
            self._inventory = json.loads(INVENTORY_CACHE.read_text())
        except (OSError, ValueError):
            self._inventory = {}

    def recordings(self) -> list[dict[str, Any]]:
        out = []
        changed = False
        files = sorted(RECORDINGS_DIR.glob("*.jsonl")) + sorted(RECORDINGS_DIR.glob("*.jsonl.gz")) + sorted(SAMPLES_DIR.glob("*.jsonl.gz"))
        for f in files:
            key = f"{f.name}:{f.stat().st_mtime_ns}:{f.stat().st_size}"
            if key not in self._inventory:
                out_ = self._summarize(f)
                self._inventory = {k: v for k, v in self._inventory.items() if not k.startswith(f.name + ":")}
                self._inventory[key] = out_
                changed = True
            d = dict(self._inventory[key])
            d["path"] = str(f)
            d["sample"] = f.parent == SAMPLES_DIR
            out.append(d)
        if changed:
            INVENTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            INVENTORY_CACHE.write_text(json.dumps(self._inventory))
        return sorted(out, key=lambda d: d.get("last_ts") or 0, reverse=True)

    @staticmethod
    def _summarize(f: Path) -> dict[str, Any]:
        polls = sv = 0
        ac: set[str] = set()
        regions: set[str] = set()
        first = last = None
        prov = "?"
        for b in iter_recording(f):
            polls += 1
            sv += len(b)
            ac.update(x.icao24 for x in b.states)
            regions.add(b.region)
            prov = b.provider
            first = b.ts if first is None else first
            last = b.ts
        special = any(t in f.name for t in ("_mil_", "_ladd_", "_pia_", "synthetic"))
        return {"file": f.name, "provider": prov, "regions": sorted(regions), "polls": polls, "state_vectors": sv,
                "aircraft": len(ac), "first_ts": first, "last_ts": last,
                "span_min": round((last - first) / 60, 1) if first and last else 0, "size_mb": round(f.stat().st_size / 1e6, 1),
                "special": special}

    # ---- jobs ------------------------------------------------------------------------------
    def _job_types(self) -> dict[str, Any]:
        return {
            "capture": self._job_capture, "audit_session": self._job_audit_session, "audit_recording": self._job_audit_recording,
            "train": self._job_train, "evaluate": self._job_evaluate, "prune": self._job_prune, "docs_build": self._job_docs,
            "corroborate": self._job_corroborate,
        }

    def _job_capture(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        import asyncio
        from datetime import UTC, datetime

        from ..config import parse_regions
        from ..ingest import make_provider
        from ..stream import JsonlRecorder, stream_batches

        provider, region = p.get("provider", "adsblol"), p.get("region", "nyc")
        radius, interval, seconds = p.get("radius"), float(p.get("interval", 12)), float(p.get("seconds", 600))
        regions = parse_regions(region, float(radius) if radius else None)
        label = "+".join(r.key for r in regions)
        path = Path("data/recordings") / f"{provider}_{label}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
        rec = JsonlRecorder(path)
        t0 = time.time()

        async def main() -> None:
            prov = make_provider(provider)
            try:
                async for b in stream_batches(prov, regions, interval, seconds, rec):
                    job.progress = min(1.0, (time.time() - t0) / seconds)
                    job.say(f"{b.region}: {len(b)} aircraft")
                    if job.stop.is_set():
                        break
            finally:
                await prov.aclose()
                rec.close()

        asyncio.run(main())
        return {"recording": str(path), "polls": rec.batches}

    def _job_audit_session(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        st = self.sources.state
        if st is None:
            raise RuntimeError("no active source")
        name = "".join(c for c in str(p.get("name") or f"session_{st.region}") if c.isalnum() or c in "-_.")[:80] or "session"
        with st.lock:
            jp, mp, hp = write_reports(st.engine, REPORTS, name, source=self.source_description())
        job.say(f"wrote {hp.name} (+ manifest)")
        return {"json": str(jp), "md": str(mp), "html": str(hp), "name": hp.stem}

    def _job_audit_recording(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from .sources import build_engine

        path = self.recording_path(p.get("recording"))
        with open_recording(path) as fh:
            total = sum(1 for _ in fh)
        eng = build_engine(self.settings)
        for err in self.settings.pop("_errors", []):
            job.say(err)
        for i, b in enumerate(iter_recording(path), 1):
            eng.process_batch(b)
            job.progress = i / max(total, 1)
            if job.stop.is_set():
                break
        jp, mp, hp = write_reports(eng, REPORTS, recording_stem(path), source=provenance.describe_source(recording=path))
        s = eng.summary()
        job.say(f"{s['unique_aircraft']} aircraft, {s['findings_total']} findings -> {hp.name} (+ manifest)")
        return {"json": str(jp), "md": str(mp), "html": str(hp), "name": hp.stem, "summary": {k: s[k] for k in ("unique_aircraft", "findings_total", "by_severity")}}

    def _job_train(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from ..ml.train import train

        recs = [str(self.recording_path(r)) for r in (p.get("recordings") or [])] or [r["path"] for r in self.recordings() if not r["special"]]
        if not recs:
            raise RuntimeError("no civil recordings to train on")
        out = safe_path(self.settings.get("model") or "models/kinematic_iforest.joblib", [MODELS], (".joblib",), must_exist=False)
        job.say(f"training on {len(recs)} recordings -> {out}")
        stats = train(recs, out, float(p.get("contamination", 0.01)))
        job.say(f"{stats['samples_total']} rows, holdout flag rate {stats['flag_rate_holdout']:.2%}; registered sha256 {stats['sha256'][:12]}")
        return {k: stats[k] for k in ("samples_total", "aircraft_total", "flag_rate_holdout", "model_path", "model_card", "sha256")}

    def _job_evaluate(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from ..ml import verify_model
        from ..ml.evaluate import evaluate, write_evaluation

        rec = str(self.recording_path(p["recording"])) if p.get("recording") else next(
            (r["path"] for r in self.recordings() if not r["special"] and r["provider"] == "adsblol"), None)
        if not rec:
            raise RuntimeError("no recording to evaluate on")
        model = None
        mp = Path(self.settings.get("model") or "")
        if mp.is_file():
            v = verify_model(mp)
            if v["match"] or self.settings.get("allow_unverified_model"):
                model = str(mp)
            else:
                job.say(f"model {mp} skipped: not verified against {v['registry']}")
        job.say(f"evaluating on {Path(rec).name}")
        rep = evaluate(rec, model, int(p.get("targets", 25)), int(p.get("seed", 42)), None, int(p.get("max_batches", 60)),
                       allow_unverified_model=bool(self.settings.get("allow_unverified_model")))
        jp, mp_ = write_evaluation(rep)
        return {"json": str(jp), "md": str(mp_), "recall": {r.name: r.recall for r in rep.results}, "precision": rep.rule_precision}

    def _job_prune(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        days, apply = int(p.get("days", self.settings.get("retention_days", 30))), bool(p.get("apply", False))
        cutoff = time.time() - days * 86400
        old = [f for f in sorted(Path("data/recordings").glob("*.jsonl")) if f.stat().st_mtime < cutoff]
        for f in old:
            job.say(f"{'deleting' if apply else 'would delete'} {f.name}")
            if apply:
                f.unlink()
        return {"files": [f.name for f in old], "deleted": apply}

    def _job_docs(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from ..docs_build import build

        return {"written": [str(x) for x in build()]}

    def _job_corroborate(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from ..config import parse_regions
        from ..ingest import make_provider
        from ..security import corroborate

        reg = parse_regions(p.get("region", "nyc"), float(p["radius"]) if p.get("radius") else None)[0]
        pa, pb = make_provider(p.get("primary", "adsblol")), make_provider(p.get("secondary", "opensky"))
        seconds, interval = float(p.get("seconds", 75)), float(p.get("interval", 25))
        totals = {"matched": 0, "only_primary": 0, "only_secondary": 0, "disagreements": 0}
        seps: list[float] = []
        findings = []

        async def main() -> None:
            start = time.time()
            try:
                while time.time() - start < seconds and not job.stop.is_set():
                    t0 = time.time()
                    ba, bb = await asyncio.gather(pa.fetch(reg), pb.fetch(reg), return_exceptions=True)
                    if isinstance(ba, Exception) or isinstance(bb, Exception):
                        job.say(f"fetch error: {ba if isinstance(ba, Exception) else bb}")
                    else:
                        res = corroborate(ba, bb)
                        for k in totals:
                            totals[k] += getattr(res, k)
                        seps.extend(res.separations_nm)
                        findings.extend(res.findings)
                        job.say(f"matched {res.matched} disagree {res.disagreements} median {res.summary()['median_sep_nm']} nm")
                    job.progress = min(1.0, (time.time() - start) / seconds)
                    await asyncio.sleep(max(0.0, interval - (time.time() - t0)))
            finally:
                await pa.aclose()
                await pb.aclose()

        asyncio.run(main())
        seps.sort()
        st = self.sources.state
        if st is not None and findings:
            with st.lock:
                st.engine.findings.extend(findings)
                for f in findings:
                    st.events.appendleft(st._finding_json(f))
        return {**totals, "median_sep_nm": round(seps[len(seps) // 2], 3) if seps else None,
                "p95_sep_nm": round(seps[int(0.95 * (len(seps) - 1))], 3) if seps else None, "findings": len(findings)}

    # ---- settings --------------------------------------------------------------------------
    def settings_view(self) -> dict[str, Any]:
        import math

        def _finite(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

        def _clean(v: Any) -> Any:  # browsers reject Infinity/NaN in JSON; show non-numeric tunables as text
            return v if _finite(v) else str(v)

        rows = [{"section": s, "key": k, "value": _clean(v), "overridden": o, "editable": _finite(v)}
                for s, k, v, o in tuning.effective()]
        from ..ml import verify_model

        model = self.settings.get("model") or ""
        return {"tunables": rows, "app": {k: self.settings.get(k) for k in ("demo", "alert_log", "alert_webhook", "retention_days", "model", "watchlist", "allow_unverified_model")},
                "model_integrity": verify_model(model) if model else None,
                "aero_toml": str(tuning.DEFAULT_PATH), "aero_toml_exists": tuning.DEFAULT_PATH.exists()}

    @staticmethod
    def validate_app_settings(app: dict[str, Any]) -> dict[str, Any]:
        """Each app setting has a type and, for paths, a directory it must stay inside."""
        out: dict[str, Any] = {}
        for k, v in app.items():
            if k in ("demo", "allow_unverified_model"):
                out[k] = bool(v)
            elif k == "retention_days":
                out[k] = max(1, min(int(v), 3650))
            elif k == "alert_webhook":
                out[k] = safe_url(v)
            elif k == "alert_log":
                out[k] = str(safe_path(v, [LOGS, DATA], (".jsonl",), must_exist=False)) if str(v or "").strip() else ""
            elif k == "model":
                out[k] = str(safe_path(v, [MODELS], (".joblib",), must_exist=False)) if str(v or "").strip() else ""
            elif k == "watchlist":
                out[k] = str(safe_path(v, [DATA], (".json",), must_exist=False)) if str(v or "").strip() else ""
            # unknown keys are dropped
        return out

    def settings_update(self, body: dict[str, Any]) -> dict[str, Any]:
        if "app" in body:
            self.settings.update(self.validate_app_settings(dict(body["app"] or {})))
            save_settings(self.settings)
        if "tunables" in body:
            import tomllib

            path = tuning.DEFAULT_PATH
            current = tomllib.loads(path.read_text()) if path.exists() else {}
            for section, kv in body["tunables"].items():
                allowed = tuning.tunables(section)
                for k, v in kv.items():
                    if k not in allowed or not isinstance(allowed[k], (int, float)) or isinstance(allowed[k], bool):
                        raise KeyError(f"not an editable tunable: [{section}] {k}")
                    current.setdefault(section, {})[k] = type(allowed[k])(v)
            lines = ["# aero.toml: threshold overrides written by the app; edit freely.", ""]
            for section, kv in current.items():
                lines.append(f"[{section}]")
                lines += [f"{k} = {json.dumps(v)}" for k, v in kv.items()]
                lines.append("")
            path.write_text("\n".join(lines))
            tuning.apply(path)
        return self.settings_view()

    # ---- reports / docs --------------------------------------------------------------------
    @staticmethod
    def reports() -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for f in REPORTS.glob("*"):
            if f.suffix not in (".html", ".md", ".json") or f.name == ".gitkeep":
                continue
            stem, kind = (f.stem[:-len(".manifest")], "manifest") if f.name.endswith(".manifest.json") else (f.stem, f.suffix[1:])
            g = groups.setdefault(stem, {"name": stem, "mtime": f.stat().st_mtime, "files": {}})
            g["files"][kind] = f"/reports/{f.name}"
            g["mtime"] = max(g["mtime"], f.stat().st_mtime)
        kinds = {"evaluation": "evaluation", "risk_assessment": "risk", "corroborate": "corroboration", "session": "session audit"}
        for g in groups.values():
            g["kind"] = next((v for k, v in kinds.items() if g["name"].startswith(k)), "audit")
        return sorted(groups.values(), key=lambda g: g["mtime"], reverse=True)

    def info(self) -> dict[str, Any]:
        model = None
        try:
            entries = json.loads(Path("models/registry.json").read_text())
            e = entries[-1]
            model = {k: e.get(k) for k in ("model_path", "rows", "aircraft", "holdout_flag_rate", "trained_at", "sha256")}
            model["evaluation"] = e.get("evaluation")
        except (OSError, ValueError, IndexError):
            pass  # no registry yet, or an unreadable one: the app shows "no model" rather than failing
        tour = self.tour.status()
        tour.pop("script", None)
        return {
            "version": __version__, "uptime_s": round(time.time() - self.started), "source": self.sources.status(),
            "model": model, "model_file": Path(self.settings.get("model") or "").is_file(),
            "recordings": len(list(RECORDINGS_DIR.glob("*.jsonl"))) + len(list(RECORDINGS_DIR.glob("*.jsonl.gz"))),
            "samples": len(list(SAMPLES_DIR.glob("*.jsonl.gz"))), "reports": len(self.reports()),
            "jobs_running": sum(1 for j in self.jobs.jobs.values() if j.status == "running"),
            "settings": {k: self.settings.get(k) for k in ("demo", "retention_days")},
            "evaluation_exists": Path("models/evaluation.json").is_file(),
            "security": self.guard.describe(), "tour": tour,
            "audit_chain": {"entries": len(self.audit), "head": self.audit.head},
        }


# ---- routes ----------------------------------------------------------------------------------
def _state_or_inactive(app: App) -> dict[str, Any]:
    st = app.sources.state
    return st.snapshot() if st else {"active": False}


@router.route("GET", "/api/v1/app")
def r_app(app: App, req: Any) -> Any:
    return app.info()


@router.route("GET", "/api/v1/regions")
def r_regions(app: App, req: Any) -> Any:
    return region_catalog()


@router.route("GET", "/api/v1/recordings")
def r_recordings(app: App, req: Any) -> Any:
    return app.recordings()


@router.route("POST", "/api/v1/source/start")
def r_source_start(app: App, req: Any) -> Any:
    b = req["body"]
    if b.get("mode") == "live":
        provider, region = str(b.get("provider", "adsblol")), str(b.get("region", "nyc"))
        if provider not in ("adsblol", "opensky"):
            return ({"error": f"unknown provider {provider}"}, 400)
        app.audit.record("source.start", mode="live", provider=provider, region=region, radius=b.get("radius"),
                         interval=b.get("interval"), demo=bool(b.get("demo", True)))
        app.sources.start_live(provider, region, float(b["radius"]) if b.get("radius") else None, float(b.get("interval", 12)),
                               b.get("demo"), bool(b.get("record", True)))
    else:
        try:
            rec = app.recording_path(b.get("recording"))
        except FileNotFoundError as e:
            return ({"error": str(e)}, 404)
        except PermissionError as e:
            app.audit.record("source.start.refused", recording=str(b.get("recording"))[:200], reason=str(e))
            return ({"error": str(e)}, 400)
        app.audit.record("source.start", mode="replay", recording=str(rec), speed=b.get("speed", 8), demo=bool(b.get("demo", True)))
        app.sources.start_replay(rec, float(b.get("speed", 8)), b.get("demo"))
    app.settings["last_source"] = app.sources.params
    save_settings(app.settings)
    return {"ok": True, "source": app.sources.status()}


@router.route("GET", "/api/v1/security")
def r_security(app: App, req: Any) -> Any:
    return app.guard.describe()


@router.route("GET", "/api/v1/tour")
def r_tour(app: App, req: Any) -> Any:
    return app.tour.status()


@router.route("POST", "/api/v1/tour")
def r_tour_ctl(app: App, req: Any) -> Any:
    action = req["body"].get("action", "start")
    if action == "start":
        st = app.sources.state
        if st is None:
            return ({"error": "start a source first"}, 400)
        if not st.demo:
            return ({"error": "demo mode is off for this source"}, 403)
        app.tour.start()
    elif action == "stop":
        app.tour.stop()
        if app.sources.state:
            app.sources.state.clear_injections()
    else:
        return ({"error": "action must be start or stop"}, 400)
    app.audit.record(f"tour.{action}")
    return app.tour.status()


@router.route("POST", "/api/v1/source/stop")
def r_source_stop(app: App, req: Any) -> Any:
    app.audit.record("source.stop", label=app.sources.label)
    app.sources.stop()
    return {"ok": True}


@router.route("GET", "/api/v1/state")
def r_state(app: App, req: Any) -> Any:
    return _state_or_inactive(app)


@router.route("GET", "/api/v1/aircraft/{icao}")
def r_aircraft(app: App, req: Any) -> Any:
    st = app.sources.state
    d = st.aircraft_detail(req["params"]["icao"].lower()) if st else None
    return d if d else ({"error": "unknown aircraft"}, 404)


@router.route("GET", "/api/v1/findings")
def r_findings(app: App, req: Any) -> Any:
    st = app.sources.state
    if not st:
        return {"total": 0, "items": []}
    q = req["query"]
    sev, rule, cat, text = q.get("severity"), q.get("rule"), q.get("category"), (q.get("q") or "").lower()
    limit = int(q.get("limit") or 500)
    with st.lock:
        fs = list(st.engine.findings)
    out = []
    for f in sorted(fs, key=lambda f: f.risk_score, reverse=True):
        if sev and f.severity.value != sev:
            continue
        if rule and f.rule_id != rule:
            continue
        if cat and f.category.value != cat:
            continue
        if text and text not in f"{f.icao24} {f.callsign or ''} {f.title} {f.rule_id}".lower():
            continue
        out.append(st._finding_json(f))
    return {"total": len(out), "items": out[:limit],
            "rules": sorted({f.rule_id for f in fs}), "severities": [s.value for s in SEVERITY_ORDER]}


@router.route("GET", "/api/v1/findings.csv")
def r_findings_csv(app: App, req: Any) -> Any:
    st = app.sources.state
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["severity", "rule", "category", "icao24", "callsign", "time", "risk", "occurrences", "title", "evidence"])
    if st:
        with st.lock:
            for f in sorted(st.engine.findings, key=lambda f: f.risk_score, reverse=True):
                w.writerow([f.severity.value, f.rule_id, f.category.value, f.icao24, f.callsign, f.ts, f.risk_score, f.occurrences,
                            f.title, json.dumps(f.evidence, default=str)])
    return (buf.getvalue().encode(), "text/csv; charset=utf-8")


@router.route("GET", "/api/v1/risk")
def r_risk(app: App, req: Any) -> Any:
    st = app.sources.state
    return assess(st.engine.summary() if st else None)


@router.route("GET", "/api/v1/threats")
def r_threats(app: App, req: Any) -> Any:
    return coverage_matrix(load_evaluation())


@router.route("GET", "/api/v1/evaluation")
def r_eval(app: App, req: Any) -> Any:
    return load_evaluation() or {}


@router.route("GET", "/api/v1/impact")
def r_impact(app: App, req: Any) -> Any:
    st = app.sources.state
    return estimate_holding_impact(st.engine.findings if st else []).as_dict()


@router.route("GET", "/api/v1/model")
def r_model(app: App, req: Any) -> Any:
    return app.info()["model"] or {}


@router.route("GET", "/api/v1/rules")
def r_rules(app: App, req: Any) -> Any:
    return [{"rule": rid, "category": cat, "description": desc, "playbook": bool(playbook_for(rid))} for rid, (cat, desc) in RULE_CATALOG.items()]


@router.route("GET", "/api/v1/playbooks")
def r_playbooks(app: App, req: Any) -> Any:
    return {rid: pb.__dict__ for rid, pb in PLAYBOOKS.items()}


@router.route("GET", "/api/v1/playbook/{rule}")
def r_playbook(app: App, req: Any) -> Any:
    pb = playbook_for(req["params"]["rule"].upper())
    return pb.__dict__ if pb else ({"error": "no playbook"}, 404)


@router.route("POST", "/api/v1/inject")
def r_inject(app: App, req: Any) -> Any:
    st = app.sources.state
    if not st:
        return ({"error": "no active source"}, 400)
    if not st.demo:
        return ({"error": "demo mode is off"}, 403)
    b = req["body"]
    inj = st.inject(b.get("kind", ""), b.get("icao24") or None, int(b.get("batches", 6)))
    app.audit.record("inject", kind=inj.kind, icao24=inj.icao24, polls=inj.remaining)
    return {"kind": inj.kind, "icao24": inj.icao24, "remaining": inj.remaining, "label": inj.label}


@router.route("POST", "/api/v1/clear")
def r_clear(app: App, req: Any) -> Any:
    app.audit.record("inject.clear")
    if app.sources.state:
        app.sources.state.clear_injections()
    return {"ok": True}


@router.route("GET", "/api/v1/reports")
def r_reports(app: App, req: Any) -> Any:
    return app.reports()


# ---- ecosystem ---------------------------------------------------------------------------------
@router.route("GET", "/api/v1/ecosystem")
def r_ecosystem(app: App, req: Any) -> Any:
    st = app.sources.state
    return st.eco if (st and st.eco) else {"active": False, "airports": [], "operators": [], "types": [], "phases": {}, "categories": {}, "faa_status": []}


@router.route("GET", "/api/v1/flights")
def r_flights(app: App, req: Any) -> Any:
    st = app.sources.state
    if not st:
        return {"total": 0, "items": [], "facets": {}, "active": False}
    return st.flights(**req["query"])


@router.route("GET", "/api/v1/flights.csv")
def r_flights_csv(app: App, req: Any) -> Any:
    st = app.sources.state
    cols = ["callsign", "icao24", "reg", "operator_code", "operator", "operator_cat", "type", "type_name", "type_cat", "phase", "airport",
            "airport_nm", "lat", "lon", "alt", "agl", "gs", "track", "vrate", "squawk", "ground", "src", "trust", "sev", "rules", "ts"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    if st:
        for a in st.flights(**{**req["query"], "limit": "100000"})["items"]:
            w.writerow([",".join(a[c]) if c == "rules" else a.get(c) for c in cols])
    return (buf.getvalue().encode(), "text/csv; charset=utf-8")


@router.route("GET", "/api/v1/airports")
def r_airports(app: App, req: Any) -> Any:
    st = app.sources.state
    active = {r["icao"]: r for r in (st.eco.get("airports", []) if st and st.eco else [])}
    status = defaultdict(list)
    for rec in (st.faa_status.get("entries", []) if st else []):
        status[rec["airport"]].append(rec)
    metars = {m["station"]: m for m in (st.metars if st else [])}
    rows = []
    for a in AIRPORTS.values():
        r = active.get(a.icao) or {"icao": a.icao, "iata": a.iata, "name": a.name, "city": a.city, "country": a.country, "lat": a.lat, "lon": a.lon,
                                   "nearby": 0, "ground": 0, "departing": 0, "arriving": 0, "approach": 0, "terminal": 0, "overhead": 0,
                                   "holds": 0, "emergencies": 0, "findings": 0, "worst": None, "faa": [{k: v for k, v in x.items() if k != "airport"} for x in status.get(a.iata, [])]}
        r = dict(r)
        r["elev_ft"] = a.elev_ft
        r["major"] = a.major
        r["metar"] = metars.get(a.icao)
        rows.append(r)
    country = req["query"].get("country")
    if country:
        rows = [r for r in rows if r["country"] == country.upper()]
    rows.sort(key=lambda r: (-r["nearby"], r["icao"]))
    return {"items": rows, "faa_updated": st.faa_status.get("updated") if st else None, "active": bool(st)}


@router.route("GET", "/api/v1/airports/{icao}")
def r_airport(app: App, req: Any) -> Any:
    icao = req["params"]["icao"].upper()
    a = AIRPORTS.get(icao)
    if not a:
        return ({"error": "unknown airport"}, 404)
    st = app.sources.state
    flights = st.flights(airport=icao, limit="500")["items"] if st else []
    row = next((r for r in (st.eco.get("airports", []) if st and st.eco else []) if r["icao"] == icao), None)
    metar = next((m for m in (st.metars if st else []) if m["station"] == icao), None)
    faa = [x for x in (st.faa_status.get("entries", []) if st else []) if x["airport"] == a.iata]
    return {"airport": a.__dict__, "activity": row, "flights": flights, "metar": metar, "faa": faa}


@router.route("GET", "/api/v1/operators")
def r_operators(app: App, req: Any) -> Any:
    st = app.sources.state
    rows = st.eco.get("operators", []) if st and st.eco else []
    cat = req["query"].get("category")
    if cat:
        rows = [r for r in rows if r["category"] == cat]
    return {"items": rows, "types": st.eco.get("types", []) if st and st.eco else [], "categories": sorted({r["category"] for r in rows})}


@router.route("GET", "/api/v1/faa")
def r_faa(app: App, req: Any) -> Any:
    st = app.sources.state
    if st and st.faa_status.get("updated"):
        return st.faa_status
    import asyncio

    from ..ingest.faa_status import fetch_status

    try:
        data = asyncio.run(fetch_status())
    except Exception as e:  # noqa: BLE001
        return {"updated": None, "entries": [], "error": f"{type(e).__name__}: {e}"}
    if st:
        with st.lock:
            st.faa_status = data
    return data


@router.route("GET", "/api/v1/audit")
def r_audit(app: App, req: Any) -> Any:
    q = req["query"]
    return {"items": app.audit.entries(int(q.get("limit") or 300), q.get("action"), q.get("actor"), q.get("q")),
            "actions": app.audit.actions(), "total": len(app.audit)}


@router.route("GET", "/api/v1/audit.csv")
def r_audit_csv(app: App, req: Any) -> Any:
    return (app.audit.to_csv().encode(), "text/csv; charset=utf-8")


@router.route("GET", "/api/v1/audit/verify")
def r_audit_verify(app: App, req: Any) -> Any:
    return app.audit.verify()


@router.route("GET", "/api/v1/reports/{name}/manifest")
def r_report_manifest(app: App, req: Any) -> Any:
    from ..provenance import verify_manifest

    name = req["params"]["name"]
    mp = REPORTS / f"{name}.manifest.json"
    if "/" in name or ".." in name or not mp.is_file():
        return ({"error": "no manifest"}, 404)
    return verify_manifest(mp)


@router.route("GET", "/api/v1/jobs")
def r_jobs(app: App, req: Any) -> Any:
    return app.jobs.list()


@router.route("POST", "/api/v1/jobs")
def r_jobs_submit(app: App, req: Any) -> Any:
    b = req["body"]
    job = app.jobs.submit(b.get("type", ""), b.get("params") or {})
    app.audit.record("job.submit", job=job.id, type=job.type, params=job.params)
    return job.to_dict()


@router.route("GET", "/api/v1/jobs/{id}")
def r_job(app: App, req: Any) -> Any:
    j = app.jobs.get(req["params"]["id"])
    return j.to_dict() if j else ({"error": "no such job"}, 404)


@router.route("POST", "/api/v1/jobs/{id}/cancel")
def r_job_cancel(app: App, req: Any) -> Any:
    return {"ok": app.jobs.cancel(req["params"]["id"])}


@router.route("GET", "/api/v1/settings")
def r_settings(app: App, req: Any) -> Any:
    return app.settings_view()


@router.route("POST", "/api/v1/settings")
def r_settings_update(app: App, req: Any) -> Any:
    app.audit.record("settings.update", **req["body"])
    return app.settings_update(req["body"])


@router.route("GET", "/api/v1/docs")
def r_docs(app: App, req: Any) -> Any:
    files = sorted(DOCS.glob("*.md")) + sorted((DOCS / "generated").glob("*.md")) + [Path("README.md")]
    return [{"name": str(f.relative_to(".")), "title": f.stem.replace("_", " ").title()} for f in files if f.is_file()]


@router.route("GET", "/api/v1/docs/{name}")
def r_doc(app: App, req: Any) -> Any:
    name = req["params"]["name"].replace("%2F", "/")
    p = Path(name)
    if p.is_absolute() or ".." in p.parts or p.suffix != ".md" or not p.is_file():
        return ({"error": "not found"}, 404)
    if not (p.resolve().is_relative_to(DOCS.resolve()) or p == Path("README.md")):
        return ({"error": "not found"}, 404)
    return {"name": name, "text": p.read_text()}


# ---- HTTP glue -------------------------------------------------------------------------------
def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "aero-audit"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in app.guard.response_headers(report=urlparse(self.path).path.startswith("/reports/")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, root: Path, rel: str, ctype: str | None = None) -> None:
            """Serve one file from under ``root``; anything that normalises outside it is a 404."""
            base = os.path.realpath(root)
            target = os.path.normpath(os.path.join(base, rel.lstrip("/")))
            if not target.startswith(base + os.sep) or not os.path.isfile(target):
                self._send(404, b"not found", "text/plain")
                return
            with open(target, "rb") as fh:
                body = fh.read()
            self._send(200, body, ctype or mimetypes.guess_type(target)[0] or "application/octet-stream")

        def _dispatch(self, method: str) -> None:
            u = urlparse(self.path)
            path = u.path
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                app.guard.check(method, path, self.headers)
            except Denied as d:
                if d.status == 401:
                    app.audit.record("request.denied", actor="system", status=d.status, path=path[:120], reason=d.message)
                self._send(d.status, json.dumps({"error": d.message}).encode(), "application/json")
                return
            try:
                if method == "GET" and (path == "/" or path.startswith("/#")):
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                    return
                if method == "GET" and path.startswith("/static/"):
                    self._serve_file(STATIC, path[len("/static/"):])
                    return
                if method == "GET" and path.startswith("/reports/"):
                    rel = path[len("/reports/"):]
                    ctype = {".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".json": "application/json"}.get(Path(rel).suffix, "text/plain")
                    self._serve_file(REPORTS, rel, ctype)
                    return
                m = router.match(method, path)
                if not m:
                    self._send(404, json.dumps({"error": "not found"}).encode(), "application/json")
                    return
                handler, params = m
                body: dict[str, Any] = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    try:
                        parsed = json.loads(self.rfile.read(n) or b"{}") if n else {}
                    except ValueError:
                        self._send(400, json.dumps({"error": "body is not valid JSON"}).encode(), "application/json")
                        return
                    if not isinstance(parsed, dict):
                        self._send(400, json.dumps({"error": "body must be a JSON object"}).encode(), "application/json")
                        return
                    body = parsed
                result = handler(app, {"params": params, "query": query, "body": body})
                status = 200
                if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
                    result, status = result
                if isinstance(result, tuple) and isinstance(result[0], bytes):
                    self._send(status, result[0], result[1])
                    return
                self._send(status, json.dumps(result, default=str).encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

    return Handler


def run_app(port: int = 8787, host: str = "127.0.0.1", open_browser: bool = True, block: bool = True,
            preset: dict[str, Any] | None = None, token: str | None = None, allow_unauthenticated: bool = False,
            allowed_hosts: tuple[str, ...] = (), tour: bool = False) -> tuple[App, ThreadingHTTPServer]:
    guard = Guard(host, token, allow_unauthenticated, allowed_hosts)
    app = App(guard)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))  # bind first, serve after the preset is running
    if preset:
        if preset.get("mode") == "live":
            app.sources.start_live(preset.get("provider", "adsblol"), preset.get("region", "nyc"), preset.get("radius"),
                                   float(preset.get("interval", 12)), preset.get("demo"))
        elif preset.get("recording"):
            app.sources.start_replay(preset["recording"], float(preset.get("speed", 8)), preset.get("demo"))
        app.audit.record("source.start", actor="system", **{k: str(v) for k, v in preset.items()})
    if tour and app.sources.state is not None:
        app.tour.start()
        app.audit.record("tour.start", actor="system")
    threading.Thread(target=httpd.serve_forever, daemon=True, name="aero-http").start()
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{httpd.server_address[1]}/"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    if block:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            app.sources.stop()
            httpd.shutdown()
    return app, httpd
