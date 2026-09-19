"""Study registry: questions the programme answers reproducibly, with inputs, method, metrics,
and hashed outputs. Runnable studies execute on supplied files; planned ones name what they need.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import provenance

STUDIES_DIR = Path("reports/studies")


@dataclass(frozen=True)
class Study:
    id: str
    title: str
    question: str
    domain: str
    method: str
    inputs: tuple[str, ...]
    metrics: tuple[str, ...]
    status: str  # runnable | needs-network | planned
    runner: str | None = None
    upstream: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "question": self.question, "domain": self.domain, "method": self.method,
                "inputs": list(self.inputs), "metrics": list(self.metrics), "status": self.status, "runner": self.runner,
                "upstream": list(self.upstream)}


# ---- runners ---------------------------------------------------------------------------------
def _integrity_by_operator(recording: str | Path, **_: Any) -> dict[str, Any]:
    from ..ecosystem import enrich
    from ..ingest.replay import iter_recording

    ok: dict[str, int] = defaultdict(int)
    n: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    aircraft: dict[str, set[str]] = defaultdict(set)
    for b in iter_recording(recording):
        for sv in b.states:
            if not sv.has_position or sv.on_ground or (sv.position_source or "adsb") != "adsb" or sv.nic is None or sv.nac_p is None or sv.sil is None:
                continue
            e = enrich(sv)
            code = e.operator_code or "unknown"
            names[code] = e.operator or code
            n[code] += 1
            aircraft[code].add(sv.icao24)
            if sv.nic >= 7 and sv.nac_p >= 8 and sv.sil == 3:
                ok[code] += 1
    rows = [{"operator_code": c, "operator": names[c], "fixes": n[c], "aircraft": len(aircraft[c]), "compliance": round(ok[c] / n[c], 4)}
            for c in n if n[c] >= 20]
    rows.sort(key=lambda r: (r["compliance"], -r["fixes"]))
    total = sum(n.values())
    return {"recording": str(recording), "airborne_adsb_fixes": total, "overall_compliance": round(sum(ok.values()) / total, 4) if total else None,
            "operators": rows, "lowest": rows[:10], "highest": rows[-10:][::-1]}


def _recall_vs_revisit(**_: Any) -> dict[str, Any]:
    p = Path("models/evaluation.json")
    if not p.is_file():
        raise FileNotFoundError("models/evaluation.json not found; run `aero evaluate` first")
    ev = json.loads(p.read_text())
    scen = ev.get("scenarios", [])
    return {"recording": ev.get("recording"), "median_revisit_s": ev.get("median_revisit_s"),
            "scenarios": [{"name": s.get("name"), "recall": s.get("recall"), "median_ttd_s": s.get("median_ttd_s"), "known_gap": s.get("known_gap")} for s in scen],
            "rule_precision": ev.get("rule_precision", {}),
            "reading": "one-off manipulations are bounded by the revisit interval; replay, hijack and integrity are not"}


def _telemetry_plausibility(csv: str | Path, **_: Any) -> dict[str, Any]:
    from ..space.telemetry import audit_telemetry, load_csv, summarize

    pts = load_csv(csv)
    findings = audit_telemetry(pts, stream=Path(csv).stem)
    s = summarize(pts, findings)
    return {**s, "csv": str(csv), "findings_detail": [{"rule": f.rule_id, "t_s": f.ts, "severity": f.severity.value, "title": f.title} for f in findings]}


def _asset_coverage(catalog: str | Path = "data/space/nasa3d_catalog.json", **_: Any) -> dict[str, Any]:
    from ..space.nasa3d import load_catalog

    cat = load_catalog(catalog)
    subj: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in cat.assets:
        subj[a.subject][a.kind] += 1
    ranked = sorted(subj.items(), key=lambda kv: -sum(kv[1].values()))
    return {**cat.summary(), "catalog": str(catalog), "top_subjects": [{"subject": s, **dict(k)} for s, k in ranked[:25]],
            "models_with_preview": sum(1 for s, k in subj.items() if k.get("model") and k.get("image"))}


def _holding_by_airport(recording: str | Path, **_: Any) -> dict[str, Any]:
    from ..audit.engine import AuditEngine
    from ..ecosystem import enrich
    from ..impact import estimate_holding_impact
    from ..ingest.replay import iter_recording

    eng = AuditEngine()
    last_seen: dict[str, Any] = {}
    for b in iter_recording(recording):
        eng.process_batch(b)
        for sv in b.states:
            if sv.has_position:
                last_seen[sv.icao24] = sv
    holds = [f for f in eng.findings if f.rule_id == "OPS-002"]
    by_apt: dict[str, list[Any]] = defaultdict(list)
    for f in holds:
        sv = last_seen.get(f.icao24 or "")
        apt = enrich(sv).airport if sv else None
        by_apt[apt or "none within 40 nm"].append(f)
    rows = []
    for apt, fs in sorted(by_apt.items(), key=lambda kv: -len(kv[1])):
        est = estimate_holding_impact(fs).as_dict()
        rows.append({"airport": apt, "holds": len(fs), **{k: est[k] for k in ("observed_minutes", "fuel_kg", "co2_kg", "delay_cost")}})
    return {"recording": str(recording), "holds": len(holds), "by_airport": rows}


def _airports_in_extent(geojson: str | Path, buffer_nm: float = 10.0, **_: Any) -> dict[str, Any]:
    """Airports inside (or within buffer_nm of) polygons of a GeoJSON crisis extent (e.g. a CMT flood map export)."""
    from ..features.tracks import haversine_nm
    from ..knowledge import AIRPORTS
    from ..vision.apron import point_in_polygon

    gj = json.loads(Path(geojson).read_text())
    feats = gj.get("features", [gj]) if gj.get("type") != "Feature" else [gj]
    polys: list[tuple[str, list[tuple[float, float]]]] = []
    for f in feats:
        geom = f.get("geometry", f)
        name = str((f.get("properties") or {}).get("name") or f"feature{len(polys) + 1}")
        if geom.get("type") == "Polygon":
            polys.append((name, [(float(x), float(y)) for x, y in geom["coordinates"][0]]))
        elif geom.get("type") == "MultiPolygon":
            for k, part in enumerate(geom["coordinates"]):
                polys.append((f"{name}#{k + 1}", [(float(x), float(y)) for x, y in part[0]]))
    inside, near = [], []
    for a in AIRPORTS.values():
        for name, ring in polys:
            if point_in_polygon(a.lon, a.lat, ring):
                inside.append({"icao": a.icao, "iata": a.iata, "name": a.name, "extent": name, "major": a.major})
                break
            d = min(haversine_nm(a.lat, a.lon, y, x) for x, y in ring)
            if d <= buffer_nm:
                near.append({"icao": a.icao, "iata": a.iata, "name": a.name, "extent": name, "distance_nm": round(d, 1), "major": a.major})
                break
    return {"geojson": str(geojson), "extents": [n for n, _ in polys], "buffer_nm": buffer_nm, "airports_inside": inside,
            "airports_near": sorted(near, key=lambda r: r["distance_nm"]), "major_affected": [r["iata"] for r in inside + near if r["major"]]}


def _conjunction_screen(tle: str | Path, hours: float = 24.0, threshold_km: float = 10.0, **_: Any) -> dict[str, Any]:
    from ..space.orbital import findings, parse_tle, screen

    sets = parse_tle(Path(tle).read_text())
    res = screen(sets, None, float(hours), float(threshold_km))
    fs = findings(res, sets[:200], stream=Path(tle).stem)
    ages = list(res["element_age_days"].values())
    return {"tle": str(tle), "sets": res["sets"], "pairs": res["pairs"], "hours": hours, "threshold_km": threshold_km,
            "approaches": res["approaches"][:50], "approach_count": len(res["approaches"]), "co_moving_pairs": len(res["co_moving"]), "stale_sets": sum(1 for f in fs if f.rule_id == "ORB-001"),
            "propagation_errors": len(res["propagation_errors"]), "median_element_age_days": round(sorted(ages)[len(ages) // 2], 2) if ages else None,
            "covariance": res["covariance"]}


def _cdm_assessment(cdm: str | Path, hbr_m: float = 20.0, **_: Any) -> dict[str, Any]:
    from ..space.cdm import assess, parse_cdm

    c = parse_cdm(Path(cdm).read_text())
    res, fs = assess(c, float(hbr_m))
    return {"cdm": str(cdm), "message_id": c.message_id, "tca": c.tca, "pc": (res.get("pc") or {}).get("pc"), "miss_m": (res.get("pc") or {}).get("miss_m"),
            "error": res.get("error"), "findings": [{"rule": f.rule_id, "severity": f.severity.value, "title": f.title} for f in fs]}


def _wellclear(recording: str | Path, max_batches: int | None = None, **_: Any) -> dict[str, Any]:
    from ..uas import extract_encounters, summarize_encounters

    summary, fs = summarize_encounters(extract_encounters(recording, max_batches=int(max_batches) if max_batches else None))
    return {**{k: v for k, v in summary.items() if k != "pairs"}, "top_pairs": summary["pairs"][:20], "findings": len(fs)}


def _encounter_rates(recording: str | Path, **kw: Any) -> dict[str, Any]:
    r = _wellclear(recording, **kw)
    return {k: r[k] for k in ("recording", "flight_hours", "aircraft_airborne", "encounter_pairs", "nmac_proximate", "nmac_per_flight_hour", "violations_per_flight_hour")}


def _utm_conformance(spec: str | Path, sample: str | Path, schema: str | None = None, path: str | None = None, **_: Any) -> dict[str, Any]:
    from ..uas.utm import check_samples, load_document

    doc = load_document(spec)
    inst = json.loads(Path(sample).read_text())
    return check_samples(doc, [(Path(sample).name, inst)], schema, path)


def _debris(mission: str | Path, **_: Any) -> dict[str, Any]:
    from ..space.debris import Mission, checklist

    summary, fs = checklist(Mission.from_json(mission))
    return {**summary, "findings": [{"rule": f.rule_id, "severity": f.severity.value, "title": f.title} for f in fs]}


def _classifier_eval(manifest: str | Path = "data/space/dataset/manifest.json", holdout: str | Path | None = None, **_: Any) -> dict[str, Any]:
    """Train on the manifest's split and report validation accuracy; with a hold-out manifest (other queries, de-duplicated
    against training), report the second-source accuracy too, which is the number that matters."""
    from ..space.classifier import evaluate, load, train

    out_path = Path("models") / "scene_classifier_study.joblib"
    stats = train(manifest, out_path)
    res = {k: stats[k] for k in ("manifest", "classes", "counts", "n_train", "n_val", "accuracy", "per_class", "sha256")}
    hp = Path(holdout) if holdout else Path("data/space/dataset_holdout/manifest.json")
    if hp.is_file():
        ev = evaluate(hp, load(out_path, allow_unverified=True), split=None)
        res["holdout"] = {"manifest": str(hp), "n": ev["n"], "accuracy": ev["accuracy"], "per_class": ev["per_class"], "confusion": ev["confusion"]}
    return res


def _risk_classes(recording: str | Path, max_batches: int | None = None, **_: Any) -> dict[str, Any]:
    from ..uas import risk

    summary, fs = risk.assess(recording, max_batches=max_batches)
    return {"risk_ratio": summary["risk_ratio"], "bands": summary["density"]["bands"], "flight_hours": summary["flight_hours"], "findings": [f.rule_id for f in fs]}


def _space_weather(scales: str | Path = "data/samples/swpc_scales_sample.json", recording: str | Path | None = None, lat_min: float = 60.0, **_: Any) -> dict[str, Any]:
    import json as _json

    from ..space import spaceweather

    payload = _json.loads(Path(scales).read_text())
    summary, fs = spaceweather.assess(payload)
    out = {k: summary[k] for k in ("product_time", "scales_now", "scales_24h", "kp", "icao_advisory_conditions", "age_s")}
    if recording:
        exp, fs2 = spaceweather.exposed_flights(recording, summary["icao_advisory_conditions"], lat_min)
        out["exposed_aircraft"] = exp["aircraft"]
        fs += fs2
    out["findings"] = [f.rule_id for f in fs]
    return out


def _launch_join(recording: str | Path, launches: str | Path = "data/samples/ll2_launches_sample.json", hazard_nm: float = 50.0, **_: Any) -> dict[str, Any]:
    import json as _json

    from ..space import launches as ll

    summary, fs = ll.join_traffic(_json.loads(Path(launches).read_text()), recording, hazard_nm)
    return {"launches": summary["launches"], "overlapping": summary["overlapping"], "rows": summary["rows"], "findings": [f.rule_id for f in fs]}


def _encounter_model(recording: str | Path, n: int = 2000, horizon_s: float = 25.0, seed: int = 0, max_batches: int | None = None, **_: Any) -> dict[str, Any]:
    from ..uas import encounter_model as em

    return em.fit_and_simulate(recording, int(n), float(horizon_s), int(seed), max_batches)


def _element_history(files: list[str | Path] | None = None, tle: str | Path | None = None, **_: Any) -> dict[str, Any]:
    from ..space import maneuvers

    fl = [Path(f) for f in (files or [])] or ([Path(tle)] if tle else None)
    summary, fs = maneuvers.analyse(fl)
    return {"objects": summary["objects"], "with_history": summary["with_history"], "changes": len(summary["changes"]), "decaying": len(summary["decaying"]),
            "changes_detail": summary["changes"][:50], "decaying_detail": summary["decaying"][:50], "findings": [f.rule_id for f in fs]}


def _wellclear_trend(recordings_dir: str | Path = "data/recordings", pattern: str = "*", files: list[str | Path] | None = None, max_batches: int | None = None, **_: Any) -> dict[str, Any]:
    from ..uas import trend as tr

    recs = [Path(f) for f in files] if files else tr.find_recordings(recordings_dir, pattern)
    if not recs:
        raise RuntimeError(f"no recordings under {recordings_dir}")
    summary, fs = tr.trend(recs, max_batches)
    return {k: v for k, v in summary.items() if k != "rows"} | {"rows": [{k: v for k, v in r.items() if k != "regions"} for r in summary["rows"]], "findings": [f.rule_id for f in fs]}


def _catalog_reconcile(**_: Any) -> dict[str, Any]:
    from .catalog import build_catalog, load_catalog, reconcile, save_catalog

    old = load_catalog()
    new = build_catalog(".")
    r = reconcile(old, new)
    save_catalog(new)
    return {**r, "granules": new["granules_total"], "bytes": new["bytes_total"], "collections": {k: v["count"] for k, v in new["collections"].items()}}


def _first_fix(recording: str | Path) -> datetime | None:
    from ..ingest.replay import iter_recording

    for b in iter_recording(recording):
        ts = [sv.ts for sv in b.states if sv.ts]
        if ts:
            return datetime.fromtimestamp(min(ts), UTC)
    return None


def _tfr_join(recording: str | Path | None = None, tfr: str | Path = "data/samples/tfr_sample.json", launches: str | Path = "data/samples/ll2_launches_sample.json", **_: Any) -> dict[str, Any]:
    import json as _json

    from ..ingest import tfr as tfr_mod
    from ..space import airspace

    payload = tfr_mod.load(tfr)
    out: dict[str, Any] = {"product": tfr_mod.summary(tfr), "findings": []}
    if recording:
        s, fs = airspace.join_traffic(payload, recording)
        out["traffic"] = s["rows"]
        out["findings"] += [f.rule_id for f in fs]
    s2, fs2 = airspace.join_launches(payload, _json.loads(Path(launches).read_text()))
    out["launch_coverage"] = {"launches": s2["launches"], "covered": s2["covered"], "us_uncovered_soon": s2["us_uncovered_soon"], "rows": s2["rows"]}
    out["findings"] += [f.rule_id for f in fs2]
    return out


def _reentry_exposure(tle: str | Path = "data/samples/decaying_sample.tle", recording: str | Path | None = None, hours: float = 6.0, width_nm: float = 50.0, files: list[str | Path] | None = None, **_: Any) -> dict[str, Any]:
    from ..space import reentry

    start = _first_fix(recording) if recording else None
    summary, fs = reentry.analyse(files or [tle], recording, start, float(hours), 30.0 if not recording else 10.0, float(width_nm))
    rows = [{k: v for k, v in r.items() if k != "track"} for r in summary["rows"]]
    return {"objects": summary["objects"], "from": summary.get("from"), "hours": hours, "width_nm": width_nm, "rows": rows, "findings": [f.rule_id for f in fs]}


def _tfr_displacement(products: list[str | Path] | None = None, recordings: list[str | Path] | None = None, recording: str | Path | None = None, tfr: str | Path | None = None, **_: Any) -> dict[str, Any]:
    from ..space import airspace

    prods = [Path(x) for x in products] if products else ([Path(tfr)] if tfr else sorted(p for p in Path("data/airspace").glob("tfr_*.json") if not p.name.endswith(".provenance.json")))
    recs = [Path(x) for x in recordings] if recordings else ([Path(recording)] if recording else sorted(Path("data/recordings").glob("*.jsonl*")))
    if not prods:
        prods = [Path("data/samples/tfr_sample.json")]
    if not recs:
        recs = sorted(Path("data/samples").glob("*.jsonl.gz"))
    return airspace.displacement(prods, recs)


def _mission_dossier(launch: str = "wallops", launches: str | Path = "data/samples/ll2_launches_sample.json", tfr: str | Path = "data/samples/tfr_sample.json",
                     scales: str | Path = "data/samples/swpc_scales_sample.json", recording: str | Path | None = None, hazard_nm: float = 50.0, **_: Any) -> dict[str, Any]:
    import json as _json

    from ..space import mission, satcat

    ll = _json.loads(Path(launches).read_text())
    row = mission.find_launch(ll, launch)
    if row is None:
        raise KeyError(f"no launch matches {launch!r} in {launches}")
    d, fs = mission.dossier(row, recording, _json.loads(Path(tfr).read_text()), _json.loads(Path(scales).read_text()), satcat.load() or None, float(hazard_nm))
    return {**d, "findings_detail": [f.rule_id for f in fs]}


RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "wellclear": _wellclear, "encounter_rates": _encounter_rates, "utm_conformance": _utm_conformance, "debris": _debris,
    "classifier_eval": _classifier_eval, "catalog_reconcile": _catalog_reconcile,
    "cdm_assessment": _cdm_assessment, "risk_classes": _risk_classes, "space_weather": _space_weather, "launch_join": _launch_join,
    "tfr_join": _tfr_join, "reentry_exposure": _reentry_exposure, "mission_dossier": _mission_dossier, "tfr_displacement": _tfr_displacement,
    "encounter_model": _encounter_model, "element_history": _element_history, "wellclear_trend": _wellclear_trend,
    "conjunction_screen": _conjunction_screen,
    "airports_in_extent": _airports_in_extent,
    "integrity_by_operator": _integrity_by_operator, "recall_vs_revisit": _recall_vs_revisit,
    "telemetry_plausibility": _telemetry_plausibility, "asset_coverage": _asset_coverage, "holding_by_airport": _holding_by_airport,
}


STUDIES: dict[str, Study] = {s.id: s for s in (
    Study("ST-01", "ADS-B integrity compliance by operator", "Which operators fly below the 14 CFR 91.227 integrity minimums, and how often?",
          "air-surveillance", "Airborne ADS-B fixes grouped by operator designator; share meeting NIC>=7 / NACp>=8 / SIL=3; operators with >= 20 fixes.",
          ("recording (.jsonl / .jsonl.gz)",), ("compliance per operator", "fixes", "aircraft"), "runnable", "integrity_by_operator"),
    Study("ST-02", "Detection recall versus revisit interval", "How much of the detection clock is the feed's revisit interval rather than the rule?",
          "air-surveillance", "Read the latest injected-scenario evaluation; relate recall and time-to-detect to the median revisit.",
          ("models/evaluation.json",), ("recall per scenario", "median TTD", "median revisit"), "runnable", "recall_vs_revisit"),
    Study("ST-03", "Launch telemetry plausibility", "Does a telemetry stream obey vehicle physics and stream continuity?",
          "space-launch", "SPC-001..005 over a t/speed/altitude stream.", ("telemetry CSV",), ("findings by rule", "max speed", "max altitude"), "runnable", "telemetry_plausibility"),
    Study("ST-04", "NASA-3D asset coverage", "Which subjects have both a model and a preview image, and how large are they?",
          "space-assets", "Catalogue summary by kind and subject.", ("data/space/nasa3d_catalog.json",), ("assets by kind", "subjects", "models with preview"), "runnable", "asset_coverage"),
    Study("ST-05", "Holding cost by airport", "Where is holding time, fuel and delay cost concentrated?",
          "air-operations", "OPS-002 findings attributed to the nearest airport of the aircraft's last position; impact model per airport.",
          ("recording",), ("holds", "minutes", "fuel", "CO2", "cost"), "runnable", "holding_by_airport"),
    Study("ST-06", "Conjunction screening trend", "How many close approaches under a distance threshold per window, and how old were the elements?",
          "space-orbital", "SGP4 propagation of a catalogue subset (CelesTrak group or file); pairwise minimum separation; stale-element count. Pc awaits CDMs with covariance.",
          ("TLE file (aero space conjunctions --group ...)",), ("approaches under threshold", "median element age", "propagation errors"), "runnable", "conjunction_screen",
          ("brandon-rhodes/python-sgp4", "skyfielders/python-skyfield", "open-space-collective/ccsds-data-messages")),
    Study("ST-07", "Well-clear violation rates", "How often do observed encounters violate well-clear, and with what alert lead time?",
          "uas-utm", "Pairwise encounters from surveillance tracks scored with the DO-365 / DAIDALUS well-clear definitions and alert levels.",
          ("recording",), ("violations per flight hour", "NMAC-proximate pairs", "median alert lead time"), "runnable", "wellclear", ("nasa/daidalus", "nasa/WellClear")),
    Study("ST-08", "Encounter and NMAC-proximate rates", "How many encounters, and how many within NMAC distances, per flight hour?",
          "uas-utm", "Encounter extraction on recorded tracks; NMAC-proximate = 500 ft / 100 ft (risk classes and the risk ratio: ST-16).",
          ("recording",), ("encounters per flight hour", "NMAC-proximate per flight hour"), "runnable", "encounter_rates", ("mit-ll/air-risk-class", "mit-ll/em-core")),
    Study("ST-09", "UTM API conformance", "Do exchanges match the NASA UTM OpenAPI contracts?",
          "uas-utm", "Schema validation of captured exchanges against an OpenAPI document (nasa/utm-apis, or this app's own).", ("OpenAPI document", "captured exchange"),
          ("conformance failures",), "runnable", "utm_conformance", ("nasa/utm-apis",)),
    Study("ST-13", "Debris-mitigation checklist", "Does a mission description meet the disposal, passivation, collision-avoidance, casualty and trackability rules?",
          "space-orbital", "DEB-001..008 with a decay-model lifetime estimate.", ("mission JSON",), ("checks passed / failed", "estimated lifetime"), "runnable", "debris",
          ("nasa/GMAT",)),
    Study("ST-14", "Scene classifier evaluation", "How well does the scene classifier separate launch, orbit, station and surface imagery on held-out data?",
          "space-assets", "Train on the manifest's train split, evaluate on the validation split; per-class precision and recall.", ("dataset manifest",),
          ("accuracy", "per-class precision/recall"), "runnable", "classifier_eval"),
    Study("ST-16", "Airspace density classes and DAA risk ratio", "How dense is the low-altitude airspace, and what bound does observation put on the DAA risk ratio?",
          "uas-utm", "Aircraft-hours per 0.2° cell and altitude band normalised to area and time (density classes, MIT-LL air-risk-class lineage); risk ratio bounded by "
          "NMAC-proximate encounters whose alert lead was below the warning time (ASTM F3442 lineage). Programme thresholds, stated in the report.",
          ("recording",), ("cells per class per band", "observed risk ratio"), "runnable", "risk_classes", ("mit-ll/air-risk-class", "ASTM F3442")),
    Study("ST-17", "Space weather exposure of observed traffic", "Which ICAO advisory conditions hold, and which observed flights are exposed?",
          "space-environment", "NOAA scales and Kp mapped to ICAO moderate / severe conditions per effect; aircraft poleward of 60° during G/S conditions listed.",
          ("SWPC product (sample bundled)", "recording (optional)"), ("conditions per effect", "exposed aircraft"), "runnable", "space_weather", ("NOAA SWPC",)),
    Study("ST-18", "Traffic near launch pads during windows", "Did aircraft stay out of the hazard radius during each launch window that overlaps the recording?",
          "space-launch", "Launch windows and pad coordinates joined to recorded positions; aircraft inside the radius during the window versus outside it.",
          ("launch file (sample bundled)", "recording"), ("aircraft inside during window", "baseline outside window"), "runnable", "launch_join", ("TheSpaceDevs/Launch Library 2",)),
    Study("ST-19", "Encounter model Monte Carlo", "From the encounters a recording shows, what NMAC probability follows with nobody manoeuvring, and with an alerting horizon?",
          "uas-utm", "Empirical initial conditions resampled into straight-line encounters, propagated through the well-clear definitions; NMAC counted with and without a horizon (em-core lineage, small scale).",
          ("recording",), ("P(NMAC) unmitigated / mitigated", "model risk ratio", "NMAC per flight hour"), "runnable", "encounter_model", ("mit-ll/em-core", "ASTM F3442")),
    Study("ST-20", "Element history: manoeuvres and decay", "Which catalogued objects changed orbit between snapshots, and which are about to re-enter?",
          "space-orbital", "Mean elements per object across cached snapshots; semi-major-axis and inclination steps beyond drag, perigee and mean-motion decay rate.",
          ("two or more element files",), ("manoeuvre-scale changes", "objects decaying within 30 days"), "runnable", "element_history", ("CelesTrak", "CCSDS 502.0-B")),
    Study("ST-21", "Well-clear rate trend across recordings", "Is the well-clear violation rate per flight hour rising, falling or flat across the recordings on disk?",
          "uas-utm", "Encounter summary and low-altitude density per recording, ordered by first timestamp; least-squares slope of the violation rate; DAA-005 when rising.",
          ("recordings directory",), ("violations per flight hour per recording", "slope per day", "dense low-altitude cells"), "runnable", "wellclear_trend", ("nasa/daidalus", "mit-ll/air-risk-class")),
    Study("ST-22", "Launch airspace compliance", "Did traffic stay out of the published space-operations restrictions, and does every imminent US launch window have one?",
          "space-launch", "FAA TFR product (keyless; geometry, effective time, vertical limits) joined to a recording (aircraft inside while in effect, baseline outside) and to launch windows (coverage of the pad in the window).",
          ("TFR product", "recording", "launch file"), ("aircraft inside per restriction", "restrictions overlapping the recording", "US windows without a TFR within 72 h"), "runnable", "tfr_join", ("nasa/utm-apis",)),
    Study("ST-23", "Reentry corridor exposure", "Which airports and flights sit under the ground track of an object the element history says is decaying?",
          "space-orbital", "Decaying objects from the element history propagated with SGP4, TEME to geodetic by the GMST rotation, corridor of +-width around the track; airports and recorded traffic within it at the time of the pass.",
          ("element file(s)", "recording"), ("objects flagged", "airports under the corridor", "aircraft under the track", "element age"), "runnable", "reentry_exposure", ("nasa/GMAT", "Bill-Gray/find_orb")),
    Study("ST-24", "Mission dossier", "For one launch, what did every domain see: airspace, traffic, space weather, catalogued objects and their decay?",
          "space-launch", "Join of the launch record with the spaceport table, the TFR product, the recording, the newest space-weather product and the SATCAT by launch date and site code; one report, one manifest.",
          ("launch file", "TFR product", "SWPC product", "recording"), ("TFRs covering the window", "aircraft inside the hazard radius and inside the TFR", "advisory conditions", "objects catalogued and decayed"), "runnable", "mission_dossier", ("nasa/openmct",)),
    Study("ST-25", "Traffic displacement by launch airspace", "How much traffic did each space-operations restriction actually displace, across every cached product and recording?",
          "space-launch", "Newest geometry per NOTAM id across the cached TFR products; per recording, distinct aircraft inside the volume per minute while in effect against the same volume outside its effective time; ratio per pair, median over history.",
          ("TFR products", "recordings"), ("restrictions", "pairs with both windows", "displacement ratio per pair", "median ratio"), "runnable", "tfr_displacement", ()),
    Study("ST-15", "Data catalogue reconciliation", "What changed on disk since the last catalogue build?",
          "air-surveillance", "Rebuild the CMR-style catalogue and diff it against the saved one.", (), ("added", "removed", "changed"), "runnable", "catalog_reconcile",
          ("nasa/Common-Metadata-Repository", "nasa/cumulus")),
    Study("ST-11", "Airports inside a crisis extent", "Which airports and hubs sit inside or near a flood, fire or disaster extent?",
          "earth-crisis", "Point-in-polygon of the airport table against GeoJSON extents (Crisis Mapping Toolkit exports), plus a distance buffer.",
          ("GeoJSON extent",), ("airports inside", "airports near", "major hubs affected"), "runnable", "airports_in_extent", ("nasa/CrisisMappingToolkit",)),
    Study("ST-12", "Conjunction data message assessment", "Given a CDM with states and covariances, what is the probability of collision and is the message self-consistent?",
          "space-orbital", "Parse CCSDS 508.0-B KVN; rotate RTN covariances to inertial; 2D short-encounter Pc by numerical integration; miss-distance consistency check.",
          ("CDM file (KVN)",), ("Pc", "miss distance", "consistency"), "runnable", "cdm_assessment", ("open-space-collective/ccsds-data-messages", "nasa/GMAT")),
    Study("ST-10", "Cross-feed corroboration baseline", "How far apart do two independent feeds place the same aircraft, and how often do they disagree?",
          "air-surveillance", "Dead-reckoned comparison of adsb.lol and OpenSky over the same region.", ("two live feeds",), ("median separation", "p95", "disagreements"), "needs-network", None),
)}


def run_study(study_id: str, out_dir: str | Path = STUDIES_DIR, **params: Any) -> dict[str, Any]:
    st = STUDIES.get(study_id)
    if st is None:
        raise KeyError(f"unknown study {study_id}; known: {', '.join(STUDIES)}")
    if st.status != "runnable" or not st.runner:
        raise RuntimeError(f"{study_id} is {st.status}: {', '.join(st.inputs)} needed")
    t0 = time.time()
    result = RUNNERS[st.runner](**params)
    inputs = {k: {"value": str(v), "sha256": provenance.sha256_file(v) if isinstance(v, (str, Path)) and Path(str(v)).is_file() else None}
              for k, v in params.items()}
    record = {"study": st.to_dict(), "params": inputs, "result": result, "duration_s": round(time.time() - t0, 2),
              "provenance": {"tool": "aero-audit", "version": provenance.__version__, "git": provenance.git_commit(),
                             "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jp = out / f"{study_id}_{stamp}.json"
    jp.write_text(json.dumps(record, indent=2, default=str))
    md = [f"# {st.id} {st.title}", "", f"**Question.** {st.question}", "", f"**Method.** {st.method}", "",
          "**Inputs.** " + (", ".join(f"{k}={v['value']}" + (f" (sha256 {v['sha256'][:12]})" if v["sha256"] else "") for k, v in inputs.items()) or "none"), "",
          "## Result", "", "```json", json.dumps({k: v for k, v in result.items() if k not in ("operators", "findings_detail")}, indent=1, default=str)[:6000], "```", ""]
    (out / f"{study_id}_{stamp}.md").write_text("\n".join(md))
    record["files"] = {"json": str(jp), "md": str(out / f"{study_id}_{stamp}.md")}
    return record


def latest_results(out_dir: str | Path = STUDIES_DIR) -> dict[str, dict[str, Any]]:
    """Most recent result file per study id."""
    out: dict[str, dict[str, Any]] = {}
    d = Path(out_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("ST-*.json")):
        sid = p.name.split("_")[0]
        out[sid] = {"file": str(p), "mtime": p.stat().st_mtime}
    return out


def render_markdown() -> str:
    lines = ["# Study registry (generated)", "", "| Id | Study | Domain | Status | Inputs | Metrics | Adopts |", "|---|---|---|---|---|---|---|"]
    for s in STUDIES.values():
        lines.append(f"| {s.id} | {s.title} | {s.domain} | {s.status} | {', '.join(s.inputs)} | {', '.join(s.metrics)} | {', '.join(s.upstream) or '-'} |")
    lines += ["", "Run one: `aero gov run-study ST-01 --recording data/samples/<file>.jsonl.gz`; results land in `reports/studies/` with provenance.", ""]
    return "\n".join(lines)


__all__ = ["RUNNERS", "STUDIES", "STUDIES_DIR", "Study", "latest_results", "render_markdown", "run_study"]
