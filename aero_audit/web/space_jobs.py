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


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _recording_path(value: Any) -> Path:
    from .app import App

    return App.recording_path(value)


def _write_report(prefix: str, summary: dict[str, Any], findings: list[Any]) -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    p = REPORTS / f"{prefix}_{_stamp()}.json"
    p.write_text(json.dumps({"summary": summary, "findings": [f.model_dump() for f in findings]}, indent=1, default=str))
    for f in findings:
        obs.METRICS.inc("aero_findings_total", rule=f.rule_id, severity=f.severity.value)
    return {"report": str(p), "findings": len(findings), "worst": max((f.severity.value for f in findings), default=None)}


def cdm_inbox(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import cdm_inbox as inbox

    res = inbox.process_inbox(p.get("inbox") or inbox.INBOX, p.get("ledger") or inbox.LEDGER, float(p.get("hbr_m") or 20.0))
    ev = inbox.events(p.get("ledger") or inbox.LEDGER)
    job.say(f"{res.get('processed', 0)} new message(s), {len(ev)} event(s)")
    return {"processed": res.get("processed"), "skipped": res.get("skipped_duplicates"), "events": len(ev), "escalating": sum(1 for e in ev if e.get("trend") == "escalating")}


def spacetrack_pull(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..space import cdm_inbox as inbox
    from ..space.spacetrack import SpaceTrack

    st = SpaceTrack()
    rows = st.cdm_public(int(p.get("days") or 7), float(p.get("min_pc") or 1e-7))
    n = inbox.record_summary(rows, p.get("ledger") or inbox.LEDGER)
    job.say(f"{len(rows)} summaries, {n} new in the ledger")
    return {"summaries": len(rows), "recorded": n}


def conjunctions(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space.orbital import fetch_group, findings, parse_tle, screen

    path = p.get("tle") or asyncio.run(fetch_group(p.get("group") or "stations"))
    sets = parse_tle(Path(path).read_text())
    max_sets = int(p.get("max_sets") or 150)
    res = screen(sets, None, float(p.get("hours") or 24.0), float(p.get("threshold_km") or 10.0), max_sets=max_sets)
    fs = findings(res, sets[:max_sets], stream=Path(path).stem)
    job.say(f"{len(sets)} sets, {len(res['approaches'])} approaches")
    REPORTS.mkdir(parents=True, exist_ok=True)
    rp = REPORTS / f"conjunctions_{Path(path).stem}_{_stamp()}.json"
    rp.write_text(json.dumps({"screen": res, "findings": [f.model_dump() for f in fs]}, indent=1, default=str))
    for f in fs:
        obs.METRICS.inc("aero_findings_total", rule=f.rule_id, severity=f.severity.value)
    return {"report": str(rp), "sets": len(sets), "approaches": len(res["approaches"]), "findings": len(fs)}


def space_weather(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space import spaceweather

    path = Path(p["file"]) if p.get("file") else asyncio.run(spaceweather.fetch())
    payload = json.loads(Path(path).read_text())
    summary, fs = spaceweather.assess(payload)
    if p.get("recording"):
        exp, fs2 = spaceweather.exposed_flights(_recording_path(p["recording"]), summary["icao_advisory_conditions"], float(p.get("lat_min") or spaceweather.HIGH_LAT_DEG))
        summary["exposed"] = exp
        fs += fs2
    job.say(f"scales {summary['scales_now']} advisories {summary['icao_advisory_conditions']}")
    return {"file": str(path), **_write_report("space_weather", summary, fs), "scales": summary["scales_now"]}


def launches(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from ..space import launches as ll

    path = Path(p["file"]) if p.get("file") else asyncio.run(ll.fetch(p.get("mode") or "upcoming", int(p.get("limit") or 20)))
    payload = json.loads(Path(path).read_text())
    out: dict[str, Any] = {"file": str(path), "launches": len(payload.get("launches", []))}
    if p.get("recording"):
        summary, fs = ll.join_traffic(payload, _recording_path(p["recording"]), float(p.get("hazard_nm") or ll.HAZARD_NM))
        out.update(_write_report("launches", summary, fs))
    job.say(f"{out['launches']} launches cached")
    return out


def wellclear(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..uas import extract_encounters, summarize_encounters

    rec = _recording_path(p["recording"])
    summary, fs = summarize_encounters(extract_encounters(rec, max_batches=p.get("max_batches")))
    job.say(f"{summary['encounter_pairs']} pairs, {summary['violations']} violations")
    return _write_report(f"wellclear_{rec.stem.split('.')[0]}", summary, fs) | {"violations_per_flight_hour": summary["violations_per_flight_hour"]}


def uas_risk(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..uas import risk

    rec = _recording_path(p["recording"])
    summary, fs = risk.assess(rec, max_batches=p.get("max_batches"))
    job.say(f"risk ratio {summary['risk_ratio']['risk_ratio']}")
    return _write_report(f"uas_risk_{rec.stem.split('.')[0]}", summary, fs) | {"risk_ratio": summary["risk_ratio"]["risk_ratio"]}


def catalog_build(job: Job, p: dict[str, Any]) -> dict[str, Any]:
    from ..governance import catalog

    old = catalog.load_catalog() if Path("data/app/catalog.json").is_file() else None
    cat = catalog.build_catalog(".")
    catalog.save_catalog(cat)
    rec = catalog.reconcile(old, cat) if old else None
    job.say(f"{cat['granules_total']} granules")
    return {"granules": cat["granules_total"], "drift": bool(rec and rec.get("drift")), "added": len(rec["added"]) if rec else None, "removed": len(rec["removed"]) if rec else None}


REGISTRY = {"cdm_inbox": cdm_inbox, "spacetrack_pull": spacetrack_pull, "conjunctions": conjunctions, "space_weather": space_weather, "launches": launches,
            "wellclear": wellclear, "uas_risk": uas_risk, "catalog_build": catalog_build}

__all__ = ["REGISTRY", "catalog_build", "cdm_inbox", "conjunctions", "launches", "space_weather", "spacetrack_pull", "uas_risk", "wellclear"]
