"""Launch-window capture: due windows, one capture per launch, the recording and the joins written afterwards, the job
and the CLI; all with a fake provider, no network."""

import json
from pathlib import Path

from typer.testing import CliRunner

from aero_audit import cli
from aero_audit.models import Batch, StateVector
from aero_audit.space import capture

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_789_038_000.0  # 2026-09-10T11:00:00Z


def _launches(now: float) -> dict:
    iso = lambda t: __import__("datetime").datetime.fromtimestamp(t, __import__("datetime").UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"launches": [
        {"id": "open-1", "name": "Open Window | Pad A", "pad": "Pad A", "location": "Wallops, VA, USA", "pad_lat": 37.83, "pad_lon": -75.49, "status": "Go", "net": iso(now + 600), "window_start": iso(now - 600), "window_end": iso(now + 1800)},
        {"id": "later-2", "name": "Tomorrow | Pad B", "pad": "Pad B", "location": "KSC, FL, USA", "pad_lat": 28.6, "pad_lon": -80.6, "status": "Go", "net": iso(now + 86400), "window_start": iso(now + 86400), "window_end": iso(now + 90000)},
        {"id": "scrub-3", "name": "Scrubbed | Pad C", "pad": "Pad C", "location": "VSFB, CA, USA", "pad_lat": 34.6, "pad_lon": -120.6, "status": "Scrubbed", "net": iso(now), "window_start": iso(now - 60), "window_end": iso(now + 60)},
        {"id": "nopad-4", "name": "No pad", "status": "Go", "net": iso(now)},
    ]}


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, region) -> Batch:
        self.calls += 1
        ts = T0 + self.calls * 10.0
        return Batch(ts=ts, provider="adsblol", region=region.key, states=[StateVector(icao24=f"c{i:05x}", ts=ts, source="synthetic", lat=region.lat + i * 0.01, lon=region.lon, baro_alt_ft=5000.0 + i) for i in range(4)])


def test_due_pick_and_region():
    ll = _launches(T0)["launches"]
    d = capture.due(ll, T0)
    assert [r["id"] for r in d] == ["open-1"]  # tomorrow is outside the lead, the scrub is skipped, no pad is skipped
    assert [r["id"] for r in capture.due(ll, T0 + 86400 - 3600)] == ["later-2"]
    reg = capture.region_for(ll[0], 500.0)
    assert reg.key == "launch-open-1" and reg.radius_nm == 250.0 and reg.lat == 37.83
    state = {"open-1": {"segments": [{"ended_ts": T0 + 1800 + 3600}]}}
    assert capture.pick(ll, state, T0) is None  # already captured through the tail
    assert capture.pick(ll, {"open-1": {"segments": [{"ended_ts": T0}]}}, T0)["id"] == "open-1"  # a cut segment gets another
    assert capture.pick(ll, {"open-1": {"running": True}}, T0) is None
    assert capture.window(ll[3]) is not None and capture.slug({"name": "Falcon 9 | X"}) == "falcon-9-x"


def test_run_records_joins_and_marks_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/samples").mkdir(parents=True)
    (tmp_path / "data/airspace").mkdir(parents=True)
    (tmp_path / "data/airspace/tfr_20260910T113000Z.json").write_bytes((ROOT / "data/samples/tfr_sample.json").read_bytes())
    prov = FakeProvider()
    dry = capture.run(now=T0, launches_payload=_launches(T0), provider_factory=lambda n: prov, dry_run=True)
    assert dry["picked"] == "Open Window | Pad A" and len(dry["due"]) == 1 and prov.calls == 0 and not capture.load_state()
    res = capture.run(now=T0, launches_payload=_launches(T0), provider_factory=lambda n: prov, interval_s=0.0, max_batches=3, out_dir="reports")
    assert res["batches"] == 3 and res["state_vectors"] == 12 and Path(res["recording"]).is_file() and res["region"]["radius_nm"] == 100.0
    assert set(res["reports"]) == {"launches", "tfr", "mission"} and all(Path(p).is_file() for p in res["reports"].values())
    state = capture.load_state()
    seg = state["open-1"]["segments"][0]
    assert not state["open-1"]["running"] and seg["batches"] == 3 and seg["reports"]["mission"].startswith("reports/mission_open-1")
    lj = json.loads(Path(res["reports"]["launches"]).read_text())
    assert lj["summary"]["rows"][0]["aircraft_inside_during_window"] == 4  # every fake aircraft sits on the pad
    again = capture.run(now=T0 + 1800 + 3600 + 5, launches_payload=_launches(T0), provider_factory=lambda n: prov, max_batches=1)
    assert again["picked"] is None and prov.calls == 3  # the window and its tail are over: nothing is recorded twice
    nothing = capture.run(now=T0 + 7 * 86400, launches_payload=_launches(T0), provider_factory=lambda n: prov)
    assert nothing["due"] == [] and nothing["picked"] is None


def test_job_and_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/samples").mkdir(parents=True)
    lf = tmp_path / "data/samples/launches.json"
    lf.write_text(json.dumps(_launches(T0)))
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job

    monkeypatch.setattr("aero_audit.ingest.make_provider", lambda name: FakeProvider())
    res = space_jobs.launch_capture(Job("j", "launch_capture", {}), {"file": "data/samples/launches.json", "dry_run": True})
    assert res["dry_run"] and res["picked"] is None  # T0 is in the past by now: nothing due at wall-clock time
    r = CliRunner().invoke(cli.app, ["space", "launch-capture", "--file", "data/samples/launches.json", "--dry-run"])
    assert r.exit_code == 0 and "due now: 0" in r.output, r.output
    import inspect

    app_cmd = next(c for c in cli.app.registered_commands if (c.name or c.callback.__name__) == "app")
    assert {"live", "provider", "radius", "interval", "demo"} <= set(inspect.signature(app_cmd.callback).parameters)  # `aero app --live REGION`
