"""The 1.0 bar: the three controls that were partial are closed (SDLS per-packet authentication, practised assurance
reviews, apron capacity with measured detector recall), the contract snapshot holds, every control is implemented, and
the seam's time-zone and crew fields parse."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aero_audit import __version__, cli
from aero_audit.governance import contract, publish, reviews
from aero_audit.governance.controls import CONTROLS
from aero_audit.space import sdls
from aero_audit.space.telemetry import audit_telemetry, load_any, load_with_auth, summarize
from aero_audit.vision import (
    detections_from_json,
    evaluate,
    occupancy,
    zone_findings,
    zones_from_json,
)

SAMPLE = Path("data/samples/sdls_packets_sample.json")
KEY = "aero-sdls-demo-key"


def test_sdls_sign_verify_statuses_replay_and_findings():
    key = sdls.key_bytes(KEY)
    assert sdls.key_bytes("00ff" * 8) == bytes.fromhex("00ff" * 8) and sdls.key_bytes("short") == b"short"
    pk = [{"spi": 1, "seq": i, "t_s": float(i), "speed_mps": 10.0 * i, "altitude_km": 0.1 * i} for i in range(1, 6)]
    signed = sdls.sign(pk, key)
    assert all(len(p["mac"]) == 64 for p in signed)
    rows = sdls.verify(signed, {1: key})
    assert [r["status"] for r in rows] == ["verified"] * 5 and not any(r["replay"] for r in rows)
    tampered = [dict(p) for p in signed]
    tampered[2]["altitude_km"] = 99.0
    tampered.append(dict(signed[1]))  # a genuine packet replayed at the end
    tampered.append({k: v for k, v in signed[4].items() if k != "mac"} | {"seq": 9})
    rows = sdls.verify(tampered, {1: key})
    assert [r["status"] for r in rows] == ["verified", "verified", "failed", "verified", "verified", "verified", "unauthenticated"]
    assert rows[5]["replay"] and not rows[1]["replay"]
    fs = sdls.findings(rows, "t")
    assert sorted(f.rule_id for f in fs) == ["SPC-006", "SPC-007", "SPC-008"]
    assert next(f for f in fs if f.rule_id == "SPC-006").severity.value == "high" and next(f for f in fs if f.rule_id == "SPC-007").evidence["unauthenticated"] == 1
    assert [r["status"] for r in sdls.verify(signed, {})] == ["no-key"] * 5
    assert sdls.keys_from_env({"AERO_SDLS_KEY_7": KEY, "AERO_SDLS_KEY_x": "bad", "OTHER": "1"}) == {7: key}
    s = sdls.summary(rows)
    assert s["packets"] == 7 and s["failed"] == 1 and s["replays"] == 1 and s["trusted_share"] == round(5 / 7, 4)


def test_sdls_sample_through_the_telemetry_audit(monkeypatch):
    monkeypatch.setenv("AERO_SDLS_KEY_1", KEY)
    pts, auth, fs = load_with_auth(SAMPLE)
    assert auth["transport"] == "sdls-packets" and auth["failed"] == 1 and auth["replays"] == 1 and auth["unauthenticated"] == 1 and auth["verified"] == auth["packets"] - 2
    assert sorted(f.rule_id for f in fs) == ["SPC-006", "SPC-007", "SPC-008"]
    assert len(load_any(SAMPLE)) == len(pts) == auth["packets"]
    phys = audit_telemetry(pts, "sdls_demo")
    assert {"SPC-001", "SPC-004"} <= {f.rule_id for f in phys}  # the forged speed and the replayed time are implausible on their own
    s = summarize(pts, fs + phys, auth)
    assert s["authentication"]["verified"] == auth["verified"] and "per_packet" not in s["authentication"]
    monkeypatch.delenv("AERO_SDLS_KEY_1")
    _, auth2, fs2 = load_with_auth(SAMPLE)
    assert auth2["no-key"] == auth2["packets"] - 1 and [f.rule_id for f in fs2] == ["SPC-007"]
    _, auth3, fs3 = load_with_auth("data/samples/gps3sv01_telemetry.json")
    assert auth3["transport"] == "plain" and auth3["verified"] == 0 and fs3 == []
    r = CliRunner().invoke(cli.app, ["space", "telemetry-audit", str(SAMPLE), "--out", "reports"], env={"AERO_SDLS_KEY_1": KEY})
    assert r.exit_code == 0 and "authentication: transport sdls-packets" in r.output and "SPC-006" in r.output, r.output


def test_reviews_are_recorded_valid_current_and_render(tmp_path):
    log = reviews.load_log()
    names = {c["component"] for c in log}
    assert names == {r["component"] for r in reviews.status(datetime(2026, 9, 18, tzinfo=UTC))} and all(e["kind"] in reviews.KINDS for e in log)
    rows = reviews.status(datetime(2026, 9, 18, tzinfo=UTC))
    assert rows and not any(r["due"] for r in rows) and all(r["checks_passed"] == r["checks_total"] for r in rows), [(r["component"], r["checks"]) for r in rows if r["checks_passed"] != r["checks_total"]]
    s = reviews.summary(rows)
    assert s["reviewed"] == s["components"] and s["peer_reviews"] == 0 and s["self_reviews"] == s["components"]  # honest: a single maintainer
    later = reviews.status(datetime(2027, 6, 1, tzinfo=UTC))
    assert all(r["due"] for r in later) and reviews.summary(later)["overdue_safety_related"]
    md = reviews.render_markdown(datetime(2026, 9, 18, tzinfo=UTC))
    assert "| Component |" in md and "self-review" in md and "Open actions" in md and "Next due" in md and "days since" not in md.lower()
    bad = tmp_path / "log.json"
    bad.write_text(json.dumps([{"component": "x", "date": "2026-01-01", "kind": "peer-review", "outcome": "nope"}]))
    with pytest.raises(ValueError):
        reviews.load_log(bad)
    r = CliRunner().invoke(cli.app, ["gov", "reviews"])
    assert r.exit_code == 0 and "reviewed" in r.output, r.output


def test_apron_capacity_from_files_with_measured_recall(tmp_path):
    zl = zones_from_json("data/samples/apron_hohn_zones.json")
    truth = detections_from_json("data/samples/apron_hohn_truth.json")
    assert len(truth) == 12 and truth[0].x2 > truth[0].x1 > 0
    occ = occupancy(truth, zl)
    assert occ == {"west stands": 6, "east stands": 6, "hangar apron": 0}
    fs = zone_findings(occ, zl, "apron_hohn.jpg", 0.0)
    assert [f.rule_id for f in fs] == ["OPS-VIS-002"] and fs[0].evidence["zone"] == "hangar apron"
    over = occupancy(truth + truth[:2], zl)
    assert "OPS-VIS-001" in {f.rule_id for f in zone_findings(over, zl, "x", 0.0)}
    det_file = Path("data/samples/apron_hohn_detections_yolov8n.json")
    dets = detections_from_json(det_file)
    ev = evaluate(dets, truth)
    assert ev["truth"] == 12 and 0 < ev["recall"] < 1 and ev["matched"] <= ev["detected"]  # the COCO baseline sees some, not all, of the parked transports
    assert evaluate(truth, truth)["recall"] == 1.0 and evaluate([], truth)["recall"] == 0.0
    r = CliRunner().invoke(cli.app, ["vision", "apron", "data/samples/apron_hohn.jpg", "--zones", "data/samples/apron_hohn_zones.json", "--detections", str(det_file),
                                     "--truth", "data/samples/apron_hohn_truth.json", "--out", str(tmp_path)])
    assert r.exit_code == 0 and "recall" in r.output and list(tmp_path.glob("apron_apron_hohn_*.json")), r.output
    rep = json.loads(next(p for p in tmp_path.glob("apron_apron_hohn_*.json") if not p.name.endswith(".manifest.json")).read_text())
    assert rep["summary"]["evaluation"]["recall"] == ev["recall"]


def test_contract_snapshot_holds_and_detects_removals():
    cur = contract.current()
    assert all(cur[s] for s in contract.SURFACES) and "space tfr" in cur["cli"] and "TFR-001" in cur["rules"] and "GET /api/v1/space" in cur["api"]
    snap = contract.load()
    assert snap and snap["version"] == "1.0.0"
    d = contract.diff(snap, cur)
    assert not d["breaking"] and not any(d["removed"].values())
    broken = {**cur, "rules": [r for r in cur["rules"] if r != "ORB-004"], "cli": cur["cli"][1:]}
    d2 = contract.diff(snap, broken)
    assert d2["breaking"] and d2["removed"]["rules"] == ["ORB-004"] and len(d2["removed"]["cli"]) == 1 and "breaking" in contract.render_markdown(d2)
    assert contract.diff(None, cur)["breaking"] is False
    r = CliRunner().invoke(cli.app, ["gov", "contract", "--check"])
    assert r.exit_code == 0 and "no removals" in r.output, r.output


def test_every_control_implemented_and_publish_gate_at_1_0():
    assert tuple(int(x) for x in __version__.split(".")[:2]) >= (1, 0) and all(c.status == "implemented" for c in CONTROLS.values())
    rows = {r["id"]: r for r in publish.checks()}
    assert rows["PUB-12"]["ok"] and rows["PUB-13"]["ok"], (rows["PUB-12"], rows["PUB-13"])
    assert "Production/Stable" in Path("pyproject.toml").read_text()


def test_tfr_time_zone_and_launch_crew_fields():
    from aero_audit.ingest import tfr
    from aero_audit.space import launches

    from .test_airspace import XNOTAM

    utc = tfr.parse_detail(XNOTAM)
    local = tfr.parse_detail(XNOTAM.replace("<codeTimeZone>UTC</codeTimeZone>", "<codeTimeZone>EDT</codeTimeZone>"))
    assert local["time_zone"] == "EDT" and not local["time_zone_assumed_utc"] and local["effective_ts"] - utc["effective_ts"] == 4 * 3600
    odd = tfr.parse_detail(XNOTAM.replace("<codeTimeZone>UTC</codeTimeZone>", "<codeTimeZone>XYZ</codeTimeZone>"))
    assert odd["time_zone_assumed_utc"] and odd["effective_ts"] == utc["effective_ts"]
    raw = {"results": [{"id": "c1", "name": "Crew-99", "mission": {"type": "Human Exploration", "orbit": {"abbrev": "LEO"}}, "rocket": {"spacecraft_stage": {"launch_crew": [{"role": "Commander"}]}},
                        "pad": {"latitude": "28.6", "longitude": "-80.6", "location": {"name": "KSC, FL, USA"}}, "status": {"abbrev": "Go"}},
                       {"id": "u1", "name": "Cargo", "mission": {"type": "Resupply"}, "pad": {}, "status": {}}]}
    rows = launches.parse(raw)
    assert rows[0]["crewed"] and rows[0]["orbit"] == "LEO" and rows[0]["mission_type"] == "Human Exploration" and not rows[1]["crewed"]
