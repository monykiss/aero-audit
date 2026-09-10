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
) -> AuditEngine:
    from .alerts import Alerter, JsonlSink, WebhookSink
    from .audit.findings import Severity
    from .security import Watchlist

    ml = None
    if model:
        from .ml import KinematicAnomalyModel

        ml = KinematicAnomalyModel.load(model)
        con.print(f"Loaded model {model} (threshold {ml.threshold_:.4f}, trained on {ml.n_train_} rows)")
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
) -> None:
    """Run the rules engine (+ optional ML model) and write JSON + Markdown reports."""
    engine = _build_engine(model, watchlist, alert_webhook, alert_log, alert_min_severity)

    if recording:
        for b in iter_recording(recording):
            engine.process_batch(b)
        name = name or recording.stem
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
    else:
        raise typer.BadParameter("Pass --recording PATH or --live")

    _print_summary(engine)
    jp, mp, hp = write_reports(engine, out, name)
    con.print(f"Reports: [bold]{mp}[/], {hp}, {jp}")


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
) -> None:
    """Inject attack scenarios into real traffic; measure recall, time-to-detect, and per-rule precision."""
    from .ml.evaluate import SCENARIOS, write_evaluation
    from .ml.evaluate import evaluate as _evaluate

    unknown = set(scenario or []) - set(SCENARIOS)
    if unknown:
        raise typer.BadParameter(f"unknown scenarios {unknown}; known: {', '.join(SCENARIOS)}")
    rep = _evaluate(recording, model, targets, seed, scenario or None, max_batches, onset)
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


@app.command("app")
def app_cmd(
    port: int = typer.Option(8787),
    host: str = typer.Option("127.0.0.1"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser automatically"),
) -> None:
    """Start the local app (home screen, live map, findings, risk, reports, data, settings, help)."""
    from .web.app import run_app

    con.print(f"[bold]aero-audit app[/] http://{host}:{port}/  (Ctrl+C to stop)")
    run_app(port, host, open_browser)


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
    con.print(f"[bold]aero-audit app[/] http://{host}:{port}/  preset={preset}  (Ctrl+C to stop)")
    run_app(port, host, open_browser, preset=preset)


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


if __name__ == "__main__":
    app()
