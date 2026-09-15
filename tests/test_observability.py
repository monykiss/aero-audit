"""Metrics registry, Prometheus exposition, structured logs with request ids, probes, and the observability API."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from aero_audit import observability as obs
from aero_audit.synthetic import generate
from aero_audit.web.app import App, make_handler
from aero_audit.web.security import Guard


def _srv(guard=None):
    app = App(guard)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return app, httpd, httpd.server_address[1]


def _get(port, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_registry_counters_gauges_histograms_and_exposition():
    r = obs.Registry()
    r.describe("t_requests_total", "requests")
    r.describe("t_seconds", "latency", (0.1, 1.0))
    r.inc("t_requests_total", route="/a", status="200")
    r.inc("t_requests_total", route="/a", status="200")
    r.inc("t_requests_total", 3, route="/b", status="500")
    r.set("t_gauge", 4.5, k="v")
    for v in (0.05, 0.5, 2.0):
        r.observe("t_seconds", v, route="/a")
    assert r.get_counter("t_requests_total", route="/a", status="200") == 2 and r.counter_total("t_requests_total") == 5
    assert r.quantile("t_seconds", 0.5, route="/a") == 0.5
    text = r.render_prometheus()
    assert '# TYPE t_requests_total counter' in text and 't_requests_total{route="/a",status="200"} 2' in text
    assert 't_gauge{k="v"} 4.5' in text and '# TYPE t_seconds histogram' in text
    assert 't_seconds_bucket{route="/a",le="0.1"} 1' in text and 't_seconds_bucket{route="/a",le="+Inf"} 3' in text
    assert 't_seconds_count{route="/a"} 3' in text and 't_seconds_sum{route="/a"} 2.55' in text
    snap = r.snapshot()
    assert snap["histograms"]["t_seconds"][0]["count"] == 3 and snap["histograms"]["t_seconds"][0]["p95"] == 2.0
    # label values are escaped
    r.inc("t_requests_total", route='x"y\\z', status="200")
    assert 'route="x\\"y\\\\z"' in r.render_prometheus()


def test_route_class_bounds_cardinality():
    assert obs.route_class("/api/v1/jobs/abc123") == "/api/v1/jobs/{id}"
    assert obs.route_class("/api/v1/aircraft/a1b2c3?x=1") == "/api/v1/aircraft/{id}"
    assert obs.route_class("/static/vendor/leaflet.js") == "/static/*" and obs.route_class("/api/v1/state") == "/api/v1/state"


def test_structured_logs_carry_request_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "LOG_FILE", tmp_path / "app.jsonl")
    monkeypatch.setattr(obs, "_logger", None)
    rid = obs.bind_request("req-123", "00-abc-def-01")
    assert rid == "req-123"
    obs.log_event("unit.test", answer=42)
    obs.clear_request()
    obs.log_event("unit.other", "warning")
    lines = obs.tail_logs(10, path=tmp_path / "app.jsonl")
    assert lines[0]["event"] == "unit.other" and lines[0]["level"] == "warning" and "request_id" not in lines[0]
    assert lines[1]["event"] == "unit.test" and lines[1]["request_id"] == "req-123" and lines[1]["traceparent"] == "00-abc-def-01" and lines[1]["answer"] == 42
    assert obs.tail_logs(10, level="warning", path=tmp_path / "app.jsonl")[0]["event"] == "unit.other"
    assert obs.tail_logs(10, event="unit.te", path=tmp_path / "app.jsonl")[0]["event"] == "unit.test"


def test_probes_metrics_and_observability_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(obs, "LOG_FILE", tmp_path / "logs" / "app.jsonl")
    monkeypatch.setattr(obs, "_logger", None)
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_obs.jsonl", n_aircraft=15, polls=6, seed=9)
    obs.METRICS.reset()  # the registry is process-global; other tests have already counted requests
    app, httpd, port = _srv()
    try:
        status, headers, body = _get(port, "/healthz")
        assert status == 200 and json.loads(body)["status"] == "ok" and len(headers["X-Request-Id"]) >= 8
        status, headers, _ = _get(port, "/api/v1/app", {"X-Request-Id": "trace-me"})
        assert status == 200 and headers["X-Request-Id"] == "trace-me"
        status, _, body = _get(port, "/readyz")
        ready = json.loads(body)
        assert status == 200 and ready["status"] == "ready" and ready["checks"]["audit_chain"]["ok"] and "source" not in ready["checks"]
        # a running replay is instrumented
        app.sources.start_replay(rec, speed=500, demo=False)
        import time

        for _ in range(60):
            time.sleep(0.05)
            if app.sources.state and app.sources.state.batches >= 3:
                break
        status, _, body = _get(port, "/metrics")
        text = body.decode()
        assert status == 200 and "aero_ingest_batches_total{" in text and "aero_engine_batch_seconds_bucket" in text
        assert 'aero_http_requests_total{method="GET",route="/healthz",status="200"} 1' in text
        assert 'aero_build_info{version=' in text and "aero_process_uptime_seconds" in text
        status, _, body = _get(port, "/api/v1/observability")
        o = json.loads(body)
        assert status == 200 and o["kpis"]["ingest_batches"] >= 3 and o["kpis"]["ingest_states"] > 0 and o["health"]["status"] == "ok"
        status, _, body = _get(port, "/api/v1/logs?limit=50&event=ingest.batch")
        logs = json.loads(body)["items"]
        assert logs and logs[0]["event"] == "ingest.batch" and logs[0]["states"] == 15 and "engine_ms" in logs[0]
        # a refused request is counted and logged
        _get(port, "/api/v1/app", {"Host": "evil.example"})
        status, _, body = _get(port, "/metrics")
        assert 'aero_http_denied_total{status="403"} 1' in body.decode()
        assert any(e["event"] == "http.denied" for e in obs.tail_logs(50, path=tmp_path / "logs" / "app.jsonl"))
        # audit entries are counted
        assert obs.METRICS.counter_total("aero_audit_entries_total") >= 1
    finally:
        app.sources.stop()
        httpd.shutdown()


def test_metrics_need_the_token_in_remote_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _app, httpd, port = _srv(Guard("0.0.0.0", token="s3cret"))
    try:
        assert _get(port, "/metrics")[0] == 401
        assert _get(port, "/metrics", {"X-Aero-Token": "s3cret"})[0] == 200
        assert _get(port, "/healthz")[0] == 200  # liveness stays open for probes
    finally:
        httpd.shutdown()
