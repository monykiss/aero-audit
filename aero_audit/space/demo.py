"""One offline pass over every space and UAS analysis on the bundled samples: the portfolio demo and the smoke test
for the whole private branch. Each step writes a report with a manifest; the table at the end says what fired."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SAMPLES = Path("data/samples")


def run(out: str | Path = "reports", recording: str | Path | None = None, max_batches: int | None = None) -> list[dict[str, Any]]:
    from ..audit.generic_report import write_generic
    from ..ingest.replay import iter_recording
    from ..space import debris, launches, spaceweather
    from ..space.cdm import assess as cdm_assess
    from ..space.cdm import parse_cdm
    from ..uas import encounter_model, extract_encounters, risk, summarize_encounters

    rec = Path(recording) if recording else SAMPLES / "adsblol_nyc_20260910T115129Z.jsonl.gz"
    rows: list[dict[str, Any]] = []

    def step(name: str, key: str, payload: Any, fs: list[Any], inputs: dict[str, Any]) -> None:
        paths = write_generic(out, name, key, payload, fs, inputs=inputs)
        rows.append({"step": name, "report": str(paths["json"]), "manifest": str(paths["manifest"]), "findings": len(fs), "rules": sorted({f.rule_id for f in fs})})

    m = debris.Mission.from_json(SAMPLES / "synthetic_mission.json")
    summary, fs = debris.checklist(m)
    step(f"debris_{m.name}", "summary", summary, fs, {"mission": SAMPLES / "synthetic_mission.json"})
    cdm = parse_cdm((SAMPLES / "synthetic_conjunction.cdm").read_text())
    res, fs = cdm_assess(cdm)
    step("cdm_synthetic", "assessment", res, fs, {"cdm": SAMPLES / "synthetic_conjunction.cdm"})
    payload = json.loads((SAMPLES / "swpc_scales_sample.json").read_text())
    summary, fs = spaceweather.assess(payload)
    exp, fs2 = spaceweather.exposed_flights(rec, summary["icao_advisory_conditions"], 40.0, max_batches)
    summary["exposed"] = exp
    step("space_weather", "summary", summary, fs + fs2, {"product": SAMPLES / "swpc_scales_sample.json", "recording": rec})
    payload = json.loads((SAMPLES / "ll2_launches_sample.json").read_text())
    summary, fs = launches.join_traffic(payload, rec, 250.0, max_batches=max_batches)
    step("launches", "summary", summary, fs, {"launches": SAMPLES / "ll2_launches_sample.json", "recording": rec})
    # the air/space seam: published space-operations airspace, reentry corridors, and the dossier of one launch
    from datetime import UTC, datetime

    from ..ingest import tfr as tfr_mod
    from ..space import airspace, mission, reentry, satcat

    tfr_payload = tfr_mod.load(SAMPLES / "tfr_sample.json")
    t_summary, fs = airspace.join_traffic(tfr_payload, rec, max_batches=max_batches)
    l_summary, fs2 = airspace.join_launches(tfr_payload, payload, now=datetime(2026, 9, 10, 11, 52, tzinfo=UTC).timestamp())
    step("tfr", "summary", {"product": tfr_mod.summary(SAMPLES / "tfr_sample.json"), "traffic": t_summary, "launches": l_summary}, fs + fs2,
         {"tfr": SAMPLES / "tfr_sample.json", "launches": SAMPLES / "ll2_launches_sample.json", "recording": rec})
    first = None
    for b in iter_recording(rec):
        ts_ = [sv.ts for sv in b.states if sv.ts]
        if ts_:
            first = datetime.fromtimestamp(min(ts_), UTC)
            break
    summary, fs = reentry.analyse([SAMPLES / "decaying_sample.tle"], rec, first, 0.5, 10.0, max_batches=max_batches)
    step("reentry", "summary", summary, fs, {"elements": SAMPLES / "decaying_sample.tle", "recording": rec})
    launch = mission.find_launch(payload, "wallops")
    if launch:
        d, fs = mission.dossier(launch, rec, tfr_payload, json.loads((SAMPLES / "swpc_scales_sample.json").read_text()), satcat.load() or None, 250.0, max_batches=max_batches)
        step("mission_sample_wallops", "dossier", d, fs, {"launches": SAMPLES / "ll2_launches_sample.json", "tfr": SAMPLES / "tfr_sample.json", "product": SAMPLES / "swpc_scales_sample.json", "recording": rec})
    ex = extract_encounters(rec, max_batches=max_batches)
    summary, fs = summarize_encounters(ex)
    step(f"wellclear_{rec.stem.split('.')[0]}", "summary", summary, fs, {"recording": rec})
    summary, fs = risk.assess(rec, max_batches=max_batches)
    step(f"uas_risk_{rec.stem.split('.')[0]}", "summary", summary, fs, {"recording": rec})
    res = encounter_model.fit_and_simulate(rec, 500, max_batches=max_batches)
    step(f"encounter_model_{rec.stem.split('.')[0]}", "summary", res, [], {"recording": rec})
    # real launch telemetry (public domain, bundled): the SPC rules on a genuine ascent
    from ..space.telemetry import audit_telemetry, load_any, summarize

    tp = SAMPLES / "gps3sv01_telemetry.json"
    pts = load_any(tp)
    fs = audit_telemetry(pts, stream=tp.stem)
    step("gps3sv01_telemetry", "summary", summarize(pts, fs), fs, {"telemetry": tp})
    # an SDLS packet stream: per-packet authentication with the documented demo key (a forged packet, a replay, an unsigned one)
    import os

    from ..space.telemetry import load_with_auth

    os.environ.setdefault("AERO_SDLS_KEY_1", "aero-sdls-demo-key")
    sp = SAMPLES / "sdls_packets_sample.json"
    pts, auth, afs = load_with_auth(sp)
    fs = audit_telemetry(pts, stream=sp.stem) + afs
    step("sdls_packets", "summary", summarize(pts, fs, auth), fs, {"telemetry": sp})
    # apron capacity from detections: the detector's own output on the sample image, scored against the annotations
    from ..vision import detections_from_json, evaluate, occupancy, zone_findings, zones_from_json

    zl = zones_from_json(SAMPLES / "apron_hohn_zones.json")
    truth = detections_from_json(SAMPLES / "apron_hohn_truth.json")
    det_file = SAMPLES / "apron_hohn_detections_aircraft.json"  # the registered fine-tune's output; the COCO baseline file is kept beside it
    if not det_file.is_file():
        det_file = SAMPLES / "apron_hohn_detections_yolov8n.json"
    dets = detections_from_json(det_file) if det_file.is_file() else truth
    occ = occupancy(dets, zl)
    fs = zone_findings(occ, zl, "apron_hohn.jpg", 0.0)
    step("apron_hohn", "summary", {"image": "apron_hohn.jpg", "zones": [{"name": z.name, "capacity": z.capacity, "count": occ.get(z.name, 0)} for z in zl], "detections": len(dets),
                                   "source": det_file.name if det_file.is_file() else "annotations", "evaluation": evaluate(dets, truth)}, fs,
         {"image": SAMPLES / "apron_hohn.jpg", "zones": SAMPLES / "apron_hohn_zones.json", "truth": SAMPLES / "apron_hohn_truth.json"})
    # NASA's real UTM contract when it has been fetched (aero uas utm-fetch); the bundled samples otherwise stay unchecked
    contract = Path("data/uas/utm-domain-commons.json")
    if contract.is_file():
        from ..uas.utm import check_samples, load_document

        doc = load_document(contract)
        samples = [(p.name, json.loads(p.read_text())) for p in (SAMPLES / "utm_position_sample.json", SAMPLES / "utm_position_bad.json")]
        rep = check_samples(doc, samples, schema_name="Position")
        step("utm_conformance", "summary", rep, [], {"contract": contract})
    # live crisis extents when cached (aero data crisis-fetch): airports inside real warning polygons
    from ..ingest import nws_alerts

    gj = nws_alerts.latest()
    if gj:
        from ..governance.studies import _airports_in_extent

        step("crisis_airports", "summary", _airports_in_extent(gj), [], {"extents": gj})
    return rows


__all__ = ["run"]
