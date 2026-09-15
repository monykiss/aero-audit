"""API contract completeness, evidence bundles, POST rate limiting, orderly shutdown."""

import json
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

from aero_audit.evidence import build_bundle, verify_bundle
from aero_audit.synthetic import generate
from aero_audit.web.app import App, make_handler, router, shutdown
from aero_audit.web.openapi import SUMMARIES, build_spec, render_markdown
from aero_audit.web.security import Guard, RateLimiter


def _srv():
    app = App()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return app, httpd, httpd.server_address[1]


def _req(port, path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_every_route_is_documented_and_spec_is_served(tmp_path, monkeypatch):
    spec = build_spec(router)
    assert spec["openapi"] == "3.1.0" and "/api/v1/state" in spec["paths"] and "/healthz" in spec["paths"]
    routed = {(r.method, r.raw) for r in router.routes}
    assert routed <= set(SUMMARIES)
    post = spec["paths"]["/api/v1/source/start"]["post"]
    assert post["security"] == [{"AeroToken": []}] and "429" in post["responses"] and post["requestBody"]["required"]
    assert spec["paths"]["/api/v1/aircraft/{icao}"]["get"]["parameters"][0] == {"name": "icao", "in": "path", "required": True, "schema": {"type": "string"}}
    md = render_markdown(spec)
    assert "| GET | `/api/v1/observability` |" in md
    monkeypatch.chdir(tmp_path)
    _app, httpd, port = _srv()
    try:
        status, _headers, body = _req(port, "/api/v1/openapi.json")
        assert status == 200 and json.loads(body)["info"]["title"].startswith("aero-audit")
    finally:
        httpd.shutdown()


def test_rate_limiter_and_429(tmp_path, monkeypatch):
    rl = RateLimiter(capacity=3, refill_per_s=0.0)
    assert [rl.allow("a") for _ in range(4)] == [True, True, True, False] and rl.allow("b")
    monkeypatch.setenv("AERO_POST_RATE_LIMIT", "5")
    monkeypatch.chdir(tmp_path)
    app, httpd, port = _srv()
    try:
        hdr = {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf}
        codes = [_req(port, "/api/v1/source/stop", "POST", {}, hdr)[0] for _ in range(7)]
        assert codes[:5] == [200] * 5 and codes[5] == 429
        status, headers, _ = _req(port, "/api/v1/source/stop", "POST", {}, hdr)
        assert status == 429 and headers.get("Retry-After") == "2"
        assert _req(port, "/api/v1/app")[0] == 200  # GETs are never limited
    finally:
        httpd.shutdown()


def test_evidence_bundle_roundtrip_and_tamper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_b.jsonl", n_aircraft=12, polls=6, seed=3)
    app = App()
    app.settings["alert_webhook"] = "https://hooks.example/secret-path"
    from aero_audit.web.sources import save_settings

    save_settings(app.settings)
    from aero_audit.audit import AuditEngine, write_reports
    from aero_audit.ingest.replay import iter_recording

    eng = AuditEngine()
    for b in iter_recording(rec):
        eng.process_batch(b)
    write_reports(eng, tmp_path / "reports", "t")
    (tmp_path / "docs/generated").mkdir(parents=True)
    (tmp_path / "docs/generated/RULES.md").write_text("# rules\n")
    z = build_bundle(tmp_path / "reports" / "ev.zip")
    r = verify_bundle(z)
    assert r["ok"] and r["checked"] >= 5 and r["audit_chain"]["ok"] and not r["extra"]
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert "BUNDLE.json" in names and "data/app/audit.jsonl" in names and "data/app/settings.redacted.json" in names
        assert any(n.endswith(".manifest.json") for n in names) and "docs/generated/RULES.md" in names
        assert "secret-path" not in zf.read("data/app/settings.redacted.json").decode()
        m = json.loads(zf.read("BUNDLE.json"))
        assert m["format"] == "aero-audit-evidence/1" and m["count"] == r["checked"]
    # tamper: rewrite one member
    tampered = tmp_path / "reports" / "ev2.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(tampered, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            if n == "data/app/audit.jsonl":
                data = data + b'{"forged": true}\n'
            dst.writestr(n, data)
    r2 = verify_bundle(tampered)
    assert not r2["ok"] and r2["bad"] == ["data/app/audit.jsonl"]


def test_shutdown_records_and_stops(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_s.jsonl", n_aircraft=10, polls=5, seed=1)
    app, httpd, port = _srv()
    app.sources.start_replay(rec, speed=200, demo=True)
    app.tour.start()
    shutdown(app, httpd, "SIGTERM")
    import time

    assert app.sources.state is None and not app.tour.running
    assert app.audit.entries(limit=1)[0]["action"] == "app.stop" and app.audit.entries(limit=1)[0]["details"]["reason"] == "SIGTERM"
    closed = False
    for _ in range(30):  # serve_forever polls every 0.5 s; the listener closes right after it exits
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
        except urllib.error.URLError:
            closed = True
            break
        except OSError:
            pass
        time.sleep(0.2)
    assert closed


def test_guard_rate_default_from_env(monkeypatch):
    monkeypatch.setenv("AERO_POST_RATE_LIMIT", "7")
    assert Guard().rate.capacity == 7
