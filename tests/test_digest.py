"""The digest folds a reports directory into one brief with a manifest and survives empty or odd inputs."""

import json
import time
from pathlib import Path

from aero_audit import provenance
from aero_audit.governance import digest


def _report(folder: Path, stem: str, findings: list[dict], age_s: float = 0.0, degraded: bool = False, manifest: bool = True) -> None:
    p = folder / f"{stem}.json"
    p.write_text(json.dumps({"summary": {"degraded": degraded}, "findings": findings}))
    if manifest:
        (folder / f"{stem}.manifest.json").write_text("{}")
    t = time.time() - age_s
    import os

    os.utime(p, (t, t))


def test_digest_groups_counts_and_renders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rep = tmp_path / "reports"
    rep.mkdir()
    _report(rep, "space_weather_20260917T120000Z", [{"rule_id": "SWX-001", "severity": "medium", "title": "G4"}], degraded=True)
    _report(rep, "wellclear_nyc_20260917T120000Z", [{"rule_id": "DAA-001", "severity": "high", "title": "v", "callsign": "A/B"}, {"rule_id": "DAA-002", "severity": "medium", "title": "l"}], manifest=False)
    _report(rep, "gps3sv01_telemetry_20260917T120000Z", [])
    _report(rep, "old_thing_20260101T000000Z", [{"rule_id": "X", "severity": "critical", "title": "ancient"}], age_s=30 * 86400)
    (rep / "broken.json").write_text("{not json")
    d = digest.build(7.0, rep)
    assert d["reports"] == 3 and set(d["by_kind"]) == {"space_weather", "wellclear", "telemetry"}
    assert d["findings_by_severity"] == {"medium": 2, "high": 1} and d["findings_by_rule"]["DAA-001"] == 1
    assert d["worst"][0]["rule_id"] == "DAA-001" and d["worst"][0]["report"].startswith("wellclear")
    assert d["reports_without_manifest"] == ["wellclear_nyc_20260917T120000Z.json"] and d["degraded_reports"] == ["space_weather_20260917T120000Z.json"]
    assert "governance_index" in d["posture"] and "passed" in d["publish"]
    md = digest.render_markdown(d)
    assert "| wellclear | 1 | 2 | 0 | 0 |" in md and "## Worst findings" in md and "Reports without a manifest" in md
    paths = digest.write(7.0, rep)
    assert paths["md"].read_text().startswith("# Digest") and provenance.verify_manifest(paths["manifest"])["ok"]
    again = digest.build(7.0, rep)
    assert again["reports"] == 3  # the digest itself is not counted


def test_digest_on_an_empty_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports").mkdir()
    d = digest.build(7.0, tmp_path / "reports")
    assert d["reports"] == 0 and d["worst"] == [] and d["live_check"] is None and d["classifier_holdout"] is None
    assert "none" in digest.render_markdown(d)
