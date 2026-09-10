"""The local app: versioned JSON API, static front end, jobs, sources, settings, reports, docs.

Everything is standard library on the server side. Add an endpoint with `@router.route(...)`,
a background task with an entry in `JOB_TYPES`, a page in static/app.js.
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__, tuning
from ..audit.findings import SEVERITY_ORDER
from ..audit.report import write_reports
from ..audit.rules import RULE_CATALOG
from ..impact import estimate_holding_impact
from ..ingest.replay import iter_recording
from ..risk import assess
from ..security.playbooks import PLAYBOOKS, playbook_for
from ..security.threats import coverage_matrix, load_evaluation
from .jobs import Job, JobManager
from .router import Router
from .sources import SourceManager, load_settings, region_catalog, save_settings

STATIC = Path(__file__).with_name("static")
REPORTS = Path("reports")
DOCS = Path("docs")
INVENTORY_CACHE = Path("data/app/inventory.json")

router = Router()


class App:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.sources = SourceManager(self.settings)
        self.jobs = JobManager(self._job_types())
        self.started = time.time()
        self._inventory: dict[str, dict[str, Any]] = {}
        self._load_inventory_cache()

    # ---- inventory ---------------------------------------------------------------------------
    def _load_inventory_cache(self) -> None:
        try:
            self._inventory = json.loads(INVENTORY_CACHE.read_text())
        except (OSError, ValueError):
            self._inventory = {}

    def recordings(self) -> list[dict[str, Any]]:
        out = []
        changed = False
        for f in sorted(Path("data/recordings").glob("*.jsonl")):
            key = f"{f.name}:{f.stat().st_mtime_ns}:{f.stat().st_size}"
            if key not in self._inventory:
                out_ = self._summarize(f)
                self._inventory = {k: v for k, v in self._inventory.items() if not k.startswith(f.name + ":")}
                self._inventory[key] = out_
                changed = True
            d = dict(self._inventory[key])
            d["path"] = str(f)
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
        with st.lock:
            jp, mp, hp = write_reports(st.engine, REPORTS, p.get("name") or f"session_{st.region}")
        job.say(f"wrote {hp.name}")
        return {"json": str(jp), "md": str(mp), "html": str(hp), "name": hp.stem}

    def _job_audit_recording(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from .sources import build_engine

        path = Path(p["recording"])
        with open(path) as fh:
            total = sum(1 for _ in fh)
        eng = build_engine(self.settings)
        for i, b in enumerate(iter_recording(path), 1):
            eng.process_batch(b)
            job.progress = i / max(total, 1)
            if job.stop.is_set():
                break
        jp, mp, hp = write_reports(eng, REPORTS, path.stem)
        s = eng.summary()
        job.say(f"{s['unique_aircraft']} aircraft, {s['findings_total']} findings -> {hp.name}")
        return {"json": str(jp), "md": str(mp), "html": str(hp), "name": hp.stem, "summary": {k: s[k] for k in ("unique_aircraft", "findings_total", "by_severity")}}

    def _job_train(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from ..ml.train import train

        recs = p.get("recordings") or [r["path"] for r in self.recordings() if not r["special"]]
        if not recs:
            raise RuntimeError("no civil recordings to train on")
        job.say(f"training on {len(recs)} recordings")
        stats = train(recs, self.settings.get("model") or "models/kinematic_iforest.joblib", float(p.get("contamination", 0.01)))
        job.say(f"{stats['samples_total']} rows, holdout flag rate {stats['flag_rate_holdout']:.2%}")
        return {k: stats[k] for k in ("samples_total", "aircraft_total", "flag_rate_holdout", "model_path", "model_card", "sha256")}

    def _job_evaluate(self, job: Job, p: dict[str, Any]) -> dict[str, Any]:
        from ..ml.evaluate import evaluate, write_evaluation

        rec = p.get("recording") or next((r["path"] for r in self.recordings() if not r["special"] and r["provider"] == "adsblol"), None)
        if not rec:
            raise RuntimeError("no recording to evaluate on")
        model = self.settings.get("model") if Path(self.settings.get("model") or "").is_file() else None
        job.say(f"evaluating on {Path(rec).name}")
        rep = evaluate(rec, model, int(p.get("targets", 25)), int(p.get("seed", 42)), None, int(p.get("max_batches", 60)))
        jp, mp = write_evaluation(rep)
        return {"json": str(jp), "md": str(mp), "recall": {r.name: r.recall for r in rep.results}, "precision": rep.rule_precision}

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
        return {"tunables": rows, "app": {k: self.settings.get(k) for k in ("demo", "alert_log", "alert_webhook", "retention_days", "model", "watchlist")},
                "aero_toml": str(tuning.DEFAULT_PATH), "aero_toml_exists": tuning.DEFAULT_PATH.exists()}

    def settings_update(self, body: dict[str, Any]) -> dict[str, Any]:
        if "app" in body:
            for k, v in body["app"].items():
                if k in self.settings:
                    self.settings[k] = v
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
            g = groups.setdefault(f.stem, {"name": f.stem, "mtime": f.stat().st_mtime, "files": {}})
            g["files"][f.suffix[1:]] = f"/reports/{f.name}"
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
            pass
        return {
            "version": __version__, "uptime_s": round(time.time() - self.started), "source": self.sources.status(),
            "model": model, "model_file": Path(self.settings.get("model") or "").is_file(),
            "recordings": len(list(Path("data/recordings").glob("*.jsonl"))), "reports": len(self.reports()),
            "jobs_running": sum(1 for j in self.jobs.jobs.values() if j.status == "running"),
            "settings": {k: self.settings.get(k) for k in ("demo", "retention_days")},
            "evaluation_exists": Path("models/evaluation.json").is_file(),
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
        app.sources.start_live(b.get("provider", "adsblol"), b.get("region", "nyc"),
                               float(b["radius"]) if b.get("radius") else None, float(b.get("interval", 12)),
                               b.get("demo"), bool(b.get("record", True)))
    else:
        app.sources.start_replay(b["recording"], float(b.get("speed", 8)), b.get("demo"))
    app.settings["last_source"] = app.sources.params
    save_settings(app.settings)
    return {"ok": True, "source": app.sources.status()}


@router.route("POST", "/api/v1/source/stop")
def r_source_stop(app: App, req: Any) -> Any:
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
    return {"kind": inj.kind, "icao24": inj.icao24, "remaining": inj.remaining, "label": inj.label}


@router.route("POST", "/api/v1/clear")
def r_clear(app: App, req: Any) -> Any:
    if app.sources.state:
        app.sources.state.clear_injections()
    return {"ok": True}


@router.route("GET", "/api/v1/reports")
def r_reports(app: App, req: Any) -> Any:
    return app.reports()


@router.route("GET", "/api/v1/jobs")
def r_jobs(app: App, req: Any) -> Any:
    return app.jobs.list()


@router.route("POST", "/api/v1/jobs")
def r_jobs_submit(app: App, req: Any) -> Any:
    b = req["body"]
    job = app.jobs.submit(b.get("type", ""), b.get("params") or {})
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
    return app.settings_update(req["body"])


@router.route("GET", "/api/v1/docs")
def r_docs(app: App, req: Any) -> Any:
    files = sorted(DOCS.glob("*.md")) + sorted((DOCS / "generated").glob("*.md")) + [Path("README.md")]
    return [{"name": str(f.relative_to(".")), "title": f.stem.replace("_", " ").title()} for f in files if f.is_file()]


@router.route("GET", "/api/v1/docs/{name}")
def r_doc(app: App, req: Any) -> Any:
    name = req["params"]["name"].replace("%2F", "/")
    p = Path(name)
    if ".." in p.parts or not (p.suffix == ".md" and p.is_file() and (p.resolve().is_relative_to(DOCS.resolve()) or p.name == "README.md")):
        return ({"error": "not found"}, 404)
    return {"name": name, "text": p.read_text()}


# ---- HTTP glue -------------------------------------------------------------------------------
def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str) -> None:
            u = urlparse(self.path)
            path = u.path
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if method == "GET" and (path == "/" or path.startswith("/#")):
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                    return
                if method == "GET" and path.startswith("/static/"):
                    f = (STATIC / path[len("/static/"):]).resolve()
                    if not f.is_relative_to(STATIC.resolve()) or not f.is_file():
                        self._send(404, b"not found", "text/plain")
                        return
                    self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                    return
                if method == "GET" and path.startswith("/reports/"):
                    f = (REPORTS / path[len("/reports/"):]).resolve()
                    if not f.is_relative_to(REPORTS.resolve()) or not f.is_file():
                        self._send(404, b"not found", "text/plain")
                        return
                    ctype = {".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".json": "application/json"}.get(f.suffix, "text/plain")
                    self._send(200, f.read_bytes(), ctype)
                    return
                m = router.match(method, path)
                if not m:
                    self._send(404, json.dumps({"error": "not found"}).encode(), "application/json")
                    return
                handler, params = m
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
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
            preset: dict[str, Any] | None = None) -> tuple[App, ThreadingHTTPServer]:
    app = App()
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True, name="aero-http").start()
    if preset:
        if preset.get("mode") == "live":
            app.sources.start_live(preset.get("provider", "adsblol"), preset.get("region", "nyc"), preset.get("radius"),
                                   float(preset.get("interval", 12)), preset.get("demo"))
        elif preset.get("recording"):
            app.sources.start_replay(preset["recording"], float(preset.get("speed", 8)), preset.get("demo"))
    url = f"http://{host}:{httpd.server_address[1]}/"
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
