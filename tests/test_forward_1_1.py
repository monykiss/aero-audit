"""After 1.0: the all-in-one overview board (view, route, CLI), the traffic-displacement study over TFR history, and the
mission job's default launch."""

import json
from pathlib import Path

from typer.testing import CliRunner

from aero_audit import cli
from aero_audit.governance.studies import STUDIES, run_study
from aero_audit.space import airspace

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "adsblol_nyc_20260910T115129Z.jsonl.gz"


def _tree(tmp_path):
    (tmp_path / "data/samples").mkdir(parents=True)
    for name in ("tfr_sample.json", "ll2_launches_sample.json", "swpc_scales_sample.json", "decaying_sample.tle", SAMPLE):
        (tmp_path / "data/samples" / name).write_bytes((ROOT / "data/samples" / name).read_bytes())
    (tmp_path / "data/airspace").mkdir()
    (tmp_path / "data/airspace/tfr_20260910T113000Z.json").write_bytes((ROOT / "data/samples/tfr_sample.json").read_bytes())
    (tmp_path / "data/space/launches").mkdir(parents=True)
    (tmp_path / "data/space/launches/ll2_upcoming_20260910T110000Z.json").write_bytes((ROOT / "data/samples/ll2_launches_sample.json").read_bytes())
    (tmp_path / "data/space/spaceweather").mkdir(parents=True)
    (tmp_path / "data/space/spaceweather/swpc_20260910T110000Z.json").write_bytes((ROOT / "data/samples/swpc_scales_sample.json").read_bytes())
    (tmp_path / "data/space/elements").mkdir(parents=True)
    (tmp_path / "data/space/elements/decaying.tle").write_bytes((ROOT / "data/samples/decaying_sample.tle").read_bytes())


def test_overview_board_from_cached_products(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tree(tmp_path)
    from aero_audit.web import views

    views._cache.clear()
    ov = views.overview()
    assert ov["airspace"]["space_ops"] == 2 and ov["airspace"]["in_effect"] == [] and ov["airspace"]["next"] is None  # the synthetic restrictions are in the past
    assert ov["launches"]["cached"] == 2 and ov["launches"]["within_24h"] == 0 and ov["launches"]["next"][0]["name"].startswith("Sample Launch")
    assert ov["space_weather"]["scales_now"]["G"] == 4 and ov["space_weather"]["advisories"]["G"] == "moderate"
    assert ov["decaying"]["objects"] == 1 and ov["decaying"]["top"][0]["norad"] == 99999
    assert ov["conjunctions"] is None and ov["uas"] is None and ov["reports"]["total"] == 0
    monkeypatch.setenv("AERO_SCHEDULE", "")
    from aero_audit.web.app import App, r_overview

    app = App()
    try:
        assert r_overview(app, {"query": {}})["launches"]["cached"] == 2
    finally:
        app.scheduler.stop()
        app.sources.stop()
    r = CliRunner().invoke(cli.app, ["overview"])
    assert r.exit_code == 0 and "space-ops TFRs in effect" in r.output and "objects decaying" in r.output, r.output
    r = CliRunner().invoke(cli.app, ["overview", "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["decaying"]["objects"] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    views._cache.clear()
    ov2 = views.overview()
    assert ov2["airspace"] is None and ov2["launches"] is None and ov2["space_weather"] is None and ov2["reports"]["total"] == 0


def test_displacement_over_tfr_history_and_recordings():
    rec = ROOT / "data/samples" / SAMPLE
    d = airspace.displacement([ROOT / "data/samples/tfr_sample.json"], [rec], max_batches=4)
    rows = {r["notam_id"]: r for r in d["rows"]}
    assert d["restrictions"] == 2 and len(d["rows"]) == 2
    r2 = rows["SYN 6/0002"]
    assert r2["minutes_during"] > 0 and r2["minutes_outside"] == 0 and r2["aircraft_inside_during"] > 0 and r2["displacement_ratio"] is None  # only the effective window was recorded
    # the same product shifted so the recording falls outside the effective window: traffic becomes the baseline
    shifted = json.loads((ROOT / "data/samples/tfr_sample.json").read_text())
    for f in shifted["features"]:
        f["effective_ts"] += 86400
        f["expire_ts"] += 86400
        f["notam_id"] += " late"
    p = Path("reports") / "_tmp_tfr_shifted.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(shifted))
    try:
        d2 = airspace.displacement([ROOT / "data/samples/tfr_sample.json", p], [rec], max_batches=4)
        rows2 = {r["notam_id"]: r for r in d2["rows"]}
        assert d2["restrictions"] == 4 and rows2["SYN 6/0002 late"]["aircraft_inside_outside"] == r2["aircraft_inside_during"] and rows2["SYN 6/0002 late"]["minutes_during"] == 0
    finally:
        p.unlink()
    assert "ST-25" in STUDIES and STUDIES["ST-25"].runner == "tfr_displacement"
    res = run_study("ST-25", Path("reports/studies"), tfr=ROOT / "data/samples/tfr_sample.json", recording=rec)["result"]
    assert res["restrictions"] == 2 and res["recordings"] == 1


def test_mission_job_defaults_to_the_next_launch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tree(tmp_path)
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job

    res = space_jobs.mission(Job("j", "mission", {}), {"file": "data/samples/ll2_launches_sample.json", "tfr": "data/samples/tfr_sample.json"})
    assert res["launch"].startswith("Sample Launch | Wallops") and Path(res["report"]).is_file()


def test_app_info_picks_the_newest_anomaly_model_not_a_classifier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AERO_SCHEDULE", "")
    (tmp_path / "models").mkdir()
    (tmp_path / "models/registry.json").write_text(json.dumps([
        {"model_path": "models/anomaly.joblib", "rows": 1000, "holdout_flag_rate": 0.01, "evaluation": {"recall": {"ghost": 0.9}}},
        {"model_path": "models/scene_classifier_study.joblib", "rows": 400, "holdout_flag_rate": 0.0, "evaluation": {"accuracy": 0.64, "per_class": {}}},  # the registry writer fills every field
    ]))
    from aero_audit.web.app import App

    app = App()
    try:
        info = app.info()
    finally:
        app.scheduler.stop()
        app.sources.stop()
    assert info["model"]["model_path"] == "models/anomaly.joblib" and info["model"]["evaluation"]["recall"]["ghost"] == 0.9
