"""Space, UAS and catalogue jobs: plain functions with the (job, params) signature the JobManager runs,
so the app's job list, the scheduler and the headless ``aero space watch`` loop share one registry.
Each writes the report shape the CLI writes (reports/<prefix>_<stamp>.json with summary and findings)
and counts its findings in the metrics like the live engine does."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import observability as obs
from .jobs import Job

REPORTS = Path("reports")
SPACE_ROOTS = ("data/space", "data/samples", "data/airspace")
JSON_SUFFIXES = (".json",)
ELEMENT_SUFFIXES = (".tle", ".txt")


def _confine(value: Any, suffixes: tuple[str, ...], must_exist: bool = True) -> Path:
    """Every path a job accepts from a request body must live under data/space or data/samples: jobs are token-gated,
    but a path is still user input and the catalogue of what a job may read or write is part of the contract."""
    from .security import safe_path

    return safe_path(value, SPACE_ROOTS, suffixes, must_exist=must_exist)


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _recording_path(value: Any) -> Path:
    """Same confinement as App.recording_path, without importing the app (no import cycle)."""
    from ..ingest.replay import RECORDING_SUFFIXES
    from .security import safe_path

    return safe_path(value, ("data/recordings", "data/samples"), RECORDING_SUFFIXES)


def _write_report(prefix: str, summary: dict[str, Any], findings: list[Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..audit.generic_report import write_generic

    p = write_generic(REPORTS, prefix, "summary", summary, findings, inputs=inputs)["json"]
    for f in findings:
        obs.METRICS.inc("aero_findings_total", rule=f.rule_id, severity=f.severity.value)
    return {"report": str(p), "findings": len(findings), "worst": max((f.severity.value for f in findings), default=None)}


def cdm_inbox(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import cdm_inbox as inbox

    inbox_dir = _confine(p["inbox"], (), must_exist=False) if p.get("inbox") else inbox.INBOX
    ledger = _confine(p["ledger"], (".jsonl",), must_exist=False) if p.get("ledger") else inbox.LEDGER
    res = inbox.process_inbox(inbox_dir, ledger, float(p.get("hbr_m") or 20.0))
    ev = inbox.events(ledger)
    n_new = len(res["processed"]) if isinstance(res.get("processed"), list) else int(res.get("processed") or 0)
    escalating = sum(1 for e in ev if e.get("trend") == "escalating")
    obs.METRICS.set("aero_cdm_events", float(len(ev)), trend="all")
    obs.METRICS.set("aero_cdm_events", float(escalating), trend="escalating")
    job.say(f"{n_new} new message(s), {len(ev)} event(s), {escalating} escalating")
    return {"processed": n_new, "skipped": res.get("skipped_duplicates"), "events": len(ev), "escalating": escalating}


def spacetrack_pull(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import cdm_inbox as inbox
    from ..space.spacetrack import SpaceTrack

    st = SpaceTrack()
    rows = st.cdm_public(int(p.get("days") or 7), float(p.get("min_pc") or 1e-7))
    n = inbox.record_summary(rows, _confine(p["ledger"], (".jsonl",), must_exist=False) if p.get("ledger") else inbox.LEDGER)
    job.say(f"{len(rows)} summaries, {n} new in the ledger")
    return {"summaries": len(rows), "recorded": n}


def conjunctions(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space.orbital import fetch_group, findings, parse_tle, screen

    group = p.get("group") or "stations"
    err = None
    if p.get("tle"):
        path = _confine(p["tle"], ELEMENT_SUFFIXES)
    else:
        from ..space.orbital import ELEMENTS_DIR

        def _latest_group() -> Path | None:
            files = sorted(ELEMENTS_DIR.glob(f"celestrak_{group}_*.tle")) if ELEMENTS_DIR.is_dir() else []
            return files[-1] if files else None

        path, err = _fetch_or_cached(job, lambda: asyncio.run(fetch_group(group)), _latest_group, "conjunctions")
    sets = parse_tle(Path(path).read_text())
    max_sets = int(p.get("max_sets") or 150)
    res = screen(sets, None, float(p.get("hours") or 24.0), float(p.get("threshold_km") or 10.0), max_sets=max_sets)
    fs = findings(res, sets[:max_sets], stream=Path(path).stem)
    from ..space import satcat as sc

    cat = sc.load()
    if cat:
        fs += sc.findings_for_elements([s.norad_id for s in sets[:max_sets]], cat, stream=Path(path).stem)
        ids = {a["a_norad"] for a in res["approaches"]} | {a["b_norad"] for a in res["approaches"]}
        res["catalogue"] = {str(n): sc.enrich([n], cat)[n] for n in list(ids)[:100]}
    job.say(f"{len(sets)} sets, {len(res['approaches'])} approaches")
    REPORTS.mkdir(parents=True, exist_ok=True)
    from ..audit.generic_report import write_generic

    res["degraded"] = err is not None
    res["fetch_error"] = err
    rp = write_generic(REPORTS, f"conjunctions_{Path(path).stem}", "screen", res, fs, inputs={"elements": path})["json"]
    for f in fs:
        obs.METRICS.inc("aero_findings_total", rule=f.rule_id, severity=f.severity.value)
    return {"report": str(rp), "sets": len(sets), "approaches": len(res["approaches"]), "findings": len(fs), "degraded": err is not None}


def _fetch_or_cached(job: Job, fetch: Any, latest: Any, what: str) -> tuple[Path, str | None]:
    """Availability over freshness: when the live fetch fails, use the newest cached product and say so (the product's
    own age then drives the stale finding); with nothing cached the failure propagates."""
    try:
        return Path(fetch()), None
    except Exception as e:
        cached = latest()
        err = f"{type(e).__name__}: {str(e)[:160]}"
        if cached is None:
            raise RuntimeError(f"{what}: fetch failed ({err}) and nothing is cached") from e
        job.say(f"{what}: fetch failed ({err}); using cached {Path(cached).name}")
        obs.log_event("feed.degraded", "warning", source=what, error=err, cached=str(cached))
        obs.METRICS.inc("aero_feed_degraded_total", source=what)
        return Path(cached), err


def space_weather(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space import spaceweather

    err = None
    if p.get("file"):
        path = _confine(p["file"], JSON_SUFFIXES)
    else:
        path, err = _fetch_or_cached(job, lambda: asyncio.run(spaceweather.fetch()), spaceweather.latest, "space_weather")
    payload = json.loads(Path(path).read_text())
    summary, fs = spaceweather.assess(payload)
    summary["degraded"] = err is not None
    summary["fetch_error"] = err
    if p.get("recording"):
        exp, fs2 = spaceweather.exposed_flights(_recording_path(p["recording"]), summary["icao_advisory_conditions"], float(p.get("lat_min") or spaceweather.HIGH_LAT_DEG))
        summary["exposed"] = exp
        fs += fs2
    if p.get("donki"):
        from ..space import donki as dk

        try:
            dp = _confine(p["donki"], JSON_SUFFIXES) if isinstance(p["donki"], str) else asyncio.run(dk.fetch())
            summary["donki"] = dk.crosscheck(summary, json.loads(Path(dp).read_text())["notifications"])
        except Exception as e:  # noqa: BLE001 - the second opinion is optional
            summary["donki"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            job.say(f"DONKI cross-check unavailable: {summary['donki']['error']}")
    job.say(f"scales {summary['scales_now']} advisories {summary['icao_advisory_conditions']}")
    return {"file": str(path), "degraded": err is not None, **_write_report("space_weather", summary, fs, {"product": path, "recording": p.get("recording")}), "scales": summary["scales_now"]}


def launches(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space import launches as ll

    err = None
    if p.get("file"):
        path = _confine(p["file"], JSON_SUFFIXES)
    else:
        path, err = _fetch_or_cached(job, lambda: asyncio.run(ll.fetch(p.get("mode") or "upcoming", int(p.get("limit") or 20))), ll.latest, "launches")
    payload = json.loads(Path(path).read_text())
    out: dict[str, Any] = {"file": str(path), "launches": len(payload.get("launches", [])), "degraded": err is not None}
    if p.get("recording"):
        summary, fs = ll.join_traffic(payload, _recording_path(p["recording"]), float(p.get("hazard_nm") or ll.HAZARD_NM))
        summary["degraded"] = err is not None
        summary["fetch_error"] = err
        out.update(_write_report("launches", summary, fs, {"launches": path, "recording": p.get("recording")}))
    job.say(f"{out['launches']} launches cached")
    return out


def wellclear(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..uas import extract_encounters, summarize_encounters

    rec = _recording_path(p["recording"])
    summary, fs = summarize_encounters(extract_encounters(rec, max_batches=p.get("max_batches")))
    job.say(f"{summary['encounter_pairs']} pairs, {summary['violations']} violations")
    return _write_report(f"wellclear_{rec.stem.split('.')[0]}", summary, fs, {"recording": rec}) | {"violations_per_flight_hour": summary["violations_per_flight_hour"]}


def uas_risk(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..uas import risk

    rec = _recording_path(p["recording"])
    summary, fs = risk.assess(rec, max_batches=p.get("max_batches"))
    job.say(f"risk ratio {summary['risk_ratio']['risk_ratio']}")
    return _write_report(f"uas_risk_{rec.stem.split('.')[0]}", summary, fs, {"recording": rec}) | {"risk_ratio": summary["risk_ratio"]["risk_ratio"]}


def maneuvers(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import maneuvers as mv

    files = [_confine(f, ELEMENT_SUFFIXES) for f in p.get("files") or []] or None
    summary, fs = mv.analyse(files)
    job.say(f"{summary['objects']} objects, {len(summary['changes'])} changes, {len(summary['decaying'])} decaying")
    return _write_report("maneuvers", summary, fs, {f"elements{i}": f for i, f in enumerate(files or [])}) | {"changes": len(summary["changes"]), "decaying": len(summary["decaying"])}


def encounter_model(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..uas import encounter_model as em

    rec = _recording_path(p["recording"])
    res = em.fit_and_simulate(rec, int(p.get("n") or 2000), float(p.get("horizon_s") or em.HORIZON_S), int(p.get("seed") or 0), p.get("max_batches"))
    job.say(f"risk ratio {res['simulation']['risk_ratio']} from {res['simulation']['n']} encounters")
    return _write_report(f"encounter_model_{rec.stem.split('.')[0]}", res, [], {"recording": rec}) | {"risk_ratio": res["simulation"]["risk_ratio"], "p_nmac_unmitigated": res["simulation"]["p_nmac_unmitigated"]}


def satcat(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space import satcat as sc

    path = _confine(p["file"], (".csv",)) if p.get("file") else None
    if path is None:
        cur = sc.latest()
        path = cur if (cur and (time.time() - cur.stat().st_mtime) < sc.MAX_AGE_S and not p.get("refresh")) else None
    if path is None:
        path, _err = _fetch_or_cached(job, lambda: asyncio.run(sc.fetch()), sc.latest, "satcat")
    cat = sc.load(path)
    s = sc.summary(cat)
    rd = sc.recent_decays(float(p.get("decays_days") or 30.0), cat)
    job.say(f"{s['objects']} objects, {len(rd)} decays in {p.get('decays_days') or 30} d")
    return _write_report("satcat", {**s, "recent_decays": rd[:200]}, [], {"satcat": path}) | {"objects": s["objects"], "decays": len(rd)}


def digest(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..governance import digest as dg

    paths = dg.write(float(p.get("days") or 7.0), REPORTS)
    d = json.loads(paths["json"].read_text())["summary"]
    job.say(f"{d['reports']} reports, findings {d['findings_by_severity']}")
    return {"report": str(paths["json"]), "reports": d["reports"], "findings": sum(d["findings_by_severity"].values())}


def catalog_build(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..governance import catalog

    old = catalog.load_catalog() if Path("data/app/catalog.json").is_file() else None
    cat = catalog.build_catalog(".")
    catalog.save_catalog(cat)
    rec = catalog.reconcile(old, cat) if old else None
    job.say(f"{cat['granules_total']} granules")
    return {"granules": cat["granules_total"], "drift": bool(rec and rec.get("drift")), "added": len(rec["added"]) if rec else None, "removed": len(rec["removed"]) if rec else None}


def tfr(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..ingest import tfr as tfr_mod
    from ..space import airspace
    from ..space import launches as ll

    err = None
    if p.get("file"):
        path = _confine(p["file"], JSON_SUFFIXES)
    else:
        path, err = _fetch_or_cached(job, lambda: asyncio.run(tfr_mod.fetch(None if p.get("all_types") else tfr_mod.SPACE_TYPES)), tfr_mod.latest, "tfr")
    payload = tfr_mod.load(path)
    summary: dict[str, Any] = {"product": tfr_mod.summary(path), "degraded": err is not None, "fetch_error": err}
    fs: list[Any] = []
    if p.get("recording"):
        s2, f2 = airspace.join_traffic(payload, _recording_path(p["recording"]))
        summary["traffic"] = s2
        fs += f2
    lp = _confine(p["launches"], JSON_SUFFIXES) if p.get("launches") else ll.latest()
    if lp:
        s3, f3 = airspace.join_launches(payload, json.loads(Path(lp).read_text()))
        summary["launches"] = s3
        fs += f3
    job.say(f"{summary['product']['features']} TFR(s), {summary['product']['with_geometry']} with geometry; findings {len(fs)}")
    return {"file": str(path), "degraded": err is not None, "features": summary["product"]["features"], **_write_report("tfr", summary, fs, {"tfr": path, "recording": p.get("recording"), "launches": lp})}


def reentry(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from datetime import UTC, datetime

    from ..space import reentry as rn

    files = [_confine(f, ELEMENT_SUFFIXES) for f in p.get("files") or []] or None
    rec = _recording_path(p["recording"]) if p.get("recording") else None
    start = datetime.fromisoformat(str(p["start"])).astimezone(UTC) if p.get("start") else None
    summary, fs = rn.analyse(files, rec, start, float(p.get("hours") or rn.HOURS), float(p.get("step_s") or rn.STEP_S), float(p.get("width_nm") or rn.WIDTH_NM))
    job.say(f"{summary['objects']} decaying object(s); {summary['with_airports_under']} with airports under, {summary['with_aircraft_under']} with aircraft under")
    return {"objects": summary["objects"], **_write_report("reentry", summary, fs, {"recording": p.get("recording"), **{f"elements_{i}": f for i, f in enumerate(files or [])}})}


def mission(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import mission as ms

    inputs = ms.load_inputs(_confine(p["file"], JSON_SUFFIXES) if p.get("file") else None, _confine(p["tfr"], JSON_SUFFIXES) if p.get("tfr") else None,
                            _confine(p["scales"], JSON_SUFFIXES) if p.get("scales") else None)
    if not inputs["launches"]:
        raise FileNotFoundError("no launch file given and none cached; run the launches job first")
    if p.get("launch"):
        row = ms.find_launch(inputs["launches"], str(p["launch"]))
    else:
        row = next((r for r in sorted(inputs["launches"].get("launches", []), key=lambda r: r.get("net") or "") if r.get("pad_lat") is not None), None)
    if row is None:
        raise KeyError(f"no launch matches {p.get('launch')!r}")
    rec = _recording_path(p["recording"]) if p.get("recording") else None
    d, fs = ms.dossier(row, rec, inputs["tfr"], inputs["swx"], inputs["satcat"] or None, float(p.get("hazard_nm") or 50.0))
    job.say(f"dossier for {row.get('name')}: {len(d['sections'])} sections, findings {len(fs)}")
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(row.get("id") or row.get("name") or "launch"))[:40]
    return {"launch": row.get("name"), "sections": d["sections"], **_write_report(f"mission_{slug}", d, fs, {k: v for k, v in inputs["files"].items() if v} | {"recording": p.get("recording")})}


def launch_capture(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import capture

    payload = json.loads(Path(_confine(p["file"], JSON_SUFFIXES)).read_text()) if p.get("file") else None
    res = capture.run(launches_payload=payload, lead_s=float(p.get("lead_h") or 2.0) * 3600, tail_s=float(p.get("tail_h") or 1.0) * 3600, radius_nm=float(p.get("radius_nm") or capture.RADIUS_NM),
                      interval_s=float(p.get("interval") or capture.INTERVAL_S), max_duration_s=float(p.get("max_h") or 4.0) * 3600, stop=job.stop, dry_run=bool(p.get("dry_run")),
                      max_batches=int(p["max_batches"]) if p.get("max_batches") else None, say=job.say)
    if not res.get("picked"):
        job.say(f"no launch window due ({res['launches_cached']} launches cached)")
    return res


REGISTRY = {"launch_capture": launch_capture, "tfr": tfr, "reentry": reentry, "mission": mission, "cdm_inbox": cdm_inbox, "spacetrack_pull": spacetrack_pull, "conjunctions": conjunctions, "space_weather": space_weather, "launches": launches,
            "wellclear": wellclear, "uas_risk": uas_risk, "catalog_build": catalog_build, "maneuvers": maneuvers, "encounter_model": encounter_model, "satcat": satcat, "digest": digest}

__all__ = ["REGISTRY", "catalog_build", "cdm_inbox", "conjunctions", "launch_capture", "launches", "mission", "reentry", "space_weather", "spacetrack_pull", "tfr", "uas_risk", "wellclear"]
