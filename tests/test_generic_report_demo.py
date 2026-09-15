"""Every non-engine report carries a manifest with provenance; the offline space demo runs end to end; doctor reports the space stack."""

import json
from pathlib import Path

from typer.testing import CliRunner

from aero_audit import cli, provenance
from aero_audit.audit.generic_report import build_provenance, render_markdown, write_generic
from aero_audit.space import demo


def test_generic_report_writes_json_md_manifest_and_verifies(tmp_path):
    inp = tmp_path / "in.json"
    inp.write_text("{}")
    paths = write_generic(tmp_path / "reports", "thing_x", "summary", {"a": 1, "nested": {"b": 2.5, "deep": {"c": 3}}, "items": [1, 2]}, [], inputs={"input": inp, "absent": tmp_path / "nope"})
    assert all(p.is_file() for p in paths.values()) and paths["manifest"].name == paths["json"].stem + ".manifest.json"
    d = json.loads(paths["json"].read_text())
    assert d["summary"]["a"] == 1 and d["findings"] == [] and d["provenance"]["inputs"]["input"]["sha256"] and d["provenance"]["inputs"]["absent"]["sha256"] is None
    md = paths["md"].read_text()
    assert "| nested.b | 2.5 |" in md and "| items | 2 item(s) |" in md and "none" in md
    v = provenance.verify_manifest(paths["manifest"])
    assert v["ok"]
    paths["md"].write_text(md + "tampered\n")
    assert not provenance.verify_manifest(paths["manifest"])["ok"]
    prov = build_provenance()
    assert prov["tool"] == "aero-audit" and prov["inputs"] == {} and "generated_at" in prov
    assert "## Findings (1)" in render_markdown("t", "summary", {}, [{"rule_id": "X-1", "severity": "low", "title": "a | b"}], prov)


def test_space_demo_runs_offline_and_every_report_has_a_manifest(tmp_path):
    rows = demo.run(tmp_path / "reports", max_batches=4)
    steps = {r["step"].split("_")[0] for r in rows}
    assert {"debris", "cdm", "space", "launches", "wellclear", "uas", "encounter"} <= steps
    for r in rows:
        assert Path(r["report"]).is_file() and Path(r["manifest"]).is_file()
        assert provenance.verify_manifest(r["manifest"])["ok"]
    assert any("ORB-004" in r["rules"] for r in rows) and any("DEB-001" in r["rules"] or "DEB-003" in r["rules"] for r in rows)
    assert any("LCH-001" in r["rules"] for r in rows) and any("SWX-001" in r["rules"] for r in rows)


def test_space_demo_command_and_doctor_rows(tmp_path):
    runner = CliRunner()
    r = runner.invoke(cli.app, ["space", "demo", "--out", str(tmp_path / "r"), "--max-batches", "3", "--no-docs"])
    assert r.exit_code == 0, r.output
    assert "wellclear" in r.output and len(list((tmp_path / "r").glob("*.manifest.json"))) >= 7
    r = runner.invoke(cli.app, ["doctor", "--no-net"])
    assert r.exit_code in (0, 1) and "space: sgp4" in r.output and "space: samples" in r.output
