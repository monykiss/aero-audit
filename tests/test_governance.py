"""Governance layer: referential integrity, coverage math, unified register, posture, runnable studies."""

import csv
import json
import math

from aero_audit.governance import (
    CONTROLS,
    DOMAINS,
    POLICIES,
    STANDARDS,
    STUDIES,
    coverage,
    implementation_index,
    posture,
    render_posture,
    run_study,
    unified_register,
)
from aero_audit.governance.controls import render_markdown as render_controls
from aero_audit.governance.controls import validate
from aero_audit.governance.register import by_rating
from aero_audit.governance.register import render_markdown as render_register
from aero_audit.governance.studies import render_markdown as render_studies
from aero_audit.synthetic import generate


def test_library_is_referentially_clean():
    assert validate() == []
    assert set(DOMAINS) >= {"air-surveillance", "air-operations", "space-assets", "space-launch", "space-orbital", "uas-utm"}
    assert all(s.area in ("air", "space", "cyber", "software", "data") for s in STANDARDS.values())
    for c in CONTROLS.values():
        assert c.domains and c.standards or c.status == "planned", c.id
    assert all(cid in CONTROLS for p in POLICIES for cid in p.controls)


def test_coverage_and_index():
    cov = coverage()
    assert cov["standards_total"] == len(STANDARDS) and 0 < cov["standards_with_controls"] <= cov["standards_total"]
    assert sum(sum(v.values()) for v in cov["by_pillar"].values()) == len(CONTROLS)
    idx = implementation_index()
    assert 0.5 < idx < 1.0
    planned_only = {k: v for k, v in CONTROLS.items() if v.status == "planned"}
    assert implementation_index(planned_only) == 0.0


def test_unified_register_spans_domains():
    rows = unified_register(None)
    ids = {r["id"] for r in rows}
    assert {"R01", "R04", "S01", "S05", "U01"} <= ids
    domains = {r["domain"] for r in rows}
    assert {"air-surveillance", "space-launch", "space-orbital", "uas-utm", "space-assets"} <= domains
    s05 = next(r for r in rows if r["id"] == "S05")
    assert s05["residual"] == s05["score"] == 15 and s05["residual_rating"] == "critical"  # planned control: no reduction
    s03 = next(r for r in rows if r["id"] == "S03")
    assert s03["residual"] < s03["score"] and s03["control_effectiveness"] == 0.6
    assert rows[0]["residual_rating"] in ("critical", "high")
    assert sum(by_rating(rows).values()) == len(rows)
    assert "| S05 |" in render_register(rows)


def test_posture_static_and_live(tmp_path, monkeypatch):
    p = posture(static=True)
    assert p["generated_at"] is None and 0 < p["governance_index"] < 1 and p["freshness"] is None
    assert {d["key"] for d in p["domains"]} == set(DOMAINS) and p["studies"]["runnable"] >= 4
    md = render_posture(p)
    assert "Governance index" in md and "space-orbital" in md and "## Evidence on disk" not in md
    monkeypatch.chdir(tmp_path)  # no reports, model, or audit log here
    live = posture()
    assert live["freshness"]["audit_chain_ok"] is None and live["freshness"]["model_verified"] is None
    assert live["components"]["evidence_freshness"] == 0.0 and live["evidence"]["missing"]  # file-backed evidence is elsewhere
    assert "## Evidence on disk" in render_posture(live)
    assert "C-01" in render_controls() and "ST-06" in render_studies()


def test_runnable_studies_on_synthetic_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = generate(tmp_path / "synthetic.jsonl", n_aircraft=30, polls=12, seed=8)
    r1 = run_study("ST-01", tmp_path / "studies", recording=rec)
    assert r1["result"]["airborne_adsb_fixes"] > 0 and r1["params"]["recording"]["sha256"] and (tmp_path / "studies").glob("ST-01_*.json")
    r5 = run_study("ST-05", tmp_path / "studies", recording=rec)
    assert "by_airport" in r5["result"] and r5["provenance"]["tool"] == "aero-audit"
    p = tmp_path / "t.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "speed_mps", "altitude_km"])
        v = alt = 0.0
        for i in range(120):
            t = i * 0.5
            v += 30 * 0.5
            alt += v * math.sin(math.radians(80)) * 0.5 / 1000
            w.writerow([t, round(v, 2), round(alt, 4)])
    r3 = run_study("ST-03", tmp_path / "studies", csv=p)
    assert r3["result"]["findings"] == 0 and r3["result"]["samples"] == 120
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "evaluation.json").write_text(json.dumps({"scenarios": [{"name": "teleport", "recall": 0.96}], "median_revisit_s": 20, "rule_precision": {"SEC-010": 1.0}}))
    r2 = run_study("ST-02", tmp_path / "studies")
    assert r2["result"]["scenarios"][0]["recall"] == 0.96
    try:
        run_study("ST-06", tmp_path / "studies")
    except RuntimeError as e:
        assert "planned" in str(e)
    else:
        raise AssertionError("planned study must not run")
    assert len(STUDIES) >= 10
