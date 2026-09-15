"""Risk classes and the DAA risk ratio; NOAA space weather mapped to ICAO conditions; launch windows joined to traffic;
the integration inventory; the scheduler; the Space and UAS summaries and routes."""

import calendar
import json
import time
from pathlib import Path

import pytest

from aero_audit.integrations import INTEGRATIONS, missing, status
from aero_audit.space import launches, spaceweather
from aero_audit.uas import risk
from aero_audit.web.schedule import NETWORK_JOBS, Scheduler, parse_schedule

SAMPLE = Path("data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz")
SWPC = Path("data/samples/swpc_scales_sample.json")
LL2 = Path("data/samples/ll2_launches_sample.json")
T_REC = float(calendar.timegm(time.strptime("2026-09-10T11:55:00Z", "%Y-%m-%dT%H:%M:%SZ")))  # inside the NYC sample and both launch windows


def test_density_classes_and_risk_ratio_from_summary():
    assert [risk.density_class(x) for x in (0.0, 0.1, 1.0, 100.0)] == ["sparse", "moderate", "dense", "very-dense"]
    rr = risk.risk_ratio({"pairs": [{"nmac_proximate": True, "lead_time_s": 10.0}, {"nmac_proximate": True, "lead_time_s": 40.0}, {"nmac_proximate": False, "lead_time_s": None}]})
    assert rr["nmac_proximate"] == 2 and rr["unresolvable"] == 1 and rr["risk_ratio"] == 0.5
    assert risk.risk_ratio({"pairs": []})["risk_ratio"] is None


def test_risk_assessment_on_the_sample_recording():
    summary, fs = risk.assess(SAMPLE, max_batches=6)
    bands = summary["density"]["bands"]
    assert set(bands) == {b[0] for b in risk.BANDS} and sum(v["cells"] for v in bands.values()) == summary["density"]["cells_total"]
    assert summary["flight_hours"] > 0 and summary["risk_ratio"]["encounters"] > 0
    rules = {f.rule_id for f in fs}
    assert rules <= {"DAA-003", "DAA-004"} and "DAA-004" in rules  # New York has dense low-altitude cells
    assert all(f.evidence["stream"] == SAMPLE.name for f in fs)


def test_space_weather_sample_maps_to_icao_conditions_and_flags_staleness():
    payload = json.loads(SWPC.read_text())
    now = float(calendar.timegm(time.strptime("2026-09-15T12:30:00Z", "%Y-%m-%dT%H:%M:%SZ")))
    summary, fs = spaceweather.assess(payload, now=now)
    assert summary["scales_now"] == {"R": 3, "S": 2, "G": 4} and summary["kp"] == 8.0
    assert summary["icao_advisory_conditions"] == {"G": "moderate", "R": "moderate", "S": None}
    assert {f.rule_id for f in fs} == {"SWX-001", "SWX-002"} and all(f.severity.value == "medium" for f in fs)
    _, stale = spaceweather.assess(payload, now=now + 5 * 3600)
    assert "SWX-004" in {f.rule_id for f in stale}
    quiet = {"scales": {"0": {"R": {"Scale": "0"}, "S": {"Scale": "0"}, "G": {"Scale": "1"}}}, "kp": [], "fetched_at": "20260915T120000Z"}
    s2, f2 = spaceweather.assess(quiet, now=now)
    assert f2 == [] and s2["icao_advisory_conditions"] == {"G": None, "R": None, "S": None}


def test_space_weather_exposed_flights_uses_the_recording():
    exp, fs = spaceweather.exposed_flights(SAMPLE, {"G": "moderate", "R": None, "S": None}, lat_min=40.0, max_batches=2)
    assert exp["aircraft"] > 0 and fs and fs[0].rule_id == "SWX-005" and fs[0].evidence["conditions"] == {"G": "moderate"}
    exp2, fs2 = spaceweather.exposed_flights(SAMPLE, {"G": None, "R": "moderate", "S": None}, lat_min=40.0, max_batches=2)
    assert exp2["aircraft"] > 0 and fs2 == []  # HF conditions alone are not a latitude exposure
    exp3, _ = spaceweather.exposed_flights(SAMPLE, {"G": "severe", "R": None, "S": None}, lat_min=60.0, max_batches=2)
    assert exp3["aircraft"] == 0


def test_launch_parse_and_join_to_traffic():
    raw = {"results": [{"id": "x1", "name": "Falcon 9 | Demo", "status": {"abbrev": "Go"}, "net": "2026-09-10T12:00:00Z", "window_start": "2026-09-10T11:45:00Z",
                        "window_end": "2026-09-10T12:15:00Z", "launch_service_provider": {"name": "SpaceX"},
                        "pad": {"name": "SLC-40", "latitude": "28.56", "longitude": "-80.58", "location": {"name": "Cape Canaveral", "country_code": "USA"}}, "last_updated": "2026-09-10T10:00:00Z"}]}
    rows = launches.parse(raw)
    assert rows[0]["pad_lat"] == 28.56 and rows[0]["provider"] == "SpaceX" and rows[0]["status"] == "Go"
    payload = json.loads(LL2.read_text())
    summary, fs = launches.join_traffic(payload, SAMPLE, hazard_nm=250.0, now=T_REC, max_batches=4)
    by = {r["name"]: r for r in summary["rows"]}
    wallops, vandenberg = by["Sample Launch | Wallops (synthetic)"], by["Sample Launch | Vandenberg (synthetic)"]
    assert wallops["overlaps_recording"] and wallops["pad_in_recorded_region"] and wallops["aircraft_inside_during_window"] > 0
    assert vandenberg["overlaps_recording"] and not vandenberg["pad_in_recorded_region"] and vandenberg["aircraft_inside_during_window"] == 0
    rules = sorted(f.rule_id for f in fs)
    assert rules == ["LCH-001", "LCH-002", "LCH-003"]  # traffic near Wallops; Vandenberg stale-in-hold and out of region
    lch1 = next(f for f in fs if f.rule_id == "LCH-001")
    assert lch1.evidence["closest"][0]["min_nm"] <= 250.0 and lch1.callsign
    tight, fs_tight = launches.join_traffic(payload, SAMPLE, hazard_nm=20.0, now=T_REC, max_batches=4)
    assert by and not any(f.rule_id == "LCH-001" for f in fs_tight) and tight["rows"][0]["aircraft_inside_during_window"] == 0


def test_integration_inventory_never_prints_values(monkeypatch):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASS", raising=False)
    assert "spacetrack" in missing()
    monkeypatch.setenv("SPACETRACK_USER", "someone")
    monkeypatch.setenv("SPACETRACK_PASS", "hunter2-not-a-real-secret")
    rows = {r["key"]: r for r in status()}
    assert rows["spacetrack"]["configured"] and "spacetrack" not in missing()
    assert "hunter2" not in json.dumps(rows) and rows["celestrak"]["required"] is False and rows["celestrak"]["configured"]
    assert all(i.keyless for i in INTEGRATIONS.values()) and {"opensky", "spacetrack", "nasa_api", "ll2", "swpc"} <= set(INTEGRATIONS)


def test_scheduler_parses_fires_and_skips_network_jobs_offline():
    assert parse_schedule("cdm_inbox=600, launches=30,bad,x=y") == {"cdm_inbox": 600.0, "launches": 60.0}
    fired: list[tuple[str, dict]] = []
    s = Scheduler(lambda t, p: fired.append((t, p)), {"cdm_inbox", "launches"}, {"cdm_inbox": 60.0, "launches": 60.0, "unknown_job": 60.0}, offline=True)
    assert s.unknown == ["unknown_job"] and set(s.schedule) == {"cdm_inbox", "launches"}
    t0 = time.time() + 10
    assert sorted(s.tick(t0)) == ["cdm_inbox"] and s.skipped["launches"] == 1 and "launches" in NETWORK_JOBS
    assert s.tick(t0 + 30) == [] and s.tick(t0 + 61) == ["cdm_inbox"]
    st = s.status()
    assert st["offline"] and {e["job"]: e["runs"] for e in st["entries"]} == {"cdm_inbox": 2, "launches": 0}
    online = Scheduler(lambda t, p: fired.append((t, p)), {"launches"}, {"launches": 60.0}, offline=False)
    assert online.tick(time.time() + 10) == ["launches"] and fired[-1] == ("launches", {"scheduled": True})
    broken = Scheduler(lambda t, p: (_ for _ in ()).throw(KeyError("boom")), {"cdm_inbox"}, {"cdm_inbox": 60.0})
    assert broken.tick(time.time() + 10) == [] and broken.runs["cdm_inbox"] == 0  # a failing submit does not kill the loop


def test_space_and_uas_summaries_and_routes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AERO_SCHEDULE", "cdm_inbox=600,launches=900,nonsense=60")
    monkeypatch.setenv("AERO_OFFLINE", "1")
    from aero_audit.web import space_jobs
    from aero_audit.web.app import App, r_integrations, r_schedule, r_space, r_uas
    from aero_audit.web.jobs import Job

    (tmp_path / "data/samples").mkdir(parents=True)
    (tmp_path / "data/samples" / SAMPLE.name).write_bytes((Path(__file__).parent.parent / SAMPLE).read_bytes())
    rec = f"data/samples/{SAMPLE.name}"
    space_jobs.space_weather(Job("j1", "space_weather", {}), {"file": str(Path(__file__).parent.parent / SWPC), "recording": rec, "lat_min": 40.0})
    space_jobs.launches(Job("j2", "launches", {}), {"file": str(Path(__file__).parent.parent / LL2), "recording": rec, "hazard_nm": 250.0})
    r = space_jobs.uas_risk(Job("j3", "uas_risk", {}), {"recording": rec, "max_batches": 4})
    assert Path(r["report"]).is_file() and "risk_ratio" in r  # None when no NMAC-proximate pair exists in the first batches
    (tmp_path / "data/space/spaceweather").mkdir(parents=True)
    (tmp_path / "data/space/spaceweather/swpc_20260915T120000Z.json").write_text((Path(__file__).parent.parent / SWPC).read_text())
    app = App()
    try:
        sp = r_space(app, {"query": {}})
        assert sp["space_weather"]["scales_now"]["G"] == 4 and sp["space_weather"]["icao_advisory_conditions"]["G"] == "moderate"
        assert sp["reports"]["space_weather"] and sp["reports"]["launches"] and sp["cdm"]["ledger_rows"] == 0
        u = r_uas(app, {"query": {}})
        assert u["risk"]["summary"]["risk_ratio"]["limit"] == risk.RISK_RATIO_LIMIT and u["reports"]["uas_risk"]
        sc = r_schedule(app, {"query": {}})
        assert sc["offline"] and sc["unknown"] == ["nonsense"] and {e["job"] for e in sc["entries"]} == {"cdm_inbox", "launches"} and "space_weather" in sc["job_types"]
        it = r_integrations(app, {"query": {}})
        assert {i["key"] for i in it["items"]} == set(INTEGRATIONS) and "note" in it
        kinds = {g["kind"] for g in app.reports()}
        assert {"space: weather", "space: launches", "uas: risk classes"} <= kinds
    finally:
        app.scheduler.stop()
        app.sources.stop()


@pytest.mark.parametrize("study", ["ST-16", "ST-17", "ST-18"])
def test_new_studies_run_offline(tmp_path, study):
    from aero_audit.governance import run_study

    params = {"recording": SAMPLE, "max_batches": 3} if study == "ST-16" else ({"recording": SAMPLE, "lat_min": 40.0} if study == "ST-17" else {"recording": SAMPLE, "hazard_nm": 250.0})
    rec = run_study(study, tmp_path / "studies", **params)
    assert rec["result"]["findings"] and Path(rec["files"]["md"]).is_file()


def test_summaries_are_strict_json():
    """Browsers reject Infinity/NaN; every value the pages read must survive a strict parse."""
    import math

    from aero_audit.web.views import space_summary, uas_summary

    for s in (space_summary(), uas_summary()):
        json.loads(json.dumps(s), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert risk.density({"pairs": []} and SAMPLE, max_batches=1)["class_limits_per_100nm2_h"][-1] is None and math.isinf(risk.DENSITY_CLASSES[-1][1])
