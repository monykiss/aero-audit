"""`aero` command-line interface."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .audit import AuditEngine, write_reports
from .audit.findings import SEVERITY_ORDER
from .config import REGIONS, Region, bbox_region, get_region, parse_regions, settings
from .ingest import PROVIDERS, iter_recording, make_provider
from .ingest.metar import fetch_metars, summarize_metar
from .stream import JsonlRecorder, stream_batches

app = typer.Typer(help="AI/ML + computer-vision auditing for aviation ops and ADS-B security.")
vision_app = typer.Typer(help="Computer-vision commands (requires the [vision] extra).")
security_app = typer.Typer(help="Threat catalog, detection coverage, playbooks, watchlist.")
risk_app = typer.Typer(help="Risk register and evidence-based risk assessment.")
data_app = typer.Typer(help="Recording inventory and maintenance.")
app.add_typer(vision_app, name="vision")
app.add_typer(security_app, name="security")
app.add_typer(risk_app, name="risk")
app.add_typer(data_app, name="data")
con = Console()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


config_app = typer.Typer(help="Threshold tuning (aero.toml).")
app.add_typer(config_app, name="config")


@app.callback()
def _root() -> None:
    """aero-audit CLI."""
    from . import tuning

    applied = tuning.apply()
    if applied:
        con.print(f"[dim]aero.toml overrides applied: {sum(len(v) for v in applied.values())} value(s)")


@app.command()
def version() -> None:
    con.print(f"aero-audit {__version__}")


@app.command()
def regions() -> None:
    """List preset regions."""
    t = Table("key", "name", "lat", "lon", "radius nm", "metar")
    for r in REGIONS.values():
        t.add_row(r.key, r.name, f"{r.lat:.2f}", f"{r.lon:.2f}", str(r.radius_nm), ",".join(r.metar_stations))
    con.print(t)


@app.command()
def providers(region: str = typer.Option(settings.region, help="Region key")) -> None:
    """Health-check every live provider."""
    reg = get_region(region)

    async def run() -> None:
        t = Table("provider", "status", "aircraft", "latency ms", "integrity fields")
        for name in PROVIDERS:
            p = make_provider(name)
            t0 = time.time()
            try:
                b = await p.fetch(reg)
                has_int = any(sv.nic is not None for sv in b.states)
                t.add_row(name, "[green]ok", str(len(b)), f"{(time.time() - t0) * 1000:.0f}", "yes" if has_int else "no")
            except Exception as e:  # noqa: BLE001
                t.add_row(name, f"[red]fail: {type(e).__name__}: {e}", "-", "-", "-")
            finally:
                await p.aclose()
        con.print(t)

    asyncio.run(run())


def _regions(region: str, radius: float | None, bbox: str | None) -> list[Region]:
    return [bbox_region(bbox)] if bbox else parse_regions(region, radius)


@app.command()
def stream(
    provider: str = typer.Option(settings.provider),
    region: str = typer.Option(settings.region, help="Region key or comma-separated list (round-robin)"),
    radius: float | None = typer.Option(None, help="Override radius nm (adsb.lol allows up to 250)"),
    bbox: str | None = typer.Option(None, help="Exact box 'lamin,lomin,lamax,lomax' (best with OpenSky)"),
    interval: float = typer.Option(settings.poll_interval, help="Seconds between consecutive polls"),
    seconds: float = typer.Option(60, help="Total capture duration"),
    out: Path | None = typer.Option(None, help="JSONL path (default data/recordings/<prov>_<region>_<ts>.jsonl)"),
) -> None:
    """Capture live traffic to a JSONL recording (multi-region round-robin supported)."""
    regs = _regions(region, radius, bbox)
    label = "+".join(r.key for r in regs)
    out = out or Path("data/recordings") / f"{provider}_{label}_{_stamp()}.jsonl"
    rec = JsonlRecorder(out)
    p = make_provider(provider)

    async def run() -> None:
        try:
            async for b in stream_batches(p, regs, interval, seconds, rec):
                airborne = sum(1 for s in b.states if s.airborne)
                con.print(f"[dim]{datetime.fromtimestamp(b.ts, UTC):%H:%M:%S}[/] {b.region:6} {len(b):5d} aircraft ({airborne} airborne)")
        finally:
            await p.aclose()
            rec.close()

    asyncio.run(run())
    con.print(f"Recorded {rec.batches} polls -> [bold]{out}[/]")


def _build_engine(
    model: Path | None,
    watchlist: Path | None,
    alert_webhook: str | None,
    alert_log: Path | None,
    alert_min_severity: str,
    allow_unverified_model: bool = False,
) -> AuditEngine:
    from .alerts import Alerter, JsonlSink, WebhookSink
    from .audit.findings import Severity
    from .security import Watchlist

    ml = None
    if model:
        from .ml import ModelIntegrityError, load_verified

        try:
            ml = load_verified(model, allow_unverified_model)
        except ModelIntegrityError as e:
            raise typer.BadParameter(str(e)) from e
        con.print(f"Loaded model {model} (sha256 {ml.sha256_[:12]}, registry {'match' if ml.verified_ else 'UNVERIFIED'}, "
                  f"threshold {ml.threshold_:.4f}, trained on {ml.n_train_} rows)")
    wl = Watchlist.load(watchlist) if watchlist else None
    if wl:
        con.print(f"Watchlist: {len(wl)} entries")
    sinks = []
    if alert_webhook:
        sinks.append(WebhookSink(alert_webhook))
    if alert_log:
        sinks.append(JsonlSink(alert_log))
    alerter = Alerter(sinks, Severity(alert_min_severity)) if sinks else None
    return AuditEngine(ml_model=ml, watchlist=wl, alerter=alerter)


def _print_summary(engine: AuditEngine) -> None:
    s = engine.summary()
    con.print(
        f"\n[bold]Audit[/] provider={s['provider']} region={s['region']} polls={s['batches']} "
        f"aircraft={s['unique_aircraft']} findings={s['findings_total']}"
    )
    t = Table("severity", "count")
    for sev in SEVERITY_ORDER:
        n = s["by_severity"][sev.value]
        color = {"critical": "red", "high": "red", "medium": "yellow", "low": "cyan", "info": "dim"}[sev.value]
        t.add_row(f"[{color}]{sev.value}", str(n))
    con.print(t)
    t2 = Table("rule", "count")
    for k, v in s["by_rule"].items():
        t2.add_row(k, str(v))
    con.print(t2)
    if s["top_aircraft_by_risk"]:
        t3 = Table("aircraft", "cumulative risk")
        for k, v in s["top_aircraft_by_risk"][:5]:
            t3.add_row(k, f"{v:.1f}")
        con.print(t3)
    if s["low_trust_aircraft"]:
        t4 = Table("low-trust aircraft", "trust", "findings")
        for k, v, n in s["low_trust_aircraft"][:5]:
            t4.add_row(k, f"{v:.2f}", str(n))
        con.print(t4)
    if s.get("adsb_compliance_rate") is not None:
        con.print(f"ADS-B integrity compliance: {s['adsb_compliance_rate']:.1%} of {s['adsb_airborne_fixes']} airborne ADS-B fixes")
    if s.get("alerts_sent"):
        con.print(f"Alerts dispatched: {s['alerts_sent']}")


@app.command()
def audit(
    recording: Path | None = typer.Option(None, help="Replay a JSONL recording"),
    live: bool = typer.Option(False, help="Audit live traffic instead"),
    provider: str = typer.Option(settings.provider),
    region: str = typer.Option(settings.region, help="Region key or comma-separated list"),
    radius: float | None = typer.Option(None, help="Override radius nm"),
    bbox: str | None = typer.Option(None, help="Exact box 'lamin,lomin,lamax,lomax'"),
    interval: float = typer.Option(settings.poll_interval),
    seconds: float = typer.Option(60),
    model: Path | None = typer.Option(None, help="Trained anomaly model (.joblib)"),
    watchlist: Path | None = typer.Option(None, help="Watchlist JSON (see aero security watchlist-example)"),
    alert_webhook: str | None = typer.Option(None, help="POST high-severity findings to this URL"),
    alert_log: Path | None = typer.Option(None, help="Append alerted findings to this JSONL"),
    alert_min_severity: str = typer.Option("high", help="info|low|medium|high|critical"),
    out: Path = typer.Option(Path("reports")),
    name: str | None = typer.Option(None),
    allow_unverified_model: bool = typer.Option(False, "--allow-unverified-model", help="Load a model that is not in models/registry.json"),
) -> None:
    """Run the rules engine (+ optional ML model) and write JSON, Markdown, HTML reports plus a signed manifest."""
    from .ingest.replay import recording_stem
    from .provenance import describe_source

    engine = _build_engine(model, watchlist, alert_webhook, alert_log, alert_min_severity, allow_unverified_model)
    source = None

    if recording:
        for b in iter_recording(recording):
            engine.process_batch(b)
        name = name or recording_stem(recording)
        source = describe_source(recording=recording)
    elif live:
        regs = _regions(region, radius, bbox)
        label = "+".join(r.key for r in regs)
        p = make_provider(provider)
        rec_path = Path("data/recordings") / f"{provider}_{label}_{_stamp()}.jsonl"
        rec = JsonlRecorder(rec_path)

        async def run() -> None:
            try:
                async for b in stream_batches(p, regs, interval, seconds, rec):
                    new = engine.process_batch(b)
                    for f in new:
                        con.print(f"  [{f.severity.value}] {f.rule_id} {f.icao24} {f.callsign or ''}: {f.title}")
            finally:
                await p.aclose()
                rec.close()

        asyncio.run(run())
        con.print(f"Live capture also saved to {rec_path}")
        name = name or f"{provider}_{label}"
        source = describe_source(mode="live", provider=provider, region=label, interval=interval, recording=None) | {"recorded_to": str(rec_path)}
    else:
        raise typer.BadParameter("Pass --recording PATH or --live")

    _print_summary(engine)
    jp, mp, hp = write_reports(engine, out, name, source=source)
    con.print(f"Reports: [bold]{mp}[/], {hp}, {jp} (+ manifest with sha256 of each file)")


@app.command()
def train(
    recording: list[Path] = typer.Argument(..., help="One or more JSONL recordings"),
    out: Path = typer.Option(Path("models/kinematic_iforest.joblib")),
    contamination: float = typer.Option(0.01, help="Expected anomaly fraction per fix"),
) -> None:
    """Fit the IsolationForest kinematic anomaly model."""
    from .ml.train import train as _train

    stats = _train(recording, out, contamination)
    con.print(json.dumps(stats, indent=2))


@app.command()
def synth(
    out: Path = typer.Option(Path("data/recordings/synthetic_nyc.jsonl")),
    aircraft: int = typer.Option(40),
    polls: int = typer.Option(30),
    seed: int = typer.Option(7),
) -> None:
    """Generate a synthetic recording with injected anomalies (offline practice)."""
    from .synthetic import generate

    if out.exists():
        out.unlink()
    p = generate(out, n_aircraft=aircraft, polls=polls, seed=seed)
    con.print(f"Wrote {p} ({polls} polls x {aircraft} aircraft)")


@app.command()
def weather(target: str = typer.Argument(settings.region, help="Region key or comma-separated ICAO stations")) -> None:
    """Fetch current METARs (NOAA AWC)."""
    stations = list(get_region(target).metar_stations) if target.lower() in REGIONS else target.upper().split(",")
    for m in asyncio.run(fetch_metars(stations)):
        con.print(summarize_metar(m))


@app.command()
def corroborate(
    region: str = typer.Option(settings.region),
    radius: float | None = typer.Option(None),
    primary: str = typer.Option("adsblol"),
    secondary: str = typer.Option("opensky"),
    interval: float = typer.Option(25, help="OpenSky anonymous latency is ~20 s; keep >= 25"),
    seconds: float = typer.Option(75),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Poll two independent feeds and flag aircraft whose positions disagree (SEC-015)."""
    from .security import corroborate as _corr

    regs = parse_regions(region, radius)
    reg = regs[0]
    pa, pb = make_provider(primary), make_provider(secondary)
    engine = AuditEngine()
    totals: dict[str, float] = {"matched": 0, "only_primary": 0, "only_secondary": 0, "disagreements": 0}
    seps: list[float] = []
    rounds = 0

    async def run() -> None:
        nonlocal rounds
        start = time.time()
        try:
            while time.time() - start < seconds:
                t0 = time.time()
                ba, bb = await asyncio.gather(pa.fetch(reg), pb.fetch(reg), return_exceptions=True)
                if isinstance(ba, Exception) or isinstance(bb, Exception):
                    con.print(f"[yellow]fetch error: {ba if isinstance(ba, Exception) else bb}")
                else:
                    res = _corr(ba, bb)
                    rounds += 1
                    for k in totals:
                        totals[k] += getattr(res, k)
                    seps.extend(res.separations_nm)
                    engine.first_ts = engine.first_ts or ba.ts
                    engine.last_ts, engine.provider, engine.region = ba.ts, f"{primary}+{secondary}", reg.key
                    engine.batches += 1
                    engine.aircraft.update({sv.icao24 for sv in ba.states} | {sv.icao24 for sv in bb.states})
                    engine.findings.extend(res.findings)
                    sm = res.summary()
                    con.print(f"[dim]{datetime.fromtimestamp(ba.ts, UTC):%H:%M:%S}[/] matched={sm['matched']} "
                              f"only_{primary}={sm['only_primary']} only_{secondary}={sm['only_secondary']} "
                              f"disagree={sm['disagreements']} median_sep={sm['median_sep_nm']}nm p95={sm['p95_sep_nm']}nm")
                    for f in res.findings:
                        con.print(f"  [{f.severity.value}] {f.rule_id} {f.icao24} {f.callsign or ''}: sep {f.evidence['separation_nm']} nm")
                await asyncio.sleep(max(0.0, interval - (time.time() - t0)))
        finally:
            await pa.aclose()
            await pb.aclose()

    asyncio.run(run())
    seps.sort()
    con.print(f"\n[bold]Corroboration[/] rounds={rounds} " + " ".join(f"{k}={int(v)}" for k, v in totals.items())
              + (f" median_sep={seps[len(seps)//2]:.2f}nm p95={seps[int(0.95*(len(seps)-1))]:.2f}nm" if seps else ""))
    if engine.findings:
        _, mp, _ = write_reports(engine, out, f"corroborate_{reg.key}")
        con.print(f"Reports: {mp}")


@security_app.command("threats")
def security_threats() -> None:
    """Threat catalog with detection coverage and, when models/evaluation.json exists, measured recall."""
    from .security import coverage_matrix
    from .security.threats import load_evaluation

    ev = load_evaluation()
    t = Table("id", "threat", "tactic", "coverage", "rules", "measured recall", "L", "S", "LxS")
    for r in coverage_matrix(ev):
        color = {"covered": "green", "partial": "yellow", "gap": "red"}[r["coverage"]]
        t.add_row(r["id"], r["threat"], r["tactic"], f"[{color}]{r['coverage']}", r["rules"], r["measured"], r["L"], r["S"], r["score"])
    con.print(t)
    if ev:
        con.print(f"[dim]measured on {ev.get('recording')} at {ev.get('created_at')}")


@security_app.command("playbook")
def security_playbook(rule_id: str = typer.Argument(..., help="e.g. SEC-010")) -> None:
    """Print the response playbook for a rule."""
    from .security import playbook_for

    pb = playbook_for(rule_id.upper())
    if not pb:
        raise typer.BadParameter(f"No playbook for {rule_id}")
    con.print(f"[bold]{pb.rule_id}: {pb.title}[/]  (triage SLA {pb.sla_minutes} min)")
    con.print("[bold]Triage[/]"); [con.print(f"  {i}. {x}") for i, x in enumerate(pb.triage, 1)]
    con.print("[bold]Verify[/]"); [con.print(f"  - {x}") for x in pb.verify]
    con.print(f"[bold]Escalate[/]  {pb.escalate}")
    con.print("[bold]Contain[/]"); [con.print(f"  - {x}") for x in pb.contain]


@security_app.command("rules")
def security_rules() -> None:
    """List every rule id the engine can emit."""
    from .audit.rules import RULE_CATALOG

    t = Table("rule", "category", "description")
    for rid, (cat, desc) in RULE_CATALOG.items():
        t.add_row(rid, cat, desc)
    con.print(t)


@security_app.command("watchlist-example")
def security_watchlist_example(out: Path = typer.Option(Path("data/watchlist.example.json"))) -> None:
    """Write an example watchlist file."""
    from .security import WatchEntry, Watchlist

    Watchlist([
        WatchEntry("Prior-incident address", "Address used in a 2025 ghost-injection test", icao24="abcdef", severity="high"),
        WatchEntry("Medical flights", "Protect: do not publish tracks", callsign_prefix="LIFE", severity="info", mode="protect"),
        WatchEntry("Registration of interest", "Example registration match", registration="N12345", severity="medium"),
    ]).save(out)
    con.print(f"Wrote {out}")


@risk_app.command("register")
def risk_register(out: Path | None = typer.Option(None, help="Write Markdown here")) -> None:
    """Baseline risk register (no observed evidence)."""
    from .risk import assess, render_markdown

    rows = assess(None)
    t = Table("id", "risk", "L", "I", "score", "rating")
    for r in rows:
        t.add_row(r["id"], r["title"], str(r["L"]), str(r["I"]), str(r["score"]), r["rating"])
    con.print(t)
    if out:
        out.write_text(render_markdown(rows, "Risk register (baseline)"))
        con.print(f"Wrote {out}")


@risk_app.command("assess")
def risk_assess(
    recording: list[Path] = typer.Argument(..., help="Recordings to audit as evidence"),
    model: Path | None = typer.Option(None),
    corroboration: list[Path] | None = typer.Option(None, help="JSON reports from `aero corroborate` to count as evidence (SEC-015)"),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Audit each recording in its own engine (plus corroboration reports), then re-score the register."""
    from .risk import assess, merge_summaries, render_markdown

    summaries = []
    for rp in recording:
        engine = _build_engine(model, None, None, None, "high")
        for b in iter_recording(rp):
            engine.process_batch(b)
        summaries.append(engine.summary())
    for cp in corroboration or []:
        summaries.append(json.loads(cp.read_text())["summary"])
    s = merge_summaries(summaries)
    rows = assess(s)
    t = Table("id", "risk", "L base->obs", "I", "score", "rating", "hits", "per 1k aircraft")
    for r in rows:
        t.add_row(r["id"], r["title"][:48], f"{r['baseline_L']}->{r['L']}", str(r["I"]), str(r["score"]), r["rating"], str(r["observed_hits"]), str(r["rate_per_1000"]))
    con.print(t)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"risk_assessment_{_stamp()}.md"
    header = (f"Evidence: {len(recording)} recording(s) audited separately"
              f"{f' + {len(corroboration)} corroboration report(s)' if corroboration else ''}, {s['batches']} polls, "
              f"{s['unique_aircraft']} aircraft-observations (summed per recording), {s['findings_total']} findings. "
              f"Rule counts: {s['by_rule']}\n\n")
    path.write_text(render_markdown(rows, "Risk assessment (evidence-adjusted)").replace("\n\n", "\n\n" + header, 1))
    con.print(f"Wrote {path}")


@app.command()
def impact(
    recording: list[Path] = typer.Argument(..., help="Recordings to audit for OPS-002 holding"),
    fuel_kg_per_min: float = typer.Option(40.0),
    co2_per_kg: float = typer.Option(3.16),
    delay_cost_per_min: float = typer.Option(100.0, help="EUR"),
    fuel_price_per_kg: float = typer.Option(0.85, help="EUR"),
) -> None:
    """Estimate observed holding minutes, fuel, CO2, and cost from OPS-002 findings."""
    from .impact import ImpactAssumptions, estimate_holding_impact

    engine = AuditEngine()
    for rp in recording:
        for b in iter_recording(rp):
            engine.process_batch(b)
    est = estimate_holding_impact(
        engine.findings,
        ImpactAssumptions(fuel_kg_per_min, co2_per_kg, delay_cost_per_min, fuel_price_per_kg),
    )
    con.print(json.dumps(est.as_dict(), indent=2))
    con.print("[dim]Observed minutes are a floor (detection window only). Replace defaults with operator figures.")


@app.command()
def evaluate(
    recording: Path = typer.Argument(..., help="Real recording used as background traffic"),
    model: Path | None = typer.Option(None, help="Trained anomaly model (.joblib)"),
    targets: int = typer.Option(25, help="Aircraft perturbed per scenario"),
    seed: int = typer.Option(42),
    max_batches: int | None = typer.Option(None, help="Truncate the recording for a quick run"),
    scenario: list[str] | None = typer.Option(None, help="Subset of scenarios (default: all)"),
    onset: float = typer.Option(0.4, help="Fraction of the recording before the attack starts"),
    allow_unverified_model: bool = typer.Option(False, "--allow-unverified-model", help="Load a model that is not in models/registry.json"),
) -> None:
    """Inject attack scenarios into real traffic; measure recall, time-to-detect, and per-rule precision."""
    from .ml.evaluate import SCENARIOS, write_evaluation
    from .ml.evaluate import evaluate as _evaluate

    unknown = set(scenario or []) - set(SCENARIOS)
    if unknown:
        raise typer.BadParameter(f"unknown scenarios {unknown}; known: {', '.join(SCENARIOS)}")
    rep = _evaluate(recording, model, targets, seed, scenario or None, max_batches, onset, allow_unverified_model=allow_unverified_model)
    t = Table("scenario", "expected", "targets", "detected", "recall", "any sec/ML", "median TTD s", "note")
    for r in rep.results:
        color = "green" if r.recall >= 0.8 else ("yellow" if r.recall >= 0.5 else "red")
        t.add_row(r.name, ", ".join(r.expected_rules) if not r.known_gap else "any kinematic", str(r.targets), str(r.detected),
                  f"[{color}]{r.recall:.0%}", f"{r.any_security_recall:.0%}",
                  f"{r.median_ttd_s:.0f}" if r.median_ttd_s is not None else "-", "known gap" if r.known_gap else "")
    con.print(t)
    if rep.median_revisit_s:
        con.print(f"Median revisit interval of targets: {rep.median_revisit_s:.0f} s (the detection clock)")
    t2 = Table("rule", "TP", "FP", "precision")
    for rid, pval in rep.rule_precision.items():
        t2.add_row(rid, str(rep.rule_tp.get(rid, 0)), str(rep.rule_fp.get(rid, 0)), f"{pval:.2f}" if pval is not None else "n/a")
    con.print(t2)
    jp, mp = write_evaluation(rep)
    con.print(f"Wrote {jp} (feeds risk_score and risk assess) and {mp}")


@config_app.command("show")
def config_show(section: str | None = typer.Argument(None)) -> None:
    """Effective thresholds and whether aero.toml overrides them."""
    from . import tuning

    t = Table("section", "key", "value", "overridden")
    for sec, key, val, over in tuning.effective():
        if section and sec != section:
            continue
        t.add_row(sec, key, str(val)[:60], "[yellow]yes" if over else "")
    con.print(t)


@config_app.command("init")
def config_init(out: Path = typer.Option(Path("aero.toml"))) -> None:
    """Write a commented aero.toml template with every tunable at its default."""
    from . import tuning

    if out.exists():
        raise typer.BadParameter(f"{out} exists; delete it first")
    out.write_text(tuning.template())
    con.print(f"Wrote {out}")


@data_app.command("catalog")
def data_catalog(action: str = typer.Argument("build", help="build | search | reconcile"), q: str | None = typer.Option(None), collection: str | None = typer.Option(None),
                 path: Path = typer.Option(Path("data/app/catalog.json"))) -> None:
    """CMR-style data catalogue: every recording, report, study, asset, element set, CDM and model as a granule with hash, time bounds and provenance."""
    from .governance.catalog import build_catalog, load_catalog, reconcile, save_catalog, search

    if action == "build":
        cat = build_catalog(".")
        save_catalog(cat, path)
        t = Table("collection", "granules", "MB")
        for name, c in cat["collections"].items():
            t.add_row(name, str(c["count"]), f"{c['bytes'] / 1e6:.1f}")
        con.print(t)
        con.print(f"{cat['granules_total']} granules, {cat['bytes_total'] / 1e9:.2f} GB -> {path}")
    elif action == "search":
        cat = load_catalog(path) or build_catalog(".")
        t = Table("collection", "granule", "MB", "time", "provenance")
        for g in search(cat, q, collection)[:60]:
            t.add_row(g["collection"], g["id"][:70], f"{g['bytes'] / 1e6:.2f}", str(g.get("time_start", ""))[:10], "yes" if g.get("provenance") else "")
        con.print(t)
    elif action == "reconcile":
        old = load_catalog(path)
        new = build_catalog(".")
        r = reconcile(old, new)
        con.print(f"since {r['previous']}: {len(r['added'])} added, {len(r['removed'])} removed, {len(r['changed'])} changed; drift={r['drift']}")
        for k in ("added", "removed", "changed"):
            for g in r[k][:20]:
                con.print(f"  {k:<8} {g}")
        save_catalog(new, path)
    else:
        raise typer.BadParameter("action must be build, search or reconcile")


@data_app.command("prune")
def data_prune(
    days: int = typer.Option(30, help="Delete recordings older than this"),
    directory: Path = typer.Option(Path("data/recordings")),
    apply: bool = typer.Option(False, help="Actually delete (default is a dry run)"),
) -> None:
    """Retention: list (or delete with --apply) recordings older than N days."""
    cutoff = time.time() - days * 86400
    old = [f for f in sorted(directory.glob("*.jsonl")) if f.stat().st_mtime < cutoff]
    if not old:
        con.print(f"No recordings older than {days} days.")
        return
    for f in old:
        con.print(f"{'deleting' if apply else 'would delete'} {f} ({f.stat().st_size / 1e6:.1f} MB)")
        if apply:
            f.unlink()
    con.print(f"{len(old)} file(s){' deleted' if apply else ' (dry run; add --apply)'}")


def _security_banner(host: str, port: int, token: str | None, allow_unauthenticated: bool) -> None:
    from .web.security import Guard

    try:
        g = Guard(host, token, allow_unauthenticated)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if g.mode == "loopback":
        con.print("[dim]Security: bound to loopback (this machine only); cross-site and rebinding requests are refused; "
                  "POSTs need the per-run token the page fetches itself.")
    elif g.mode == "token":
        con.print(f"[yellow]Security: REMOTE MODE on {host}. Every API call needs the header X-Aero-Token; the browser will ask for it once.")
    else:
        con.print(f"[red]Security: UNAUTHENTICATED on {host}. Only acceptable when the container host publishes the port on loopback.")


@app.command("app")
def app_cmd(
    port: int = typer.Option(8787),
    host: str = typer.Option("127.0.0.1", help="Bind address; anything but loopback needs --token or --allow-unauthenticated"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser automatically"),
    token: str | None = typer.Option(None, envvar="AERO_APP_TOKEN", help="Shared access token for a non-loopback bind"),
    allow_unauthenticated: bool = typer.Option(False, help="Non-loopback bind without a token (container whose port is published on loopback)"),
    allowed_host: list[str] | None = typer.Option(None, help="Extra Host header values to accept (e.g. a LAN name)"),
) -> None:
    """Start the local app (home screen, live map, findings, risk, reports, data, settings, help)."""
    from .web.app import run_app

    _security_banner(host, port, token, allow_unauthenticated)
    con.print(f"[bold]aero-audit app[/] http://{host}:{port}/  (Ctrl+C to stop)")
    run_app(port, host, open_browser, token=token, allow_unauthenticated=allow_unauthenticated, allowed_hosts=tuple(allowed_host or ()))


@app.command()
def serve(
    replay: Path | None = typer.Option(None, help="Start with a replay of this recording"),
    live: bool = typer.Option(False, help="Start with a live feed"),
    provider: str = typer.Option(settings.provider),
    region: str = typer.Option(settings.region),
    radius: float | None = typer.Option(None),
    interval: float = typer.Option(settings.poll_interval),
    speed: float = typer.Option(8.0, help="Replay speed multiplier"),
    port: int = typer.Option(8787),
    host: str = typer.Option("127.0.0.1"),
    demo: bool = typer.Option(True),
    open_browser: bool = typer.Option(False, "--open/--no-open"),
    tour: bool = typer.Option(False, help="Run the scripted attack tour on the preset source"),
    token: str | None = typer.Option(None, envvar="AERO_APP_TOKEN", help="Shared access token for a non-loopback bind"),
    allow_unauthenticated: bool = typer.Option(False, help="Non-loopback bind without a token"),
) -> None:
    """Start the app with a source already running (replay by default: newest civil recording)."""
    from .web.app import run_app

    preset: dict[str, object]
    if live:
        preset = {"mode": "live", "provider": provider, "region": region, "radius": radius, "interval": interval, "demo": demo}
    else:
        if replay is None:
            cands = sorted((p for p in Path("data/recordings").glob("*.jsonl") if "_mil_" not in p.name and "synthetic" not in p.name),
                           key=lambda p: p.stat().st_mtime)
            if not cands:
                raise typer.BadParameter("no recordings to replay; use --live or `aero app`")
            replay = cands[-1]
        preset = {"mode": "replay", "recording": str(replay), "speed": speed, "demo": demo}
    _security_banner(host, port, token, allow_unauthenticated)
    con.print(f"[bold]aero-audit app[/] http://{host}:{port}/  preset={preset}  (Ctrl+C to stop)")
    run_app(port, host, open_browser, preset=preset, token=token, allow_unauthenticated=allow_unauthenticated, tour=tour)


@app.command("docs-build")
def docs_build_cmd(out: Path = typer.Option(Path("docs/generated"))) -> None:
    """Render threat matrix, playbooks, risk register, and rule list from code."""
    from .docs_build import build

    for p in build(out):
        con.print(f"wrote {p}")


@data_app.command("inventory")
def data_inventory(directory: Path = typer.Option(Path("data/recordings"))) -> None:
    """Summarise every recording: provider, regions, polls, aircraft, time span."""
    t = Table("file", "provider", "regions", "polls", "state vectors", "aircraft", "span", "size")
    grand_sv, grand_ac = 0, set()
    for f in sorted(directory.glob("*.jsonl")):
        polls, sv, ac, regions, first, last, prov = 0, 0, set(), set(), None, None, "?"
        for b in iter_recording(f):
            polls += 1
            sv += len(b)
            ac.update(x.icao24 for x in b.states)
            regions.add(b.region)
            prov = b.provider
            first = b.ts if first is None else first
            last = b.ts
        span = f"{(last - first) / 60:.0f} min" if first and last else "-"
        t.add_row(f.name, prov, "+".join(sorted(regions)), str(polls), str(sv), str(len(ac)), span, f"{f.stat().st_size / 1e6:.1f} MB")
        grand_sv += sv
        grand_ac |= ac
    con.print(t)
    con.print(f"Total: {grand_sv} state vectors, {len(grand_ac)} unique aircraft")


@vision_app.command("detect")
def vision_detect(
    image: Path = typer.Argument(..., exists=True),
    weights: str = typer.Option("yolov8n.pt"),
    conf: float = typer.Option(0.25),
    out: Path | None = typer.Option(None, help="Annotated image path"),
    all_classes: bool = typer.Option(False, help="Keep non-aircraft detections too"),
    tile: int = typer.Option(0, help="Tile size in px for sliced inference (0 = whole image). Try 320 for aerial shots."),
    overlap: float = typer.Option(0.25, help="Tile overlap fraction"),
) -> None:
    """Detect aircraft in an image and write an annotated copy."""
    from .vision import annotate, detect, detect_tiled

    if tile:
        dets, (w, h) = detect_tiled(image, weights=weights, conf=conf, tile=tile, overlap=overlap, only_aircraft=not all_classes)
    else:
        dets, (w, h) = detect(image, weights=weights, conf=conf, only_aircraft=not all_classes)
    out = out or Path("reports") / f"{image.stem}_annotated.jpg"
    annotate(image, dets, out)
    t = Table("label", "conf", "box (x1,y1,x2,y2)", "center (norm)")
    for d in dets:
        t.add_row(d.label, f"{d.conf:.2f}", f"{d.x1},{d.y1},{d.x2},{d.y2}", f"{d.cx:.2f},{d.cy:.2f}")
    con.print(t)
    con.print(f"{len(dets)} detections in {w}x{h} image -> {out}")


@vision_app.command("apron")
def vision_apron(
    image: Path = typer.Argument(..., exists=True),
    zones: Path | None = typer.Option(None, help="JSON list of {name, polygon, capacity}"),
    weights: str = typer.Option("yolov8n.pt"),
    conf: float = typer.Option(0.15),
    tile: int = typer.Option(320, help="Tile size for sliced inference (0 = whole image)"),
) -> None:
    """Count aircraft per apron zone and emit process findings."""
    from .vision import DEFAULT_ZONES, Zone, detect, detect_tiled, occupancy, zone_findings

    zl = DEFAULT_ZONES
    if zones:
        zl = [Zone(z["name"], [tuple(p) for p in z["polygon"]], z.get("capacity", 1)) for z in json.loads(zones.read_text())]
    dets, _ = detect_tiled(image, weights=weights, conf=conf, tile=tile) if tile else detect(image, weights=weights, conf=conf)
    occ = occupancy(dets, zl)
    con.print(json.dumps(occ, indent=2))
    for f in zone_findings(occ, zl, str(image), time.time()):
        con.print(f"  [{f.severity.value}] {f.rule_id} {f.title}")


# ---- demo / doctor / log -------------------------------------------------------------------
SAMPLES_DIR = Path("data/samples")


def _demo_recording() -> Path | None:
    samples = sorted(SAMPLES_DIR.glob("*.jsonl.gz"), key=lambda p: p.stat().st_size, reverse=True)
    if samples:
        return samples[0]
    cands = sorted((p for p in Path("data/recordings").glob("*.jsonl") if "_mil_" not in p.name),
                   key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


@app.command()
def demo(
    port: int = typer.Option(8787),
    host: str = typer.Option("127.0.0.1"),
    speed: float = typer.Option(10.0, help="Replay speed multiplier"),
    recording: Path | None = typer.Option(None, help="Recording to replay (default: the largest bundled sample)"),
    tour: bool = typer.Option(True, "--tour/--no-tour", help="Run the scripted attack tour"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
    train_if_missing: bool = typer.Option(True, help="Train the anomaly model on the bundled samples when none exists"),
    token: str | None = typer.Option(None, envvar="AERO_APP_TOKEN", help="Shared access token for a non-loopback bind"),
    allow_unauthenticated: bool = typer.Option(False, help="Non-loopback bind without a token (container with a loopback-published port)"),
) -> None:
    """One command, fully offline: replay the bundled real-traffic sample with the scripted attack tour."""
    from .web.app import run_app

    rec = recording or _demo_recording()
    if rec is None:
        from .synthetic import generate

        rec = generate(Path("data/recordings/synthetic_demo.jsonl"), n_aircraft=60, polls=40, seed=11)
        con.print(f"No sample found; generated synthetic traffic at {rec}")
    model = Path("models/kinematic_iforest.joblib")
    if train_if_missing and not model.is_file():
        from .ml.train import train

        sources = sorted(SAMPLES_DIR.glob("*.jsonl.gz")) or [rec]
        con.print(f"No anomaly model yet: training one on {len(sources)} sample recording(s)...")
        stats = train([str(p) for p in sources], model, 0.01)
        con.print(f"  {stats['samples_total']} rows from {stats['aircraft_total']} aircraft; registered sha256 {stats['sha256'][:12]}")
    _security_banner(host, port, token, allow_unauthenticated)
    preset = {"mode": "replay", "recording": str(rec), "speed": speed, "demo": True}
    con.print(f"[bold]aero-audit demo[/] http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/  replaying {rec.name} at {speed:g}x"
              f"{' with the scripted tour' if tour else ''}  (Ctrl+C to stop)")
    run_app(port, host, open_browser, preset=preset, token=token, allow_unauthenticated=allow_unauthenticated, tour=tour)


@app.command()
def accounts() -> None:
    """External services: what each unlocks, its keyless fallback, where to sign up, and whether it is configured (values never printed)."""
    from .integrations import status

    t = Table("service", "configured", "env", "unlocks", "without it", "sign up")
    for i in status():
        conf = "[green]yes" if i["configured"] and i["required"] else ("[cyan]keyless" if not i["required"] else "[yellow]no")
        t.add_row(i["name"], conf, " ".join(i["env"] + i["optional_env"]), i["unlocks"][:70], i["keyless"][:50], i["signup"][:60])
    con.print(t)
    con.print("Set variables in a git-ignored .env (see docs/ACCOUNTS.md); never on the command line.")


@app.command()
def doctor(net: bool = typer.Option(True, "--net/--no-net", help="Probe the public feeds")) -> None:
    """Check this machine: Python, dependencies, samples, model integrity, ports, feeds, audit chain."""
    import importlib
    import os
    import socket
    import sys

    from .ml import verify_model
    from .provenance import git_commit
    from .web.audit import AUDIT_FILE, verify_file

    rows: list[tuple[str, str, str]] = []

    def ok(check: str, detail: str) -> None:
        rows.append((check, "[green]OK", detail))

    def warn(check: str, detail: str) -> None:
        rows.append((check, "[yellow]WARN", detail))

    def fail(check: str, detail: str) -> None:
        rows.append((check, "[red]FAIL", detail))

    v = sys.version_info
    (ok if v >= (3, 12) else fail)("python", f"{v.major}.{v.minor}.{v.micro} at {sys.executable}")
    g = git_commit()
    ok("aero-audit", f"{__version__}" + (f" @ {g['commit'][:10]}{' (dirty)' if g['dirty'] else ''}" if g else " (not a git checkout)"))
    for mod in ("numpy", "pandas", "sklearn", "httpx", "pydantic", "typer"):
        try:
            m = importlib.import_module(mod)
            ok(f"dep {mod}", getattr(m, "__version__", "?"))
        except ImportError as e:
            fail(f"dep {mod}", str(e))
    try:
        importlib.import_module("ultralytics")
        ok("vision extra", "ultralytics importable")
    except ImportError:
        warn("vision extra", "not installed (optional: uv pip install -e '.[vision]')")
    samples = list(SAMPLES_DIR.glob("*.jsonl.gz"))
    (ok if samples else warn)("bundled samples", f"{len(samples)} file(s): " + ", ".join(p.name for p in samples) if samples else "none; `aero demo` will synthesise traffic")
    recs = list(Path("data/recordings").glob("*.jsonl"))
    (ok if recs else warn)("recordings", f"{len(recs)} on disk" if recs else "none yet (capture with `aero stream` or the Data page)")
    mp = Path("models/kinematic_iforest.joblib")
    if mp.is_file():
        vm = verify_model(mp)
        (ok if vm["match"] else fail)("model integrity", f"sha256 {vm['sha256'][:12]} " + ("matches models/registry.json" if vm["match"] else "has NO matching registry entry (retrain with `aero train`)"))
    else:
        warn("model", "none trained yet; `aero demo` trains one on the samples")
    (ok if Path("models/evaluation.json").is_file() else warn)("evaluation", "models/evaluation.json feeds rule precision into scoring" if Path("models/evaluation.json").is_file() else "missing; scoring uses the precision floor")
    from . import tuning

    n_over = sum(len(v) for v in tuning.apply().values()) if tuning.DEFAULT_PATH.exists() else 0
    ok("thresholds", f"{n_over} override(s) in {tuning.DEFAULT_PATH}" if n_over else "defaults (no aero.toml)")
    creds = bool(os.getenv("OPENSKY_CLIENT_ID")) and bool(os.getenv("OPENSKY_CLIENT_SECRET"))
    ok("secrets", "OpenSky credentials present in the environment (values never printed)" if creds else "no OpenSky credentials (anonymous quota applies); .env is git-ignored")
    from .integrations import INTEGRATIONS, missing

    miss = missing()
    (warn if miss else ok)("integrations", f"{len(INTEGRATIONS) - len(miss)}/{len(INTEGRATIONS)} configured or keyless; missing: {', '.join(miss)} (see `aero accounts`)" if miss else "every integration configured or keyless")
    for d in ("data/recordings", "data/app", "reports", "logs", "models"):
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            probe = Path(d) / ".write-probe"
            probe.write_text("x")
            probe.unlink()
            ok(f"writable {d}", "yes")
        except OSError as e:
            fail(f"writable {d}", str(e))
    with socket.socket() as s:
        s.settimeout(0.5)
        busy = s.connect_ex(("127.0.0.1", 8787)) == 0
    (warn if busy else ok)("port 8787", "in use (another aero instance? pass --port)" if busy else "free")
    if AUDIT_FILE.is_file():
        vr = verify_file(AUDIT_FILE)
        (ok if vr["ok"] else fail)("audit log chain", f"{vr['chained']} linked entries, head {vr['head'][:12]}" if vr["ok"] else vr["error"] or "broken")
    else:
        ok("audit log chain", "no log yet (created on first app start)")
    if net:
        for host_, label in (("api.adsb.lol", "adsb.lol"), ("opensky-network.org", "OpenSky"), ("aviationweather.gov", "NOAA METAR"), ("nasstatus.faa.gov", "FAA NAS status")):
            try:
                with socket.create_connection((host_, 443), timeout=4):
                    ok(f"feed {label}", f"{host_}:443 reachable")
            except OSError as e:
                import shutil
                import subprocess

                curl = shutil.which("curl")
                if curl and subprocess.run([curl, "-sS", "-o", "/dev/null", "--max-time", "6", f"https://{host_}/"], capture_output=True, check=False).returncode == 0:
                    warn(f"feed {label}", f"Python sockets blocked ({type(e).__name__}) but curl works: set AERO_HTTP_BACKEND=curl (a per-app firewall?)")
                else:
                    warn(f"feed {label}", f"unreachable ({type(e).__name__}); replay and the demo still work offline")
    t = Table("check", "status", "detail")
    for r in rows:
        t.add_row(*r)
    con.print(t)
    failures = [r for r in rows if "FAIL" in r[1]]
    con.print(f"{len(rows)} checks, {len(failures)} failing")
    if failures:
        raise typer.Exit(1)


log_app = typer.Typer(help="Tamper-evident audit log and report manifests.")
app.add_typer(log_app, name="log")


@log_app.command("verify")
def log_verify(path: Path = typer.Option(Path("data/app/audit.jsonl"))) -> None:
    """Walk the hash chain of the app audit log; exit 1 if any link is broken."""
    from .web.audit import verify_file

    r = verify_file(path)
    if r["error"] and r["ok"]:
        con.print(f"[yellow]{r['error']}")
        return
    con.print(f"{path}: {r['entries']} entries, {r['chained']} chained, {r['legacy']} legacy, head {r['head'][:16]}")
    if r["ok"]:
        con.print("[green]chain verified")
    else:
        con.print(f"[red]chain broken: {r['error']}")
        raise typer.Exit(1)


@log_app.command("show")
def log_show(path: Path = typer.Option(Path("data/app/audit.jsonl")), limit: int = typer.Option(40), action: str | None = typer.Option(None)) -> None:
    """Print the latest audit-log entries."""
    from .web.audit import AuditLog

    log = AuditLog(path)
    t = Table("#", "time (UTC)", "actor", "action", "details", "hash")
    for e in log.entries(limit=limit, action=action):
        t.add_row(str(e.get("seq", "")), datetime.fromtimestamp(e["ts"], UTC).strftime("%Y-%m-%d %H:%M:%S"), e["actor"], e["action"],
                  json.dumps(e["details"], default=str)[:80], (e.get("hash") or "")[:10])
    con.print(t)


@log_app.command("bundle")
def log_bundle(out: Path | None = typer.Option(None, help="Zip path (default reports/evidence_<stamp>.zip)"),
               since_days: float | None = typer.Option(None, help="Only reports newer than this many days"),
               extra: list[Path] | None = typer.Option(None, help="Additional files to include")) -> None:
    """Evidence bundle: audit chain with verification, reports and manifests, model card and evaluation, thresholds,
    generated docs, redacted settings, and BUNDLE.json with the SHA-256 of every member."""
    from .evidence import build_bundle, verify_bundle

    p = build_bundle(out, since_days, [str(e) for e in (extra or [])])
    r = verify_bundle(p)
    con.print(f"[bold]{p}[/]: {r['checked']} files, chain {'ok' if (r.get('audit_chain') or {}).get('ok') else 'absent/broken'}, self-check {'ok' if r['ok'] else 'FAILED'}")


@log_app.command("verify-bundle")
def log_verify_bundle(bundle: Path = typer.Argument(...)) -> None:
    """Re-hash every member of an evidence bundle against BUNDLE.json; exit 1 on any mismatch."""
    from .evidence import verify_bundle

    r = verify_bundle(bundle)
    con.print(f"{bundle}: {r['checked']} checked, {len(r['bad'])} bad, {len(r['missing'])} missing, {len(r['extra'])} extra; created {r.get('created_at')} by {r.get('version')}")
    for b in r["bad"]:
        con.print(f"  [red]modified[/] {b}")
    for m in r["missing"]:
        con.print(f"  [red]missing[/] {m}")
    for e in r["extra"]:
        con.print(f"  [yellow]unlisted[/] {e}")
    if not r["ok"]:
        raise typer.Exit(1)
    con.print("[green]bundle intact")


@log_app.command("verify-report")
def log_verify_report(manifest: Path = typer.Argument(..., help="reports/<name>.manifest.json")) -> None:
    """Re-hash the files a report manifest names and compare; exit 1 on any mismatch."""
    from .provenance import verify_manifest

    r = verify_manifest(manifest)
    for k, f in r["files"].items():
        con.print(f"  {'[green]ok  ' if f['ok'] else '[red]BAD '}[/] {k}: {f['path']}")
    if not r["ok"]:
        con.print("[red]one or more files differ from the manifest")
        raise typer.Exit(1)
    con.print("[green]all files match the manifest")


# ---- space intake (NASA open assets, launch footage, telemetry) ---------------------------------
space_app = typer.Typer(help="NASA open assets and launch footage: catalogue, verified download, frames, captions, telemetry audit.")
app.add_typer(space_app, name="space")


@space_app.command("catalog")
def space_catalog(
    ref: str = typer.Option("master"),
    out: Path = typer.Option(Path("data/space/nasa3d_catalog.json")),
    kind: str | None = typer.Option(None, help="model | image | archive | doc | other"),
    subject: str | None = typer.Option(None, help="Regex on the subject folder or path, e.g. 'ISS|Orion'"),
    limit: int = typer.Option(25),
) -> None:
    """List nasa/NASA-3D-Resources (1,500+ files, 5 GB) without cloning it; write a catalogue with git blob ids."""
    from .space.nasa3d import fetch_catalog, save_catalog

    cat = asyncio.run(fetch_catalog(ref))
    path = save_catalog(cat, out)
    s = cat.summary()
    con.print(f"{s['assets']} assets, {s['bytes'] / 1e9:.2f} GB, {s['subjects']} subjects; by kind {s['by_kind']}")
    con.print(f"Catalogue: [bold]{path}[/]  (licence: {cat.licence[:60]}...)")
    t = Table("kind", "size", "subject", "file", "blob sha1")
    for a in cat.filter(kind, subject)[:limit]:
        t.add_row(a.kind, f"{a.size / 1e6:.1f} MB", a.subject[:40], a.name[:48], a.sha[:10])
    con.print(t)


@space_app.command("fetch")
def space_fetch(
    subject: str = typer.Argument(..., help="Regex on the subject folder or path"),
    kind: str | None = typer.Option("image", help="model | image | archive | doc; omit for all"),
    max_mb: float = typer.Option(50.0, help="Skip files larger than this"),
    limit: int = typer.Option(5),
    catalog: Path = typer.Option(Path("data/space/nasa3d_catalog.json")),
    dest: Path = typer.Option(Path("data/space/nasa3d")),
) -> None:
    """Download matching assets from the catalogue; every file is verified against its git blob id."""
    from .space.nasa3d import download, load_catalog

    cat = load_catalog(catalog)
    picks = cat.filter(kind or None, subject, max_bytes=int(max_mb * 1e6))[:limit]
    if not picks:
        raise typer.BadParameter("nothing matched; run `aero space catalog` first or loosen the filter")
    for a in picks:
        try:
            p = asyncio.run(download(a, dest, cat.ref))
            con.print(f"[green]ok[/] {a.path} ({a.size / 1e6:.1f} MB) -> {p}")
        except (ValueError, PermissionError) as e:
            con.print(f"[red]refused[/] {a.path}: {e}")


@space_app.command("images")
def space_images(
    query: str = typer.Argument(..., help="Search text, e.g. 'Artemis launch'"),
    media: str | None = typer.Option(None, help="image | video | audio"),
    year_start: int | None = typer.Option(None),
    year_end: int | None = typer.Option(None),
    limit: int = typer.Option(10),
    get: int | None = typer.Option(None, help="Download this result number"),
    variant: str = typer.Option("medium", help="orig | large | medium | small | mobile | thumb | captions | metadata"),
    dest: Path = typer.Option(Path("data/space/nasa_media")),
) -> None:
    """Search the NASA Image and Video Library; optionally download one rendition with a provenance sidecar."""
    from .space.nasa_images import download, search

    items, total = asyncio.run(search(query, media, year_start, year_end, limit))
    con.print(f"{total} hits for '{query}'{' (' + media + ')' if media else ''}; showing {len(items)}")
    t = Table("#", "nasa_id", "type", "date", "centre", "title")
    for i, it in enumerate(items, 1):
        t.add_row(str(i), it.nasa_id[:44], it.media_type, it.date_created[:10], it.center or "", it.title[:60] + (" [c]" if it.copyright else ""))
    con.print(t)
    if get:
        if not 1 <= get <= len(items):
            raise typer.BadParameter(f"--get must be 1..{len(items)}")
        it = items[get - 1]
        if it.copyright:
            con.print(f"[yellow]note: this item carries a copyright line: {it.copyright}")
        p = asyncio.run(download(it, variant, dest))
        con.print(f"[green]saved[/] {p} (+ provenance sidecar, manifest updated)")


@space_app.command("frames")
def space_frames(
    video: Path = typer.Argument(..., help="Local video file"),
    every: float = typer.Option(1.0, help="Seconds between frames"),
    max_frames: int = typer.Option(600),
    start: float = typer.Option(0.0),
    end: float | None = typer.Option(None),
    out: Path | None = typer.Option(None),
    detect: bool = typer.Option(False, help="Run the tiled detector on each frame (needs the [vision] extra)"),
    weights: str = typer.Option("yolov8n.pt"),
) -> None:
    """Extract frames with a hashed manifest; optionally detect objects on each frame."""
    from .space.footage import detect_frames, extract_frames

    m = extract_frames(video, out, every, max_frames, start, end)
    con.print(f"{len(m.frames)} frames from {video.name} ({m.fps:.2f} fps) -> {Path(m.frames[0]['file']).parent if m.frames else out}")
    if detect and m.frames:
        res = detect_frames(m, weights)
        labels: dict[str, int] = {}
        for r in res:
            for lab in r["labels"]:
                labels[lab] = labels.get(lab, 0) + 1
        con.print(f"frames with detections: {sum(1 for r in res if r['detections'])}/{len(res)}; labels {labels}")
        Path(m.frames[0]["file"]).parent.joinpath("detections.json").write_text(json.dumps(res, indent=1))


@space_app.command("captions")
def space_captions(srt: Path = typer.Argument(..., help="SRT caption file (NASA videos ship one)")) -> None:
    """Parse captions into a launch-event timeline (liftoff, max-Q, MECO, separation, SECO, landing)."""
    from .space.footage import events_from_captions, parse_srt, timeline_summary

    caps = parse_srt(srt.read_text(errors="replace"))
    summary = timeline_summary(events_from_captions(caps))
    con.print(f"{len(caps)} captions; {len(summary['events'])} milestones; gaps {summary['gaps']}")
    t = Table("t (s)", "event", "caption")
    for e in summary["events"]:
        t.add_row(f"{e['t_s']:.1f}", e["kind"], e["text"][:80])
    con.print(t)


@space_app.command("conjunctions")
def space_conjunctions(
    group: str | None = typer.Option("stations", help="CelesTrak group to fetch (stations, active, starlink, gps-ops, ...)"),
    tle: Path | None = typer.Option(None, help="Local TLE file instead of fetching"),
    hours: float = typer.Option(24.0),
    threshold_km: float = typer.Option(10.0),
    max_sets: int = typer.Option(150, help="Cap the pairwise screen (O(n^2))"),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Fetch elements (keyless, CelesTrak), propagate with SGP4, screen close approaches, flag stale sets (ORB-001..003)."""
    from .space.orbital import fetch_group, findings, parse_tle, screen

    path = tle or asyncio.run(fetch_group(group or "stations"))
    sets = parse_tle(Path(path).read_text())
    con.print(f"{len(sets)} element sets from {path}")
    res = screen(sets, None, hours, threshold_km, max_sets=max_sets)
    fs = findings(res, sets[:max_sets], stream=Path(path).stem)
    con.print(f"screened {res['pairs']} pairs over {hours:g} h: {len(res['approaches'])} approaches under {threshold_km:g} km "
              f"({len(res['co_moving'])} co-moving pairs set aside); {sum(1 for f in fs if f.rule_id == 'ORB-001')} stale sets; {len(res['propagation_errors'])} propagation errors")
    t = Table("rule", "sev", "object", "detail")
    for f in fs[:40]:
        t.add_row(f.rule_id, f.severity.value, (f.callsign or "")[:24], f.title[:70])
    con.print(t)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"conjunctions_{(group or Path(path).stem)}_{_stamp()}.json"
    jp.write_text(json.dumps({"screen": res, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}  ({res['covariance']})")


@space_app.command("cdm")
def space_cdm(
    path: Path = typer.Argument(..., help="CCSDS Conjunction Data Message (KVN)"),
    hbr_m: float = typer.Option(20.0, help="Combined hard-body radius in metres"),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Assess a CDM: probability of collision from states and covariances (2D short-encounter), ORB-004/005 findings."""
    from .space.cdm import assess, parse_cdm

    cdm = parse_cdm(path.read_text())
    res, fs = assess(cdm, hbr_m)
    if "pc" in res:
        pc = res["pc"]
        con.print(f"{cdm.message_id or path.name}: {' vs '.join(o.name or o.designator for o in cdm.objects)}  TCA {cdm.tca}")
        con.print(f"Pc = [bold]{pc['pc']:.3e}[/]  miss {pc['miss_m']:.1f} m (stated {pc['stated_miss_m']})  rel speed {pc['relative_speed_ms']:.0f} m/s  "
                  f"in-plane sigmas {pc['sigma_plane_m'][0]:.0f}/{pc['sigma_plane_m'][1]:.0f} m  HBR {hbr_m:g} m")
    else:
        con.print(f"[red]{res.get('error')}")
    for f in fs:
        con.print(f"  [{f.severity.value}] {f.rule_id} {f.title}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"cdm_{(cdm.message_id or path.stem).replace('/', '_')}_{_stamp()}.json"
    jp.write_text(json.dumps({"assessment": res, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@space_app.command("debris")
def space_debris(mission: Path = typer.Argument(..., help="Mission description JSON (see data/samples/synthetic_mission.json)"), out: Path = typer.Option(Path("reports"))) -> None:
    """Debris-mitigation checklist (NASA-STD-8719.14, ISO 24113, FCC 5-year rule): DEB-001..008 with a lifetime estimate."""
    from .space.debris import Mission, checklist

    m = Mission.from_json(mission)
    summary, fs = checklist(m)
    t = Table("rule", "requirement", "status", "detail")
    for r in summary["rows"]:
        t.add_row(r["rule"], r["requirement"], {"pass": "[green]pass", "fail": "[red]FAIL", "unknown": "[yellow]unknown"}[r["status"]], r["detail"][:90])
    con.print(t)
    con.print(f"{summary['mission']} ({summary['regime']}): {summary['passed']} pass, {summary['failed']} fail, {summary['unknown']} unknown; "
              f"estimated lifetime {summary['estimated_lifetime_years']} y")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"debris_{m.name}_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@space_app.command("cdm-inbox")
def space_cdm_inbox(inbox: Path = typer.Option(Path("data/space/cdm/inbox")), ledger: Path = typer.Option(Path("data/space/cdm/ledger.jsonl")),
                    hbr_m: float = typer.Option(20.0)) -> None:
    """Assess every new CDM (KVN or XML) in the inbox, append to the ledger, and show conjunction events with their Pc trend."""
    from .space.cdm_inbox import events, process_inbox

    r = process_inbox(inbox, ledger, hbr_m)
    con.print(f"processed {len(r['processed'])} new, skipped {r['skipped_duplicates']} duplicates, {len(r['errors'])} unreadable")
    for e in r["errors"]:
        con.print(f"  [red]{e['file']}: {e['error']}")
    t = Table("pair", "TCA", "h to TCA", "msgs", "latest Pc", "max Pc", "trend", "latest findings")
    for ev in events(ledger)[:30]:
        t.add_row(ev["pair"], (ev["tca"] or "")[:19], str(ev["hours_to_tca"]), str(ev["messages"]), f"{ev['latest_pc']:.2e}" if ev["latest_pc"] is not None else "-",
                  f"{ev['max_pc']:.2e}" if ev["max_pc"] is not None else "-", ev["trend"], ", ".join(f["rule"] for f in ev["latest_findings"]) or "-")
    con.print(t)


@space_app.command("spacetrack")
def space_spacetrack(days: int = typer.Option(7), min_pc: float = typer.Option(1e-7), ledger: Path = typer.Option(Path("data/space/cdm/ledger.jsonl"))) -> None:
    """Pull public conjunction summaries from Space-Track (SPACETRACK_USER / SPACETRACK_PASS in the environment) into the ledger."""
    from .space.cdm_inbox import record_summary
    from .space.spacetrack import SpaceTrack, SpaceTrackError

    try:
        rows = SpaceTrack().cdm_public(days, min_pc)
    except SpaceTrackError as e:
        raise typer.BadParameter(str(e)) from e
    n = record_summary(rows, ledger)
    con.print(f"{len(rows)} public conjunctions in the last {days} days above Pc {min_pc:g}; {n} new ledger rows")


@space_app.command("dataset")
def space_dataset(
    per_class: int = typer.Option(30), dest: Path = typer.Option(Path("data/space/dataset")),
    nasa3d_catalog: Path | None = typer.Option(None, help="Add NASA-3D model previews from this catalogue"),
    library: bool = typer.Option(True, "--library/--no-library", help="Search the NASA image library for the default classes"),
) -> None:
    """Build a labelled, hashed, attributed image dataset (NASA library + NASA-3D previews) with deterministic splits."""
    from .space.dataset import (
        DEFAULT_CLASSES,
        add_nasa3d_previews,
        build_from_library,
        to_classify_layout,
        write_manifest,
    )

    items = []
    if library:
        items += asyncio.run(build_from_library(DEFAULT_CLASSES, per_class, dest))
    if nasa3d_catalog:
        items += asyncio.run(add_nasa3d_previews(nasa3d_catalog, dest))
    mp = write_manifest(items, dest, DEFAULT_CLASSES)
    layout = to_classify_layout(mp)
    counts: dict[str, int] = {}
    for it in items:
        counts[it["label"]] = counts.get(it["label"], 0) + 1
    con.print(f"{len(items)} items {counts} -> {mp}; classification layout at {layout}")


@space_app.command("classify-train")
def space_classify_train(manifest: Path = typer.Argument(Path("data/space/dataset/manifest.json")), out: Path = typer.Option(Path("models/scene_classifier.joblib"))) -> None:
    """Train the scene classifier on a dataset manifest; writes the model, its card and a registry entry."""
    from .space.classifier import train

    stats = train(manifest, out)
    con.print(f"classes {stats['classes']}; {stats['n_train']} train / {stats['n_val']} val; accuracy [bold]{stats['accuracy']:.1%}[/]; sha256 {stats['sha256'][:12]}")
    for k, v in stats["per_class"].items():
        con.print(f"  {k}: P {v['precision']} R {v['recall']} n={v['support']}")


@space_app.command("classify")
def space_classify(paths: list[Path] = typer.Argument(..., help="Images, or one frames.manifest.json"), model: Path = typer.Option(Path("models/scene_classifier.joblib")),
                   allow_unverified: bool = typer.Option(False)) -> None:
    """Classify images or extracted frames with the registered scene classifier."""
    from .space.classifier import classify_frames, load, predict

    m = load(model, allow_unverified)
    if len(paths) == 1 and paths[0].name.endswith("frames.manifest.json"):
        rows = classify_frames(json.loads(paths[0].read_text()), m)
        for r in rows:
            con.print(f"  t={r['t_s']:8.2f}s  {r['label']:<10} {r['proba']:.2f}")
        return
    for r in predict(m, [str(p) for p in paths]):
        con.print(f"  {r['label']:<10} {r['proba']:.2f}  {r['path']}")


@space_app.command("weather")
def space_weather_cmd(file: Path | None = typer.Option(None, help="Cached or sample SWPC product instead of fetching (e.g. data/samples/swpc_scales_sample.json)"),
                      recording: Path | None = typer.Option(None, help="Recording whose high-latitude traffic to list as exposed"),
                      lat_min: float = typer.Option(60.0, help="Poleward of this latitude counts as exposed"), out: Path = typer.Option(Path("reports"))) -> None:
    """NOAA SWPC scales and Kp (keyless) mapped to ICAO advisory conditions (SWX-001..004); optionally the flights exposed (SWX-005)."""
    from .space import spaceweather

    path = file or asyncio.run(spaceweather.fetch())
    summary, fs = spaceweather.assess(json.loads(Path(path).read_text()))
    if recording:
        exp, fs2 = spaceweather.exposed_flights(recording, summary["icao_advisory_conditions"], lat_min)
        summary["exposed"] = exp
        fs += fs2
    con.print(f"product {summary['product_time']}: R{summary['scales_now']['R']} S{summary['scales_now']['S']} G{summary['scales_now']['G']} · Kp {summary['kp']} · "
              f"ICAO conditions {summary['icao_advisory_conditions']}" + (f" · exposed aircraft {summary['exposed']['aircraft']}" if recording else ""))
    for f in fs:
        con.print(f"  {f.rule_id} [{f.severity.value}] {f.title}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"space_weather_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@space_app.command("launches")
def space_launches_cmd(mode: str = typer.Option("upcoming", help="upcoming | previous"), limit: int = typer.Option(20),
                       file: Path | None = typer.Option(None, help="Cached or sample launch file instead of fetching (e.g. data/samples/ll2_launches_sample.json)"),
                       recording: Path | None = typer.Option(None, help="Recording to join: aircraft inside the hazard radius during each window"),
                       hazard_nm: float = typer.Option(50.0), out: Path = typer.Option(Path("reports"))) -> None:
    """Launch windows and pads from Launch Library 2 (keyless, 15/h); joined to a recording they give LCH-001..003."""
    from .space import launches

    path = file or asyncio.run(launches.fetch(mode, limit))
    payload = json.loads(Path(path).read_text())
    rows = payload.get("launches", [])
    t = Table("launch", "provider", "status", "window start", "pad", "location")
    for r in rows[:20]:
        t.add_row((r.get("name") or "")[:40], (r.get("provider") or "")[:20], str(r.get("status")), str(r.get("window_start")), str(r.get("pad"))[:22], str(r.get("location"))[:30])
    con.print(t)
    if recording:
        summary, fs = launches.join_traffic(payload, recording, hazard_nm)
        con.print(f"{summary['overlapping']} window(s) overlap the recording; findings {len(fs)}")
        for f in fs:
            con.print(f"  {f.rule_id} [{f.severity.value}] {f.title}")
        out.mkdir(parents=True, exist_ok=True)
        jp = out / f"launches_{_stamp()}.json"
        jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
        con.print(f"Report: {jp}")


@space_app.command("watch")
def space_watch(schedule: str = typer.Option("cdm_inbox=600,space_weather=900,launches=3600", help="job=seconds,... (jobs: cdm_inbox spacetrack_pull conjunctions space_weather launches catalog_build)"),
                offline: bool = typer.Option(False, help="Skip network jobs"), once: bool = typer.Option(False, help="Run every job once and exit")) -> None:
    """Headless scheduled intake without the web app: the same job registry, the same reports, one log line per run."""
    import time as _time

    from .web.jobs import JobManager
    from .web.schedule import Scheduler, parse_schedule
    from .web.space_jobs import REGISTRY

    jm = JobManager(REGISTRY, persist=Path("data/app/jobs.json"))
    sched = Scheduler(lambda t, p: jm.submit(t, p), set(REGISTRY), parse_schedule(schedule), offline=offline)
    if sched.unknown:
        raise typer.BadParameter(f"unknown job(s): {', '.join(sched.unknown)}")
    con.print(f"watching: {sched.schedule} (offline={offline}); Ctrl-C to stop")
    try:
        while True:
            for name in sched.tick(_time.time() + (1e9 if once else 0.0)):
                con.print(f"{_stamp()} submitted {name}")
            if once:
                while any(j.status in ("queued", "running") for j in jm.jobs.values()):
                    _time.sleep(0.5)
                for j in jm.jobs.values():
                    con.print(f"  {j.type}: {j.status} {j.error or json.dumps(j.result, default=str)[:160]}")
                break
            _time.sleep(5)
    except KeyboardInterrupt:
        con.print("stopped")


@space_app.command("render")
def space_render(model: Path = typer.Argument(..., help="Wavefront OBJ model"), label: str | None = typer.Option(None, help="Class label (default: file stem)"),
                 n_yaw: int = typer.Option(12), size: int = typer.Option(256), dest: Path = typer.Option(Path("data/space/renders")),
                 manifest: Path | None = typer.Option(None, help="Append the renders as items to this dataset manifest")) -> None:
    """Multi-view silhouette renders of an OBJ model (numpy z-buffer) for training data, with a manifest and optional dataset append."""
    from .space import render
    from .space.dataset import load_manifest, write_manifest

    m = render.render_views(model, dest, label, size, n_yaw)
    con.print(f"{len(m['views'])} views of {m['label']} ({m['vertices']} vertices, {m['triangles']} triangles) under {Path(m['views'][0]['file']).parent}")
    if manifest:
        items = render.dataset_items(m)
        old = load_manifest(manifest)["items"] if manifest.is_file() else []
        mp = write_manifest(old + items, manifest.parent)
        con.print(f"Manifest: {mp} (+{len(items)} items)")


@space_app.command("maneuvers")
def space_maneuvers(files: list[Path] | None = typer.Argument(None, help="Element files (default: every cached .tle)"), out: Path = typer.Option(Path("reports"))) -> None:
    """Element history per object: manoeuvre-scale changes (ORB-006) and imminent decay (ORB-007) from cached element sets."""
    from .space import maneuvers

    summary, fs = maneuvers.analyse(files or None)
    con.print(f"{summary['objects']} objects from {len(summary['files'])} file(s), {summary['with_history']} with history: {len(summary['changes'])} changes, {len(summary['decaying'])} decaying")
    for f in fs[:30]:
        con.print(f"  {f.rule_id} [{f.severity.value}] {f.title}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"maneuvers_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@space_app.command("telemetry-audit")
def space_telemetry(
    csv_path: Path = typer.Argument(..., help="CSV with t_s, speed_mps|speed_kmh, altitude_km|altitude_m"),
    name: str | None = typer.Option(None),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Physics checks on a launch telemetry stream (SPC-001..005); writes JSON and Markdown reports."""
    from .space.telemetry import audit_telemetry, load_csv, summarize, write_report

    pts = load_csv(csv_path)
    findings = audit_telemetry(pts, stream=csv_path.stem)
    s = summarize(pts, findings)
    con.print(f"{s['samples']} samples, max {s['max_speed_mps']} m/s, {s['max_altitude_km']} km; findings {s['findings']} {s['by_rule']}")
    for f in findings:
        con.print(f"  [{f.severity.value}] {f.rule_id} t={f.ts}s {f.title}")
    jp, mp = write_report(pts, findings, out, f"{name or csv_path.stem}_telemetry_{_stamp()}")
    con.print(f"Reports: {mp}, {jp}")


# ---- governance: the bird's-eye view ----------------------------------------------------------
gov_app = typer.Typer(help="Holistic governance: domains, standards, controls with evidence, unified register, studies, posture.")
app.add_typer(gov_app, name="gov")


@gov_app.command("domains")
def gov_domains() -> None:
    """Air and space domains with status, rules, standards and upstream projects adopted."""
    from .governance import DOMAINS, coverage

    cov = coverage()["by_domain"]
    t = Table("domain", "status", "rules", "impl / partial / planned", "data sources", "adopts")
    for d in DOMAINS.values():
        k = cov[d.key]
        t.add_row(d.key, d.status, ",".join(d.rule_prefixes) or "-", f"{k['implemented']} / {k['partial']} / {k['planned']}", "; ".join(d.data_sources)[:60], ", ".join(d.upstream)[:60])
    con.print(t)


@gov_app.command("standards")
def gov_standards(area: str | None = typer.Option(None, help="air | space | cyber | software | data")) -> None:
    """Standards library with the number of controls mapped to each."""
    from .governance import STANDARDS, coverage

    cov = coverage()["by_standard"]
    t = Table("id", "standard", "body", "area", "impl / partial / planned")
    for s in STANDARDS.values():
        if area and s.area != area:
            continue
        v = cov[s.id]
        t.add_row(s.id, s.title[:60], s.body, s.area, f"{v['implemented']} / {v['partial']} / {v['planned']}")
    con.print(t)


@gov_app.command("controls")
def gov_controls(pillar: str | None = typer.Option(None), status: str | None = typer.Option(None), check: bool = typer.Option(False, help="Verify file-backed evidence exists")) -> None:
    """Controls with typed evidence; --check verifies that referenced files exist."""
    from .governance import CONTROLS, implementation_index
    from .governance.controls import evidence_present, validate

    problems = validate()
    t = Table("id", "pillar", "control", "status", "domains", "evidence")
    for c in CONTROLS.values():
        if (pillar and c.pillar != pillar) or (status and c.status != status):
            continue
        ev = "; ".join(c.evidence)[:70]
        if check:
            missing = [e for e, ok in evidence_present(c).items() if not ok]
            ev = ("[red]missing: " + ", ".join(missing)) if missing else "[green]all present"
        t.add_row(c.id, c.pillar, c.title[:52], c.status, ",".join(c.domains)[:36], ev)
    con.print(t)
    con.print(f"implementation index {implementation_index():.0%}; library {'clean' if not problems else 'PROBLEMS: ' + '; '.join(problems)}")
    if problems:
        raise typer.Exit(1)


@gov_app.command("risks")
def gov_risks(recording: list[Path] | None = typer.Argument(None, help="Recordings whose audits adjust the air rows")) -> None:
    """Unified air and space register (residual from evidence for air, from control status elsewhere)."""
    from .governance import unified_register
    from .governance.register import by_rating
    from .risk.register import merge_summaries

    summary = None
    if recording:
        summaries = []
        for rp in recording:
            eng = AuditEngine()
            for b in iter_recording(rp):
                eng.process_batch(b)
            summaries.append(eng.summary())
        summary = merge_summaries(summaries)
    rows = unified_register(summary)
    t = Table("id", "domain", "risk", "L", "I", "inherent", "residual", "controls / evidence")
    for r in rows:
        color = {"critical": "red", "high": "yellow", "medium": "cyan", "low": "green"}[r["residual_rating"]]
        t.add_row(r["id"], r["domain"], r["title"][:56], str(r["L"]), str(r["I"]), f"{r['score']} {r['rating']}", f"[{color}]{r['residual']} {r['residual_rating']}",
                  ", ".join(r.get("controls") or r.get("evidence") or [])[:40])
    con.print(t)
    con.print(f"by residual rating: {by_rating(rows)}  (basis: {'session evidence' if summary else 'baseline'})")


@gov_app.command("studies")
def gov_studies() -> None:
    """Study registry: runnable now, needs network, or planned with the upstream method named."""
    from .governance import STUDIES
    from .governance.studies import latest_results

    latest = latest_results()
    t = Table("id", "study", "domain", "status", "inputs", "last result")
    for s in STUDIES.values():
        t.add_row(s.id, s.title[:50], s.domain, s.status, ", ".join(s.inputs)[:40], Path(latest[s.id]["file"]).name if s.id in latest else "-")
    con.print(t)


@gov_app.command("run-study")
def gov_run_study(
    study_id: str = typer.Argument(..., help="e.g. ST-01"),
    recording: Path | None = typer.Option(None),
    csv_path: Path | None = typer.Option(None, "--csv"),
    catalog: Path | None = typer.Option(None),
    geojson: Path | None = typer.Option(None, help="Crisis extent (GeoJSON) for ST-11"),
    tle: list[Path] | None = typer.Option(None, help="TLE file for ST-06; repeat for ST-20 element history"),
    cdm_path: Path | None = typer.Option(None, "--cdm", help="CDM file for ST-12"),
    mission: Path | None = typer.Option(None, help="Mission JSON for ST-13"),
    scales: Path | None = typer.Option(None, help="SWPC product file for ST-17 (default: the bundled sample)"),
    launches: Path | None = typer.Option(None, help="Launch file for ST-18 (default: the bundled sample)"),
    out: Path = typer.Option(Path("reports/studies")),
) -> None:
    """Run a study with provenance; results in reports/studies/."""
    from .governance import run_study

    params: dict[str, object] = {}
    if recording:
        params["recording"] = recording
    if csv_path:
        params["csv"] = csv_path
    if catalog:
        params["catalog"] = catalog
    if geojson:
        params["geojson"] = geojson
    if tle:
        params["tle"] = tle[0]
        if len(tle) > 1:
            params["files"] = tle
    if cdm_path:
        params["cdm"] = cdm_path
    if mission:
        params["mission"] = mission
    if scales:
        params["scales"] = scales
    if launches:
        params["launches"] = launches
    try:
        rec = run_study(study_id.upper(), out, **params)
    except (KeyError, RuntimeError, FileNotFoundError, TypeError) as e:
        raise typer.BadParameter(str(e)) from e
    res = rec["result"]
    con.print(json.dumps({k: v for k, v in res.items() if k not in ("operators", "findings_detail", "top_subjects", "by_airport")}, indent=1, default=str)[:2500])
    con.print(f"Result: [bold]{rec['files']['md']}[/] ({rec['duration_s']} s)")


@gov_app.command("traceability")
def gov_traceability(out: Path | None = typer.Option(None, help="Write the Markdown here"), gaps_only: bool = typer.Option(False)) -> None:
    """Bidirectional traceability: controls to standards, rules, modules, tests and studies, and back; gaps first."""
    from .governance import traceability as tr

    cov = tr.coverage()
    con.print("coverage: " + " · ".join(f"{k} {v:.0%}" for k, v in cov.items()))
    for k, v in tr.gaps().items():
        con.print(f"  {k}: {', '.join(v) if v else '[green]none'}")
    if out and not gaps_only:
        out.write_text(tr.render_markdown())
        con.print(f"Wrote {out}")


@gov_app.command("assurance")
def gov_assurance(out: Path | None = typer.Option(None, help="Write the Markdown to this path")) -> None:
    """NPR 7150.2 classification per component, the SLIM repository checklist evaluated on this tree, SDLS expectations."""
    from .governance.assurance import classification, render_markdown, slim_checklist

    t = Table("component", "class", "safety", "paths")
    for r in classification():
        t.add_row(r["component"], r["class"], "yes" if r["safety_related"] else "no", r["path"][:50])
    con.print(t)
    s = slim_checklist(".")
    con.print(f"SLIM checklist {s['passed']}/{s['total']} ({s['score']:.0%}); missing: {', '.join(r['id'] + ' ' + r['title'] for r in s['rows'] if not r['ok']) or 'none'}")
    if out:
        out.write_text(render_markdown("."))
        con.print(f"wrote {out}")


@gov_app.command("posture")
def gov_posture(
    recording: list[Path] | None = typer.Argument(None, help="Recordings whose audits provide session evidence"),
    as_json: bool = typer.Option(False, "--json"),
    out: Path | None = typer.Option(None, help="Write the Markdown posture report here"),
) -> None:
    """The bird's-eye view: governance index, domains, pillars, unified risks, studies, evidence on disk."""
    from .governance import posture, render_posture
    from .risk.register import merge_summaries

    summary = None
    if recording:
        summaries = []
        for rp in recording:
            eng = AuditEngine()
            for b in iter_recording(rp):
                eng.process_batch(b)
            summaries.append(eng.summary())
        summary = merge_summaries(summaries)
    p = posture(summary)
    if as_json:
        con.print(json.dumps(p, indent=1, default=str))
        return
    c = p["components"]
    con.print(f"[bold]Governance index {p['governance_index']:.0%}[/]  controls {c['controls_implementation']:.0%} · standards {c['standards_coverage']:.0%} · "
              f"risk low/medium {c['risk_share_low_or_medium']:.0%} · studies runnable {c['studies_runnable_share']:.0%} · evidence freshness {c['evidence_freshness']:.0%}  ({p['evidence_basis']})")
    t = Table("domain", "status", "rules", "impl / partial / planned")
    for d in p["domains"]:
        k = d["controls"]
        t.add_row(d["name"], d["status"], str(d["rules"]), f"{k['implemented']} / {k['partial']} / {k['planned']}")
    con.print(t)
    con.print(f"residual risks: {p['risks']['by_residual']}; top: " + "; ".join(f"{r['id']} {r['rating']} ({r['residual']})" for r in p["risks"]["top_residual"]))
    f = p["freshness"]
    con.print(f"evidence: chain {'ok' if f['audit_chain_ok'] else 'absent/broken'} · model verified {f['model_verified']} · latest report {f['latest_report_age_h']} h · "
              f"evaluation {f['evaluation_age_days']} d · study results {f['study_results']}")
    if p["evidence"]["missing"]:
        con.print(f"[yellow]evidence claimed but not on disk: {', '.join(p['evidence']['missing'])}")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_posture(p))
        con.print(f"wrote {out}")
# ---- UAS: well-clear metrics, encounters, UTM contracts ------------------------------------------
uas_app = typer.Typer(help="UAS integration: DO-365 / DAIDALUS well-clear metrics on recordings, encounter rates, UTM contract checks.")
app.add_typer(uas_app, name="uas")


@uas_app.command("wellclear")
def uas_wellclear(recording: Path = typer.Argument(..., help="Recording (.jsonl / .jsonl.gz)"), max_batches: int | None = typer.Option(None),
                  out: Path = typer.Option(Path("reports"))) -> None:
    """Encounters from a recording scored with the well-clear definitions: violations per flight hour, NMAC-proximate pairs, alert lead time."""
    from .uas import extract_encounters, summarize_encounters

    ex = extract_encounters(recording, max_batches=max_batches)
    summary, fs = summarize_encounters(ex)
    con.print(f"{summary['aircraft_airborne']} airborne aircraft, {summary['flight_hours']} flight hours, {summary['encounter_pairs']} encounter pairs; "
              f"violations {summary['violations']} ({summary['violations_per_flight_hour']}/fh), NMAC-proximate {summary['nmac_proximate']}, "
              f"pairs alerted {summary['pairs_with_alert']}, median lead {summary['median_lead_time_s']} s")
    t = Table("pair", "region", "min range ft", "min dz ft", "min HMD ft", "alert", "violation", "lead s")
    for r in summary["pairs"][:25]:
        t.add_row(r["callsigns"][:28], r["region"], f"{r['min_range_ft']:.0f}", f"{r['min_dz_ft']:.0f}", f"{r['min_hmd_ft']:.0f}", str(r["max_alert"]),
                  "[red]yes" if r["violation"] else "no", str(r["lead_time_s"]))
    con.print(t)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"wellclear_{recording.stem.split('.')[0]}_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@uas_app.command("risk")
def uas_risk_cmd(recording: Path = typer.Argument(..., help="Recording (.jsonl / .jsonl.gz)"), max_batches: int | None = typer.Option(None), out: Path = typer.Option(Path("reports"))) -> None:
    """Airspace density classes per altitude band and the observed DAA risk ratio (DAA-003/004)."""
    from .uas import risk

    summary, fs = risk.assess(recording, max_batches=max_batches)
    rr = summary["risk_ratio"]
    con.print(f"{summary['flight_hours']} flight hours; encounters {rr['encounters']}, NMAC-proximate {rr['nmac_proximate']}, unresolvable {rr['unresolvable']}; risk ratio {rr['risk_ratio']} (limit {rr['limit']})")
    t = Table("band ft", "aircraft-hours", "cells", "sparse", "moderate", "dense", "very dense")
    for band, v in summary["density"]["bands"].items():
        c = v["classes"]
        t.add_row(band, str(v["aircraft_hours"]), str(v["cells"]), str(c.get("sparse", 0)), str(c.get("moderate", 0)), str(c.get("dense", 0)), str(c.get("very-dense", 0)))
    con.print(t)
    for f in fs:
        con.print(f"  {f.rule_id} [{f.severity.value}] {f.title}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"uas_risk_{recording.stem.split('.')[0]}_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    con.print(f"Report: {jp}")


@uas_app.command("encounter-model")
def uas_encounter_model(recording: Path = typer.Argument(...), n: int = typer.Option(2000, help="Simulated encounters"), horizon_s: float = typer.Option(25.0),
                        seed: int = typer.Option(0), max_batches: int | None = typer.Option(None), out: Path = typer.Option(Path("reports"))) -> None:
    """Fit an encounter model from the recording's encounters and estimate NMAC probability with and without an alerting horizon (Monte Carlo)."""
    from .uas import encounter_model as em

    res = em.fit_and_simulate(recording, n, horizon_s, seed, max_batches)
    m, sm = res["model"], res["simulation"]
    con.print(f"fitted from {m['n']} pairs over {m['flight_hours']} fh (range p10/50/90 {m['range_ft_q']} ft); simulated {sm['n']}: "
              f"P(NMAC) {sm['p_nmac_unmitigated']} unmitigated, {sm['p_nmac_mitigated']} with a {horizon_s:g} s horizon; model risk ratio {sm['risk_ratio']}")
    if sm["rates"]:
        con.print(f"per flight hour: encounters {sm['rates']['encounters_per_fh']}, NMAC {sm['rates']['nmac_per_fh_unmitigated']} -> {sm['rates']['nmac_per_fh_mitigated']}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"encounter_model_{recording.stem.split('.')[0]}_{_stamp()}.json"
    jp.write_text(json.dumps({"summary": res, "findings": []}, indent=1, default=str))
    con.print(f"Report: {jp}")


@uas_app.command("utm-check")
def uas_utm_check(spec: Path = typer.Argument(..., help="OpenAPI document (JSON)"), sample: list[Path] = typer.Argument(..., help="JSON samples to validate"),
                  schema: str | None = typer.Option(None, help="Component schema name"), path: str | None = typer.Option(None, help="Endpoint path for a response schema"),
                  method: str = typer.Option("get"), status: str = typer.Option("200")) -> None:
    """Validate captured exchanges against an OpenAPI contract (NASA utm-apis or this app's own document)."""
    from .uas.utm import check_samples, load_document

    doc = load_document(spec)
    samples = [(p.name, json.loads(p.read_text())) for p in sample]
    rep = check_samples(doc, samples, schema, path, method, status)
    con.print(f"{rep['schema']}: {rep['conformant']}/{rep['samples']} conformant")
    for r in rep["rows"]:
        con.print(f"  {'[green]ok  ' if r['ok'] else '[red]FAIL'}[/] {r['sample']}" + ("" if r["ok"] else ": " + "; ".join(r["problems"][:5])))
    if rep["conformant"] != rep["samples"]:
        raise typer.Exit(1)


# ---- observability -------------------------------------------------------------------------------
obs_app = typer.Typer(help="Metrics, probes and structured logs of a running app, or the local log file.")
app.add_typer(obs_app, name="obs")


def _fetch(url: str, token: str | None) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"X-Aero-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


@obs_app.command("health")
def obs_health(url: str = typer.Option("http://127.0.0.1:8787"), token: str | None = typer.Option(None, envvar="AERO_APP_TOKEN")) -> None:
    """Liveness and readiness of a running app (exit 1 when not ready)."""
    import urllib.error

    con.print(json.loads(_fetch(f"{url}/healthz", token)))
    try:
        body = json.loads(_fetch(f"{url}/readyz", token))
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
    t = Table("check", "ok", "detail")
    for name, c in body.get("checks", {}).items():
        t.add_row(name, "[green]yes" if c.get("ok") else "[red]NO", ", ".join(f"{k}={v}" for k, v in c.items() if k != "ok"))
    con.print(t)
    con.print(f"status: {body.get('status')}")
    if body.get("status") != "ready":
        raise typer.Exit(1)


@obs_app.command("metrics")
def obs_metrics(url: str = typer.Option("http://127.0.0.1:8787"), token: str | None = typer.Option(None, envvar="AERO_APP_TOKEN"),
                raw: bool = typer.Option(False, help="Print the Prometheus exposition text")) -> None:
    """Key metrics of a running app (or the raw /metrics text)."""
    if raw:
        con.print(_fetch(f"{url}/metrics", token).decode(), highlight=False, markup=False)
        return
    o = json.loads(_fetch(f"{url}/api/v1/observability", token))
    t = Table("kpi", "value")
    for k, v in o["kpis"].items():
        t.add_row(k, str(v))
    con.print(t)
    con.print(f"ready={o['ready']} version={o['health']['version']} uptime={o['health']['uptime_s']} s")


@obs_app.command("logs")
def obs_logs(limit: int = typer.Option(50), level: str | None = typer.Option(None), event: str | None = typer.Option(None),
             path: Path = typer.Option(Path("logs/app.jsonl")), follow: bool = typer.Option(False, "-f", "--follow")) -> None:
    """Tail the structured log (newest first; -f streams new lines)."""
    from .observability import tail_logs

    def show(rows: list[dict]) -> None:
        for e in reversed(rows):
            extra = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "level", "event", "logger"))
            colour = {"error": "red", "warning": "yellow"}.get(e.get("level"), "white")
            con.print(f"[{colour}]{datetime.fromtimestamp(e['ts'], UTC).strftime('%H:%M:%S')} {e['level']:<7} {e['event']:<18}[/] {extra[:200]}", highlight=False, markup=True)

    show(tail_logs(limit, level, event, path))
    if follow:
        import os as _os

        with open(path) as fh:
            fh.seek(0, _os.SEEK_END)
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if (level and e.get("level") != level) or (event and event not in e.get("event", "")):
                    continue
                show([e])


@app.command()
def bench(
    recording: Path | None = typer.Option(None, help="Recording (default: the largest bundled sample)"),
    rounds: int = typer.Option(3),
    model: Path | None = typer.Option(None, help="Model to include (verified against the registry)"),
    suite: str = typer.Option("engine", help="engine | space | all: the rules engine, or the space/UAS hot paths (encounters, projection, rasteriser, screen, catalogue)"),
    out: Path = typer.Option(Path("reports")),
) -> None:
    """Throughput of the rules engine on a recording (batches/s, state vectors/s, per-batch p50/p95) and, with --suite space, the
    space and UAS hot paths. Writes reports/bench_*.json."""
    import statistics

    from .provenance import build as build_prov

    if suite in ("space", "all"):
        from .bench_space import run_suite

        rows = run_suite(recording or _demo_recording(), rounds)
        t = Table("case", "input", "best s", "median s", "rate")
        for r in rows:
            t.add_row(r["case"], r["input"], f"{r['best_s']:.3f}", f"{r['median_s']:.3f}", r["rate"])
        con.print(t)
        out.mkdir(parents=True, exist_ok=True)
        jp = out / f"bench_space_{_stamp()}.json"
        jp.write_text(json.dumps({"suite": "space", "rounds": rounds, "cases": rows}, indent=1, default=str))
        con.print(f"Wrote {jp}")
        if suite == "space":
            return
    rec = recording or _demo_recording()
    if rec is None:
        raise typer.BadParameter("no recording; pass --recording")
    batches = list(iter_recording(rec))
    states = sum(len(b.states) for b in batches)
    results = []
    for r in range(rounds):
        eng = _build_engine(model, None, None, None, "high")
        per = []
        t0 = time.perf_counter()
        for b in batches:
            tb = time.perf_counter()
            eng.process_batch(b)
            per.append(time.perf_counter() - tb)
        wall = time.perf_counter() - t0
        per.sort()
        results.append({"round": r + 1, "wall_s": round(wall, 3), "batches_per_s": round(len(batches) / wall, 1), "states_per_s": round(states / wall),
                        "batch_p50_ms": round(per[len(per) // 2] * 1000, 2), "batch_p95_ms": round(per[int(0.95 * (len(per) - 1))] * 1000, 2),
                        "batch_max_ms": round(per[-1] * 1000, 2), "findings": len(eng.findings)})
    best = max(results, key=lambda x: x["states_per_s"])
    t = Table("round", "wall s", "batches/s", "states/s", "p50 ms", "p95 ms", "max ms", "findings")
    for x in results:
        t.add_row(*(str(x[k]) for k in ("round", "wall_s", "batches_per_s", "states_per_s", "batch_p50_ms", "batch_p95_ms", "batch_max_ms", "findings")))
    con.print(t)
    con.print(f"{rec.name}: {len(batches)} batches, {states} state vectors; best {best['states_per_s']} states/s; "
              f"median batches/s {statistics.median(x['batches_per_s'] for x in results)}")
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"bench_{_stamp()}.json"
    jp.write_text(json.dumps({"recording": str(rec), "batches": len(batches), "state_vectors": states, "model": str(model) if model else None,
                              "rounds": results, "provenance": build_prov(eng)}, indent=1, default=str))
    con.print(f"Wrote {jp}")


if __name__ == "__main__":
    app()
