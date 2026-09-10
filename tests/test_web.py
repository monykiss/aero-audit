import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from aero_audit.synthetic import generate
from aero_audit.web.app import App, make_handler


def _srv():
    app = App()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return app, httpd, httpd.server_address[1]


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        body = r.read()
        ctype = r.headers.get("Content-Type", "")
        return r.status, (json.loads(body) if "json" in ctype else body.decode())


def _post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def test_app_pages_sources_findings_and_jobs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolated data/, reports/, models/
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_test.jsonl", n_aircraft=20, polls=12, seed=3)
    app, httpd, port = _srv()
    try:
        assert _get(port, "/")[1].count("aero-audit") >= 1
        assert _get(port, "/static/app.js")[0] == 200
        status, info = _get(port, "/api/v1/app")
        assert status == 200 and info["source"]["active"] is False and info["recordings"] == 1
        status, recs = _get(port, "/api/v1/recordings")
        assert recs[0]["aircraft"] == 20 and recs[0]["special"] is True
        assert {r["key"] for r in _get(port, "/api/v1/regions")[1]} >= {"nyc", "conus", "usa-hubs"}
        # start a replay source, wait for polls
        status, r = _post(port, "/api/v1/source/start", {"mode": "replay", "recording": str(rec), "speed": 200, "demo": True})
        assert status == 200 and r["source"]["active"] and r["source"]["mode"] == "replay"
        for _ in range(50):
            time.sleep(0.1)
            if app.sources.state and app.sources.state.batches >= 4:
                break
        status, s = _get(port, "/api/v1/state")
        assert s["kpis"]["tracked"] == 20 and s["batches"] >= 4
        status, f = _get(port, "/api/v1/findings?limit=10")
        assert status == 200 and "items" in f
        status, csvtxt = _get(port, "/api/v1/findings.csv")
        assert csvtxt.startswith("severity,rule")
        status, inj = _post(port, "/api/v1/inject", {"kind": "teleport"})
        assert inj["kind"] == "teleport" and inj["icao24"]
        for path in ("/api/v1/risk", "/api/v1/threats", "/api/v1/impact", "/api/v1/rules", "/api/v1/playbooks", "/api/v1/settings", "/api/v1/docs", "/api/v1/reports", "/api/v1/jobs"):
            assert _get(port, path)[0] == 200, path
        # a job: audit the session -> report files under tmp reports/
        status, job = _post(port, "/api/v1/jobs", {"type": "audit_session", "params": {"name": "t"}})
        for _ in range(100):
            time.sleep(0.1)
            status, j = _get(port, f"/api/v1/jobs/{job['id']}")
            if j["status"] in ("done", "failed"):
                break
        assert j["status"] == "done", j
        assert (tmp_path / j["result"]["html"]).exists()
        assert any(rp["name"] == j["result"]["name"] for rp in _get(port, "/api/v1/reports")[1])
        # settings: app + tunables write aero.toml and apply
        status, raw = _get(port, "/api/v1/settings")
        assert "Infinity" not in json.dumps(raw) and any(t["key"] == "BANDS" and not t["editable"] for t in raw["tunables"])
        status, sv = _post(port, "/api/v1/settings", {"app": {"demo": False, "retention_days": 7}, "tunables": {"rules": {"MAX_PLAUSIBLE_GS_KT": 800.0}}})
        assert sv["app"]["demo"] is False and (tmp_path / "aero.toml").exists()
        assert any(t["key"] == "MAX_PLAUSIBLE_GS_KT" and t["value"] == 800.0 and t["overridden"] for t in sv["tunables"])
        assert _post(port, "/api/v1/source/stop", {})[0] == 200
        assert _get(port, "/api/v1/app")[1]["source"]["active"] is False
    finally:
        app.sources.stop()
        httpd.shutdown()
        from aero_audit import tuning
        from aero_audit.audit import rules
        rules.MAX_PLAUSIBLE_GS_KT = 750.0
        tuning._applied.clear()


def test_router_matches_params():
    from aero_audit.web.router import Router

    r = Router()
    r.add("GET", "/api/v1/aircraft/{icao}", lambda app, req: req)
    _, params = r.match("GET", "/api/v1/aircraft/abc123")
    assert params == {"icao": "abc123"} and r.match("POST", "/api/v1/aircraft/abc123") is None


def test_ecosystem_flights_airports_operators_and_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_eco.jsonl", n_aircraft=25, polls=10, seed=5)
    app, httpd, port = _srv()
    try:
        _post(port, "/api/v1/source/start", {"mode": "replay", "recording": str(rec), "speed": 200, "demo": True})
        for _ in range(50):
            time.sleep(0.1)
            if app.sources.state and app.sources.state.batches >= 3:
                break
        status, fl = _get(port, "/api/v1/flights?limit=5")
        assert status == 200 and fl["total"] == 25 and {"operator", "phase", "type_cat"} <= set(fl["items"][0])
        assert "phases" in fl["facets"] and len(fl["items"]) == 5
        status, csvtxt = _get(port, "/api/v1/flights.csv?phase=cruise")
        assert csvtxt.startswith("callsign,icao24")
        status, eco = _get(port, "/api/v1/ecosystem")
        assert status == 200 and "phases" in eco and eco["operators"]
        status, ap = _get(port, "/api/v1/airports")
        assert status == 200 and ap["items"] and {"nearby", "departing", "faa", "elev_ft"} <= set(ap["items"][0])
        status, one = _get(port, "/api/v1/airports/KJFK")
        assert status == 200 and one["airport"]["iata"] == "JFK" and "flights" in one
        status, ops = _get(port, "/api/v1/operators")
        assert status == 200 and ops["items"] and "compliance" in ops["items"][0]
        _post(port, "/api/v1/inject", {"kind": "flood"})
        status, log = _get(port, "/api/v1/audit")
        actions = [e["action"] for e in log["items"]]
        assert "inject" in actions and "source.start" in actions and "app.start" in actions
        assert _get(port, "/api/v1/audit.csv")[1].startswith("time,actor,action")
        assert (tmp_path / "data/app/audit.jsonl").exists()
    finally:
        app.sources.stop()
        httpd.shutdown()
