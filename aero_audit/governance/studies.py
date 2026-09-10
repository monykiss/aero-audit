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


RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
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
          "uas-utm", "Pairwise encounters from surveillance tracks scored with DAIDALUS well-clear definitions.",
          ("surveillance recording", "DAIDALUS parameters"), ("violations per flight hour", "alert lead time"), "planned", None, ("nasa/daidalus", "nasa/WellClear")),
    Study("ST-08", "Airborne collision risk classes", "What is the unmitigated collision risk of observed encounters by airspace class?",
          "uas-utm", "Encounter-model based risk classes (ASTM F3442 lineage) over recorded tracks.",
          ("surveillance recording",), ("risk class distribution",), "planned", None, ("mit-ll/air-risk-class", "mit-ll/em-core")),
    Study("ST-09", "UTM API conformance", "Do exchanges match the NASA UTM OpenAPI contracts?",
          "uas-utm", "Schema validation of captured exchanges against nasa/utm-apis documents.", ("captured exchanges", "OpenAPI documents"), ("conformance failures by endpoint",), "planned", None, ("nasa/utm-apis",)),
    Study("ST-11", "Airports inside a crisis extent", "Which airports and hubs sit inside or near a flood, fire or disaster extent?",
          "earth-crisis", "Point-in-polygon of the airport table against GeoJSON extents (Crisis Mapping Toolkit exports), plus a distance buffer.",
          ("GeoJSON extent",), ("airports inside", "airports near", "major hubs affected"), "runnable", "airports_in_extent", ("nasa/CrisisMappingToolkit",)),
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
