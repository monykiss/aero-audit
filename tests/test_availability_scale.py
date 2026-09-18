"""Scheduler guards (no stacking, politeness floors, backoff), cached-product degradation, feed health, and the trend study."""

import json
import time
from pathlib import Path

import pytest

from aero_audit.uas import trend as tr
from aero_audit.web.schedule import MAX_BACKOFF_FACTOR, MIN_INTERVALS, Scheduler, parse_schedule

NYC = Path("data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz")
HUBS = Path("data/samples/adsblol_usa-hubs_20260910T130638Z.jsonl.gz")


def test_scheduler_never_stacks_and_honours_politeness_floors():
    assert parse_schedule("launches=60,space_weather=30,cdm_inbox=60") == {"launches": MIN_INTERVALS["launches"], "space_weather": MIN_INTERVALS["space_weather"], "cdm_inbox": 60.0}
    running = {"cdm_inbox": True}
    fired = []
    s = Scheduler(lambda t, p: fired.append(t), {"cdm_inbox", "catalog_build"}, {"cdm_inbox": 60.0, "catalog_build": 60.0}, is_running=lambda n: running.get(n, False))
    t0 = time.time() + 10
    assert s.tick(t0) == ["catalog_build"] and s.deferred["cdm_inbox"] == 1
    running["cdm_inbox"] = False
    assert s.tick(t0 + 61) == ["cdm_inbox", "catalog_build"] or set(s.tick(t0 + 61)) == {"cdm_inbox", "catalog_build"}


def test_scheduler_backs_off_on_failures_and_resets_on_success():
    fired = []
    s = Scheduler(lambda t, p: fired.append(t), {"launches"}, {"launches": 300.0})
    t0 = time.time() + 10
    assert s.tick(t0) == ["launches"]
    s.report("launches", ok=False)
    s.report("launches", ok=False)
    st = {e["job"]: e for e in s.status()["entries"]}
    assert st["launches"]["failures"] == 2 and st["launches"]["effective_s"] == 300 * 4 and st["launches"]["next_in_s"] >= 300 * 4 - 5
    assert s.tick(t0 + 301) == []  # the plain interval has passed, the backed-off one has not
    assert s.tick(t0 + 300 * 4 + 5) == ["launches"]
    for _ in range(5):
        s.report("launches", ok=False)
    assert s.status()["entries"][0]["effective_s"] == 300 * MAX_BACKOFF_FACTOR
    s.report("launches", ok=True)
    assert s.status()["entries"][0]["failures"] == 0 and s.status()["entries"][0]["effective_s"] == 300
    s.report("not-scheduled", ok=False)  # ignored


def test_network_jobs_degrade_to_the_cached_product(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from aero_audit.space import launches, spaceweather
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job

    async def boom(*a, **k):
        raise ConnectionError("no route")

    monkeypatch.setattr(spaceweather, "fetch", boom)
    monkeypatch.setattr(launches, "fetch", boom)
    with pytest.raises(RuntimeError, match="nothing is cached"):
        space_jobs.space_weather(Job("j", "space_weather", {}), {})
    (tmp_path / "data/space/spaceweather").mkdir(parents=True)
    (tmp_path / "data/space/spaceweather/swpc_20260915T120000Z.json").write_text((Path(__file__).parent.parent / "data/samples/swpc_scales_sample.json").read_text())
    job = Job("j", "space_weather", {})
    r = space_jobs.space_weather(job, {})
    assert r["degraded"] and r["scales"]["G"] == 4 and any("using cached" in line for line in job.log)
    d = json.loads(Path(r["report"]).read_text())
    assert d["summary"]["degraded"] and "ConnectionError" in d["summary"]["fetch_error"]
    (tmp_path / "data/space/launches").mkdir(parents=True)
    (tmp_path / "data/space/launches/ll2_upcoming_20260910T113000Z.json").write_text((Path(__file__).parent.parent / "data/samples/ll2_launches_sample.json").read_text())
    r = space_jobs.launches(Job("j", "launches", {}), {})
    assert r["degraded"] and r["launches"] == 2
    from aero_audit.web.views import _space_summary

    s = _space_summary()
    feeds = {f["source"]: f for f in s["feeds"]}
    assert feeds["noaa swpc"]["cached"] == 1 and feeds["launch library 2"]["cached"] == 1 and feeds["celestrak elements"]["cached"] == 0
    assert "space_weather" in s["degraded_last_run"]


def test_trend_rows_slope_and_rising_rule():
    rows = [{"recording": f"r{i}", "first_ts": 1_700_000_000 + i * 86400, "flight_hours": 10.0, "violations_per_fh": v, "nmac_per_fh": 0.0} for i, v in enumerate((0.1, 0.2, 0.4))]
    summary, fs = tr.assess_rows(rows)
    assert summary["recordings"] == 3 and summary["span_days"] == 2.0 and summary["slope_violations_per_fh_per_day"] > 0
    assert [f.rule_id for f in fs] == ["DAA-005"] and fs[0].evidence["rates"] == [0.1, 0.2, 0.4]
    flat, ff = tr.assess_rows([dict(r, violations_per_fh=0.3) for r in rows])
    assert ff == [] and flat["slope_violations_per_fh_per_day"] == 0.0
    two, f2 = tr.assess_rows(rows[:2])
    assert f2 == [] and two["recordings"] == 2  # below the minimum count
    assert tr.assess_rows([])[0]["recordings"] == 0


def test_trend_over_the_bundled_recordings_and_study(tmp_path):
    recs = tr.find_recordings("data/samples")
    assert NYC in recs and HUBS in recs
    summary, _ = tr.trend([NYC, HUBS], max_batches=3)
    assert summary["recordings"] == 2 and any(r["flight_hours"] > 0 for r in summary["rows"]) and summary["rows"][0]["first_ts"] <= summary["rows"][1]["first_ts"]  # round-robin hubs see most aircraft once in 3 batches
    from aero_audit.governance import run_study

    rec = run_study("ST-21", tmp_path / "studies", files=[NYC, HUBS], max_batches=3)
    assert rec["result"]["recordings"] == 2 and Path(rec["files"]["md"]).is_file()
    with pytest.raises(RuntimeError, match="no recordings"):
        run_study("ST-21", tmp_path / "studies", recordings_dir=tmp_path / "empty")
