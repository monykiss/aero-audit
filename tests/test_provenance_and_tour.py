"""Reports carry provenance and a manifest; the tour and gz replay behave."""

import gzip
import json
import shutil
import time

from aero_audit.audit import AuditEngine, write_reports
from aero_audit.ingest.replay import iter_recording, recording_stem
from aero_audit.provenance import build, describe_source, verify_manifest
from aero_audit.synthetic import generate
from aero_audit.web.sources import build_engine
from aero_audit.web.state import LiveState
from aero_audit.web.tour import DemoTour, Step


def test_reports_have_provenance_and_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = generate(tmp_path / "synthetic.jsonl", n_aircraft=15, polls=10, seed=4)
    eng = AuditEngine()
    for b in iter_recording(rec):
        eng.process_batch(b)
    src = describe_source(recording=rec)
    assert src["kind"] == "recording" and len(src["sha256"]) == 64
    jp, mp, hp = write_reports(eng, tmp_path / "reports", "t", source=src)
    payload = json.loads(jp.read_text())
    prov = payload["provenance"]
    assert prov["tool"] == "aero-audit" and prov["source"]["sha256"] == src["sha256"] and prov["model"] is None
    assert "## Provenance" in mp.read_text() and "Provenance" in hp.read_text()
    manifest = jp.parent / f"{jp.stem}.manifest.json"
    assert manifest.is_file()
    r = verify_manifest(manifest)
    assert r["ok"] and set(r["files"]) == {"json", "md", "html"}
    hp.write_text(hp.read_text() + "<!-- edited -->")
    r = verify_manifest(manifest)
    assert not r["ok"] and not r["files"]["html"]["ok"] and r["files"]["json"]["ok"]
    p = build(eng)
    assert p["window"]["unique_aircraft"] == 15 and isinstance(p["rules_engaged"], list)


def test_gz_recordings_replay_and_stems(tmp_path):
    rec = generate(tmp_path / "adsblol_nyc_x.jsonl", n_aircraft=12, polls=3, seed=1)
    gz = tmp_path / "adsblol_nyc_x.jsonl.gz"
    with open(rec, "rb") as fin, gzip.open(gz, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    plain = list(iter_recording(rec))
    packed = list(iter_recording(gz))
    assert len(plain) == len(packed) == 3 and packed[0].states[0].icao24 == plain[0].states[0].icao24
    assert recording_stem(gz) == "adsblol_nyc_x" == recording_stem(rec)


def test_tour_injects_on_schedule_and_skips_without_demo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = generate(tmp_path / "synthetic.jsonl", n_aircraft=30, polls=6, seed=5)
    state = LiveState(build_engine({"model": "", "watchlist": "", "alert_log": "", "alert_webhook": ""}), "replay", "x", "nyc", demo=True)
    for b in iter_recording(rec):
        state.ingest(b)
    seen = []
    tour = DemoTour(lambda: state, on_inject=lambda k, i, n, narr: seen.append(k),
                    script=(Step(0.05, "flood", 2, "n1"), Step(0.05, "teleport", 3, "n2")))
    assert tour.status()["running"] is False and tour.status()["steps"] == 2
    tour.start()
    for _ in range(60):
        time.sleep(0.05)
        if tour.loops >= 1:
            break
    tour.stop()
    assert seen[:2] == ["flood", "teleport"] and state.injections
    st = tour.status()
    assert st["running"] is False and st["last"]["narration"] in ("n1", "n2")
    # no demo-enabled source: steps are skipped, nothing injected
    state.demo = False
    seen.clear()
    tour2 = DemoTour(lambda: state, on_inject=lambda *a: seen.append(a), script=(Step(0.02, "flood", 2, "n"),))
    tour2.start()
    time.sleep(0.2)
    tour2.stop()
    assert not seen and tour2.last and "skipped" in tour2.last


def test_targeted_injection_survives_round_robin(tmp_path, monkeypatch):
    """A teleport aimed at an aircraft in region A must still apply when A comes round again."""
    monkeypatch.chdir(tmp_path)
    rec = generate(tmp_path / "synthetic.jsonl", n_aircraft=30, polls=8, seed=6)
    batches = list(iter_recording(rec))
    state = LiveState(build_engine({"model": "", "watchlist": "", "alert_log": "", "alert_webhook": ""}), "replay", "x", "nyc", demo=True)
    state.ingest(batches[0])
    inj = state.inject("teleport", None, 2)
    target = inj.icao24
    assert target
    other = batches[1].model_copy(update={"region": "other", "states": [s for s in batches[1].states if s.icao24 != target]})
    state.ingest(other)  # target absent: the injection must not be consumed
    assert state.injections and state.injections[0].remaining == 2 and state.injections[0].idle == 1
    state.ingest(batches[2])  # target present: applied and counted
    assert not state.injections or state.injections[0].remaining == 1
