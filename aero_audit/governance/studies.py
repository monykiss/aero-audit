"""Study registry: questions the programme answers reproducibly, with inputs, method, metrics,
and hashed outputs. Runnable studies execute on supplied files; planned ones name what they need.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
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


def _classifier_eval(manifest: str | Path = "data/space/dataset/manifest.json", **_: Any) -> dict[str, Any]:
    from ..space.classifier import train

    stats = train(manifest, Path("models") / "scene_classifier_study.joblib")
    return {k: stats[k] for k in ("manifest", "classes", "counts", "n_train", "n_val", "accuracy", "per_class", "sha256")}


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


def _catalog_reconcile(**_: Any) -> dict[str, Any]:
    from .catalog import build_catalog, load_catalog, reconcile, save_catalog

    old = load_catalog()
    new = build_catalog(".")
    r = reconcile(old, new)
    save_catalog(new)
    return {**r, "granules": new["granules_total"], "bytes": new["bytes_total"], "collections": {k: v["count"] for k, v in new["collections"].items()}}


RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "wellclear": _wellclear, "encounter_rates": _encounter_rates, "utm_conformance": _utm_conformance, "debris": _debris,
    "classifier_eval": _classifier_eval, "catalog_reconcile": _catalog_reconcile,
    "cdm_assessment": _cdm_assessment, "risk_classes": _risk_classes, "space_weather": _space_weather, "launch_join": _launch_join,
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
