"""Observability without dependencies: metrics (Prometheus exposition), structured JSON logs with
request correlation, and health/readiness answers. One module, imported everywhere something
happens, so the whole pipeline is measurable from the outside.

- ``METRICS``: thread-safe registry of counters, gauges and histograms with labels;
  ``render_prometheus()`` emits the text exposition format, ``snapshot()`` a JSON view.
- ``log_event(event, **fields)``: one JSON line per event to ``logs/app.jsonl`` (rotating) and a
  short text line to stderr when ``AERO_LOG_STDERR=1``; ``request_id`` and W3C ``traceparent`` are
  propagated from HTTP headers so an external tracer can join our logs to its spans.
- ``health()`` / ``readiness()``: liveness is cheap and always answers; readiness checks the things
  a scrape or a load balancer should care about (writable state, static assets, audit chain,
  model registry match, a source producing data if one is expected).

Nothing here blocks: histogram updates are O(buckets), logging is buffered by the stdlib handler.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import __version__

LOG_FILE = Path(os.getenv("AERO_LOG_FILE", "logs/app.jsonl"))
DEFAULT_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_started = time.time()
_local = threading.local()


# ---- metrics ------------------------------------------------------------------------------------
def _key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple, float]] = defaultdict(dict)
        self._gauges: dict[str, dict[tuple, float]] = defaultdict(dict)
        self._hists: dict[str, dict[tuple, dict[str, Any]]] = defaultdict(dict)
        self._help: dict[str, str] = {}
        self._buckets: dict[str, tuple[float, ...]] = {}

    def describe(self, name: str, help_text: str, buckets: Iterable[float] | None = None) -> None:
        self._help[name] = help_text
        if buckets:
            self._buckets[name] = tuple(sorted(buckets))

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            d = self._counters[name]
            d[_key(labels)] = d.get(_key(labels), 0.0) + value

    def set(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[name][_key(labels)] = float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        buckets = self._buckets.get(name, DEFAULT_BUCKETS)
        with self._lock:
            h = self._hists[name].setdefault(_key(labels), {"count": 0, "sum": 0.0, "le": [0] * len(buckets), "recent": []})
            h["count"] += 1
            h["sum"] += value
            for i, b in enumerate(buckets):
                if value <= b:
                    h["le"][i] += 1
            r = h["recent"]
            r.append(value)
            if len(r) > 512:
                del r[: len(r) - 512]

    def get_counter(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._counters.get(name, {}).get(_key(labels), 0.0)

    def counter_total(self, name: str) -> float:
        with self._lock:
            return sum(self._counters.get(name, {}).values())

    def quantile(self, name: str, q: float, **labels: str) -> float | None:
        with self._lock:
            h = self._hists.get(name, {}).get(_key(labels))
            if not h or not h["recent"]:
                return None
            r = sorted(h["recent"])
            return r[min(len(r) - 1, int(q * len(r)))]

    def reset(self) -> None:
        """Clear observations (tests, or a deliberate counter reset); the build label survives."""
        with self._lock:
            build = self._gauges.get("aero_build_info")
            self._counters.clear()
            self._gauges.clear()
            self._hists.clear()
            if build:
                self._gauges["aero_build_info"] = build

    # -- views --
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            def lab(k: tuple) -> dict[str, str]:
                return dict(k)

            return {
                "counters": {n: [{"labels": lab(k), "value": v} for k, v in d.items()] for n, d in self._counters.items()},
                "gauges": {n: [{"labels": lab(k), "value": v} for k, v in d.items()] for n, d in self._gauges.items()},
                "histograms": {n: [{"labels": lab(k), "count": h["count"], "sum": round(h["sum"], 6),
                                    "p50": _q(h["recent"], 0.5), "p95": _q(h["recent"], 0.95), "p99": _q(h["recent"], 0.99)} for k, h in d.items()]
                               for n, d in self._hists.items()},
                "help": dict(self._help),
            }

    def render_prometheus(self) -> str:
        out: list[str] = []
        with self._lock:
            for n, d in sorted(self._counters.items()):
                out += [f"# HELP {n} {self._help.get(n, '')}", f"# TYPE {n} counter"]
                out += [f"{n}{_labels(k)} {_num(v)}" for k, v in sorted(d.items())]
            for n, d in sorted(self._gauges.items()):
                out += [f"# HELP {n} {self._help.get(n, '')}", f"# TYPE {n} gauge"]
                out += [f"{n}{_labels(k)} {_num(v)}" for k, v in sorted(d.items())]
            for n, d in sorted(self._hists.items()):
                buckets = self._buckets.get(n, DEFAULT_BUCKETS)
                out += [f"# HELP {n} {self._help.get(n, '')}", f"# TYPE {n} histogram"]
                for k, h in sorted(d.items()):
                    for i, b in enumerate(buckets):
                        out.append(f"{n}_bucket{_labels(k, le=_num(b))} {h['le'][i]}")
                    out.append(f"{n}_bucket{_labels(k, le='+Inf')} {h['count']}")
                    out.append(f"{n}_sum{_labels(k)} {_num(h['sum'])}")
                    out.append(f"{n}_count{_labels(k)} {h['count']}")
        return "\n".join(out) + "\n"


def _q(recent: list[float], q: float) -> float | None:
    if not recent:
        return None
    r = sorted(recent)
    return round(r[min(len(r) - 1, int(q * len(r)))], 6)


def _num(v: float) -> str:
    if v == float("inf"):
        return "+Inf"
    return repr(int(v)) if float(v).is_integer() else repr(float(v))


def _labels(k: tuple, **extra: str) -> str:
    items = list(k) + list(extra.items())
    if not items:
        return ""
    body = ",".join(f'{a}="{str(b).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for a, b in items)
    return "{" + body + "}"


METRICS = Registry()
for _n, _h, _b in (
    ("aero_http_requests_total", "HTTP requests by method, route class and status", None),
    ("aero_http_request_seconds", "HTTP request latency", None),
    ("aero_http_denied_total", "Requests refused by the guard, by reason", None),
    ("aero_ingest_batches_total", "Batches ingested by source mode and provider", None),
    ("aero_ingest_states_total", "State vectors ingested", None),
    ("aero_ingest_feed_latency_seconds", "Feed latency (batch timestamp to arrival)", (0.5, 1, 2, 5, 10, 20, 30, 60, 120)),
    ("aero_engine_batch_seconds", "Rule engine time per batch", None),
    ("aero_findings_total", "Findings raised by rule and severity", None),
    ("aero_source_errors_total", "Source loop errors by kind", None),
    ("aero_source_last_ingest_timestamp_seconds", "Wall time of the last ingested batch", None),
    ("aero_source_tracked_aircraft", "Aircraft in the latest batch", None),
    ("aero_jobs_total", "Background jobs by type and final status", None),
    ("aero_job_seconds", "Background job duration by type", (1, 5, 15, 60, 300, 900, 3600)),
    ("aero_alerts_sent_total", "Alerts delivered to sinks", None),
    ("aero_feed_requests_total", "Upstream feed requests by host and outcome", None),
    ("aero_feed_request_seconds", "Upstream feed request latency by host", None),
    ("aero_audit_entries_total", "Audit log entries written by action", None),
    ("aero_tour_injections_total", "Demo tour injections by kind", None),
    ("aero_process_uptime_seconds", "Seconds since the process started", None),
    ("aero_process_rss_bytes", "Resident set size", None),
    ("aero_process_threads", "Live threads", None),
    ("aero_build_info", "Version label, always 1", None),
):
    METRICS.describe(_n, _h, _b)
METRICS.set("aero_build_info", 1, version=__version__)


def refresh_process_metrics() -> None:
    METRICS.set("aero_process_uptime_seconds", time.time() - _started)
    METRICS.set("aero_process_threads", threading.active_count())
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        METRICS.set("aero_process_rss_bytes", rss if sys.platform == "darwin" else rss * 1024)
    except (ImportError, OSError):
        pass


def route_class(path: str) -> str:
    """Collapse ids so label cardinality stays bounded: /api/v1/jobs/abc -> /api/v1/jobs/{id}."""
    parts = path.split("?")[0].split("/")
    out = []
    for i, p in enumerate(parts):
        if i >= 4 and p and parts[3] in ("jobs", "aircraft", "airports", "playbook", "docs", "reports"):
            out.append("{id}")
        else:
            out.append(p)
    s = "/".join(out)
    if s.startswith("/static/"):
        return "/static/*"
    if s.startswith("/reports/"):
        return "/reports/*"
    return s[:80]


# ---- structured logging -------------------------------------------------------------------------
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"ts": round(record.created, 3), "level": record.levelname.lower(), "logger": record.name,
                                   "event": record.getMessage()}
        payload.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(payload, default=str)


_logger: logging.Logger | None = None
_logger_path: Path | None = None
_logger_lock = threading.Lock()


def get_logger() -> logging.Logger:
    """The process logger, (re)configured whenever LOG_FILE changes."""
    global _logger, _logger_path
    with _logger_lock:
        if _logger is not None and _logger_path == LOG_FILE:
            return _logger
        lg = logging.getLogger("aero")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        for h in list(lg.handlers):
            lg.removeHandler(h)
            with contextlib.suppress(Exception):
                h.close()
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5)
            fh.setFormatter(_JsonFormatter())
            lg.addHandler(fh)
        except OSError:
            pass
        if os.getenv("AERO_LOG_STDERR") == "1":
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            lg.addHandler(sh)
        if not lg.handlers:
            lg.addHandler(logging.NullHandler())
        _logger, _logger_path = lg, LOG_FILE
        return lg


def bind_request(request_id: str | None = None, traceparent: str | None = None) -> str:
    """Attach correlation ids to the current thread; returns the request id (generated if absent)."""
    rid = (request_id or "").strip()[:64] or uuid.uuid4().hex[:16]
    _local.request_id = rid
    _local.traceparent = (traceparent or "").strip()[:64] or None
    return rid


def clear_request() -> None:
    _local.request_id = None
    _local.traceparent = None


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    rid = getattr(_local, "request_id", None)
    tp = getattr(_local, "traceparent", None)
    if rid:
        fields.setdefault("request_id", rid)
    if tp:
        fields.setdefault("traceparent", tp)
    get_logger().log(getattr(logging, level.upper(), logging.INFO), event, extra={"fields": fields})


def tail_logs(limit: int = 200, level: str | None = None, event: str | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """Last ``limit`` JSON log lines (newest first), optionally filtered."""
    p = path or LOG_FILE
    try:
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 2_000_000))
            lines = fh.read().decode(errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for ln in reversed(lines):
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if level and e.get("level") != level:
            continue
        if event and event not in str(e.get("event", "")):
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


# ---- health ------------------------------------------------------------------------------------
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - _started, 1)}


def readiness(expect_source: bool = False, source_active: bool = False, last_ingest_age_s: float | None = None,
              max_ingest_age_s: float = 300.0) -> tuple[bool, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    static = Path(__file__).with_name("web") / "static" / "index.html"
    checks["static_assets"] = {"ok": static.is_file()}
    for d in ("data/app", "reports", "logs"):
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            probe = Path(d) / ".ready-probe"
            probe.write_text("x")
            probe.unlink()
            checks[f"writable:{d}"] = {"ok": True}
        except OSError as e:
            checks[f"writable:{d}"] = {"ok": False, "error": str(e)}
    try:
        from .web.audit import AUDIT_FILE, verify_file

        if AUDIT_FILE.is_file():
            v = verify_file(AUDIT_FILE)
            checks["audit_chain"] = {"ok": bool(v["ok"]), "entries": v["entries"], "error": v.get("error")}
        else:
            checks["audit_chain"] = {"ok": True, "entries": 0}
    except Exception as e:  # noqa: BLE001 - readiness must never raise
        checks["audit_chain"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        from .ml import verify_model

        mp = Path("models/kinematic_iforest.joblib")
        checks["model_registry"] = {"ok": (not mp.is_file()) or bool(verify_model(mp)["match"]), "present": mp.is_file()}
    except Exception as e:  # noqa: BLE001
        checks["model_registry"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if expect_source:
        fresh = source_active and (last_ingest_age_s is None or last_ingest_age_s <= max_ingest_age_s)
        checks["source"] = {"ok": bool(fresh), "active": source_active, "last_ingest_age_s": last_ingest_age_s}
    ok = all(c["ok"] for c in checks.values())
    return ok, {"status": "ready" if ok else "not-ready", "checks": checks, "version": __version__}


__all__ = ["LOG_FILE", "METRICS", "Registry", "bind_request", "clear_request", "get_logger", "health", "log_event",
           "readiness", "refresh_process_metrics", "route_class", "tail_logs"]
