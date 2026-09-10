"""The local app must not be reachable from other web pages or other machines by accident."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from aero_audit.synthetic import generate
from aero_audit.web.app import App, make_handler
from aero_audit.web.security import Guard, safe_path, safe_url


def _srv(guard=None):
    app = App(guard)
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


def test_guard_modes():
    assert Guard().mode == "loopback"
    assert Guard("0.0.0.0", token="s3cret").mode == "token"
    assert Guard("0.0.0.0", allow_unauthenticated=True).mode == "open"
    with pytest.raises(ValueError):
        Guard("0.0.0.0")
    g = Guard()
    assert g.host_ok("localhost:8787") and g.host_ok("127.0.0.1:8787") and g.host_ok("[::1]:8787")
    assert not g.host_ok("evil.example:8787") and not g.host_ok("10.0.0.5")
    assert Guard("0.0.0.0", allow_unauthenticated=True, allowed_hosts=["lab.local"]).host_ok("lab.local:8787")
    assert Guard.origin_ok("http://127.0.0.1:8787", "127.0.0.1:8787")
    assert not Guard.origin_ok("http://attacker.example", "127.0.0.1:8787") and not Guard.origin_ok("null", "127.0.0.1:8787")


def test_host_csrf_origin_and_headers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, httpd, port = _srv()
    try:
        # DNS rebinding: foreign Host header is refused even on loopback
        status, _, body = _req(port, "/api/v1/app", headers={"Host": "attacker.example"})
        assert status == 403 and b"host" in body
        # cross-site simple POST (no token) is refused; wrong token too
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json"})
        assert status == 403
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": "nope"})
        assert status == 403
        # non-JSON content type (a form post from another origin) is refused
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "text/plain", "X-Aero-Token": app.guard.csrf})
        assert status == 415
        # foreign Origin / Sec-Fetch-Site refused even with the right token
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf, "Origin": "http://evil.example"})
        assert status == 403
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf, "Sec-Fetch-Site": "cross-site"})
        assert status == 403
        # the page's own request succeeds
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf, "Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"})
        assert status == 200
        # the token is handed to the page on /app and every response carries hardening headers
        status, headers, body = _req(port, "/api/v1/app")
        info = json.loads(body)
        assert status == 200 and info["security"]["mode"] == "loopback" and info["security"]["csrf"] == app.guard.csrf
        assert headers["X-Content-Type-Options"] == "nosniff" and headers["X-Frame-Options"] == "DENY"
        assert "script-src 'self'" in headers["Content-Security-Policy"] and "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["Server"].startswith("aero-audit") and "Python" not in headers["Server"]
        # bad JSON and non-object bodies are 400, not 500
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/source/stop", data=b"{not json", method="POST",
                                     headers={"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=10)
        assert ei.value.code == 400
        # POST outside the API is refused
        status, _, _ = _req(port, "/static/app.js", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf})
        assert status == 405
    finally:
        httpd.shutdown()


def test_token_mode_requires_header_on_every_api_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, httpd, port = _srv(Guard("0.0.0.0", token="shared-secret"))
    try:
        status, _, _ = _req(port, "/api/v1/app")
        assert status == 401
        status, _, body = _req(port, "/api/v1/app", headers={"X-Aero-Token": "shared-secret"})
        assert status == 200 and json.loads(body)["security"]["csrf"] is None  # never leaks the shared secret
        status, _, _ = _req(port, "/", headers={"Host": "lab.example:8787"})
        assert status == 200  # the shell page is public; the API is not
        status, _, _ = _req(port, "/api/v1/source/stop", "POST", {}, {"Content-Type": "application/json", "X-Aero-Token": "shared-secret"})
        assert status == 200
        assert any(e["action"] == "request.denied" for e in app.audit.entries())
    finally:
        httpd.shutdown()


def test_paths_are_confined(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/recordings").mkdir(parents=True)
    (tmp_path / "data/samples").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_test.jsonl", n_aircraft=10, polls=6, seed=1)
    secret = tmp_path / "secret.jsonl"
    secret.write_text("{}\n")
    assert safe_path(rec, ["data/recordings", "data/samples"], (".jsonl", ".jsonl.gz")) == Path("data/recordings/synthetic_test.jsonl")
    with pytest.raises(PermissionError):
        safe_path(secret, ["data/recordings"], (".jsonl",))
    with pytest.raises(PermissionError):
        safe_path("data/recordings/../../secret.jsonl", ["data/recordings"], (".jsonl",))
    with pytest.raises(PermissionError):
        safe_path("/etc/passwd", ["data/recordings"])
    with pytest.raises(FileNotFoundError):
        safe_path("data/recordings/missing.jsonl", ["data/recordings"], (".jsonl",))
    with pytest.raises(PermissionError):
        safe_path("data/recordings", ["data/recordings"])  # the root itself is not a file
    assert safe_url("") == "" and safe_url("https://hooks.example/x") == "https://hooks.example/x"
    for bad in ("file:///etc/passwd", "ftp://x", "https://user:pw@host/", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            safe_url(bad)

    app, httpd, port = _srv()
    try:
        hdr = {"Content-Type": "application/json", "X-Aero-Token": app.guard.csrf}
        status, _, body = _req(port, "/api/v1/source/start", "POST", {"mode": "replay", "recording": str(secret)}, hdr)
        assert status == 400 and b"outside" in body
        status, _, _ = _req(port, "/api/v1/source/start", "POST", {"mode": "replay", "recording": "data/recordings/nope.jsonl"}, hdr)
        assert status == 404
        status, _, _ = _req(port, "/api/v1/source/start", "POST", {"mode": "replay", "recording": str(rec), "speed": 100}, hdr)
        assert status == 200
        # settings: paths and URLs validated, unknown keys dropped
        status, _, body = _req(port, "/api/v1/settings", "POST", {"app": {"model": "/tmp/evil.joblib"}}, hdr)
        assert status == 500 and b"outside" in body
        status, _, body = _req(port, "/api/v1/settings", "POST", {"app": {"alert_webhook": "file:///etc/passwd"}}, hdr)
        assert status == 500
        status, _, body = _req(port, "/api/v1/settings", "POST", {"app": {"model": "models/other.joblib", "retention_days": 99999, "bogus": 1}}, hdr)
        s = json.loads(body)["app"]
        assert status == 200 and s["model"] == "models/other.joblib" and s["retention_days"] == 3650 and "bogus" not in s
        # docs endpoint never leaves docs/ or README.md
        assert _req(port, "/api/v1/docs/..%2F..%2Fetc%2Fpasswd")[0] == 404
        assert _req(port, "/api/v1/docs/%2Fetc%2FREADME.md")[0] == 404
        # audit log recorded the refused start
        assert any(e["action"] == "source.start.refused" for e in app.audit.entries())
    finally:
        app.sources.stop()
        httpd.shutdown()
