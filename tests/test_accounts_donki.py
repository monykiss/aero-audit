"""Credential probe with an injected transport (no secrets, no network), DONKI parsing and cross-check, watch default with Space-Track."""

import json
import time
from pathlib import Path

from typer.testing import CliRunner

from aero_audit import cli
from aero_audit.integrations import INTEGRATIONS, probe
from aero_audit.space import donki


def test_probe_reports_without_leaking_values(monkeypatch):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASS", raising=False)
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.setenv("NASA_API_KEY", "not-a-real-key-123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_real_456")
    seen = []

    def fake_get(url, headers=None, params=None, auth=None):
        seen.append((url, headers, params))
        return (200, "{}") if "ll.thespacedevs" not in url else (429, "rate limited")

    rows = {r["key"]: r for r in probe(get=fake_get)}
    assert rows["spacetrack"]["ok"] is None and "not configured" in rows["spacetrack"]["detail"]
    assert rows["opensky"]["ok"] is None
    assert rows["nasa_api"]["ok"] and "your key" in rows["nasa_api"]["detail"]
    assert rows["github"]["ok"] and "token" in rows["github"]["detail"]
    assert rows["ll2"]["ok"] is False and "429" in rows["ll2"]["detail"]
    assert rows["swpc"]["ok"] and rows["celestrak"]["ok"]
    dump = json.dumps(rows)
    assert "not-a-real-key" not in dump and "ghp_not_real" not in dump
    assert set(rows) == set(INTEGRATIONS)


def test_probe_never_raises(monkeypatch):
    monkeypatch.delenv("NASA_API_KEY", raising=False)

    def boom(url, headers=None, params=None, auth=None):
        raise ConnectionError("offline")

    rows = {r["key"]: r for r in probe(get=boom)}
    assert rows["swpc"]["ok"] is False and "ConnectionError" in rows["swpc"]["detail"]
    assert "DEMO_KEY" in rows["nasa_api"]["detail"] or rows["nasa_api"]["ok"] is False


def test_donki_parse_and_crosscheck():
    now = time.time()
    iso = lambda dt: time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now - dt))
    rows = [{"messageID": "1", "messageType": "GST", "messageIssueTime": iso(3600), "messageURL": "u", "messageBody": "## Message\n# Geomagnetic storm G3 observed\ndetails"},
            {"messageID": "2", "messageType": "FLR", "messageIssueTime": iso(3 * 86400), "messageBody": "old flare"},
            {"messageID": "3", "messageType": "SEP", "messageIssueTime": iso(7200), "messageBody": ""}]
    notes = donki.parse(rows)
    assert notes[0]["headline"] == "Geomagnetic storm G3 observed" and notes[2]["headline"] == ""
    swx = {"icao_advisory_conditions": {"G": "moderate", "R": "moderate", "S": None}}
    cc = donki.crosscheck(swx, notes, now=now)
    assert cc["recent_notifications"] == 2
    assert cc["effects"]["G"]["agreement"] == "both" and cc["effects"]["G"]["types"] == ["GST"]
    assert cc["effects"]["R"]["agreement"] == "swpc-only"  # the flare is outside the 48 h window
    assert cc["effects"]["S"]["agreement"] == "donki-only"
    quiet = donki.crosscheck({"icao_advisory_conditions": {"G": None, "R": None, "S": None}}, [], now=now)
    assert all(v["agreement"] == "quiet" for v in quiet["effects"].values())
    assert donki.api_key() == ("DEMO_KEY", False) or donki.api_key()[1]


def test_space_weather_job_takes_a_donki_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job

    (tmp_path / "data/samples").mkdir(parents=True)
    root = Path(__file__).parent.parent
    (tmp_path / "data/samples/swpc.json").write_text((root / "data/samples/swpc_scales_sample.json").read_text())
    (tmp_path / "data/samples/donki.json").write_text(json.dumps({"notifications": [{"id": "x", "type": "GST", "issued": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "headline": "h"}]}))
    r = space_jobs.space_weather(Job("j", "space_weather", {}), {"file": "data/samples/swpc.json", "donki": "data/samples/donki.json"})
    d = json.loads(Path(r["report"]).read_text())
    assert d["summary"]["donki"]["effects"]["G"]["agreement"] == "both"


def test_accounts_command_and_env_template():
    r = CliRunner().invoke(cli.app, ["accounts"])
    assert r.exit_code == 0 and "Not configured" in r.output and "spacetrack" in r.output
    env = Path(".env.example").read_text()
    assert "SPACETRACK_USER=" in env and "NASA_API_KEY=" in env and "AERO_SCHEDULE" in env
