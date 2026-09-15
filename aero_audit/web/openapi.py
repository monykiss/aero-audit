"""OpenAPI 3.1 description of the local API, generated from the router so it cannot drift.

Every route must have an entry in ``SUMMARIES`` (the test suite fails otherwise): a route without
a sentence explaining it is a route nobody agreed to keep. The document is served at
``/api/v1/openapi.json`` and rendered to ``docs/generated/API.md`` by ``aero docs-build``.
"""

from __future__ import annotations

import re
from typing import Any

from .. import __version__

# (method, path) -> (summary, description, tag)
SUMMARIES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("GET", "/api/v1/app"): ("App status", "Version, uptime, active source, model registry entry, security mode, tour, audit chain head.", "app"),
    ("GET", "/api/v1/security"): ("Security mode", "Guard mode (loopback, token, open) and the CSRF token in loopback mode.", "app"),
    ("GET", "/api/v1/regions"): ("Region catalogue", "Presets, groups, boxes and global feeds with default provider and interval.", "sources"),
    ("GET", "/api/v1/recordings"): ("Recordings on disk", "Inventory of recordings and bundled samples with polls, aircraft and span.", "sources"),
    ("POST", "/api/v1/source/start"): ("Start a source", "Replay a recording (confined to data/recordings and data/samples) or go live on a provider and region.", "sources"),
    ("POST", "/api/v1/source/stop"): ("Stop the source", "Stop the active replay or live source.", "sources"),
    ("GET", "/api/v1/state"): ("Live snapshot", "Every aircraft in the latest batch with enrichment, KPIs, ranked findings, events, injections, METARs.", "picture"),
    ("GET", "/api/v1/aircraft/{icao}"): ("Aircraft detail", "State, enrichment, trail, trust and findings for one ICAO24 address.", "picture"),
    ("GET", "/api/v1/flights"): ("Flights grid", "Filterable, sortable table of the current picture (operator, category, type class, phase, airport, altitude band, severity, source, text).", "picture"),
    ("GET", "/api/v1/flights.csv"): ("Flights CSV", "The flights grid as CSV with the same filters.", "picture"),
    ("GET", "/api/v1/airports"): ("Airports", "Known airports with live activity, FAA programmes and METAR.", "ecosystem"),
    ("GET", "/api/v1/airports/{icao}"): ("Airport detail", "One airport: activity, flights nearby, weather, FAA status.", "ecosystem"),
    ("GET", "/api/v1/operators"): ("Operators", "Operators in the picture with fleet, phases, integrity compliance and findings; aircraft types alongside.", "ecosystem"),
    ("GET", "/api/v1/ecosystem"): ("Ecosystem summary", "Per-poll airport, operator and type tables, phases and categories.", "ecosystem"),
    ("GET", "/api/v1/faa"): ("FAA NAS status", "Ground stops, delay programmes and closures; fetched on demand when no source holds a copy.", "ecosystem"),
    ("GET", "/api/v1/findings"): ("Findings", "Findings this session ranked by risk score, filterable by severity, rule, category and text.", "findings"),
    ("GET", "/api/v1/findings.csv"): ("Findings CSV", "All findings as CSV.", "findings"),
    ("GET", "/api/v1/risk"): ("Risk register", "Evidence-adjusted register for the session (baseline when no source runs).", "risk"),
    ("GET", "/api/v1/threats"): ("Threat coverage", "Threat catalogue with rules and measured recall.", "risk"),
    ("GET", "/api/v1/evaluation"): ("Evaluation results", "The latest injected-scenario evaluation (models/evaluation.json).", "risk"),
    ("GET", "/api/v1/impact"): ("Holding impact", "Holding minutes, fuel, CO2 and delay cost for the session.", "risk"),
    ("GET", "/api/v1/model"): ("Model registry entry", "Rows, aircraft, holdout flag rate, checksum and evaluation of the current model.", "risk"),
    ("GET", "/api/v1/rules"): ("Rule catalogue", "Every rule id with category, description and whether a playbook exists.", "reference"),
    ("GET", "/api/v1/playbooks"): ("Playbooks", "All response playbooks.", "reference"),
    ("GET", "/api/v1/playbook/{rule}"): ("Playbook", "Triage, verify, escalate and contain steps for one rule.", "reference"),
    ("POST", "/api/v1/inject"): ("Inject a demo scenario", "Teleport, hijack code, altitude or velocity forgery, ghosts, flood, collapse (demo mode only).", "demo"),
    ("POST", "/api/v1/clear"): ("Clear injections", "Stop every active demo injection.", "demo"),
    ("GET", "/api/v1/tour"): ("Tour status", "Scripted tour state: step, next injection, narration.", "demo"),
    ("POST", "/api/v1/tour"): ("Start or stop the tour", "Body {\"action\": \"start\"|\"stop\"}.", "demo"),
    ("GET", "/api/v1/reports"): ("Reports on disk", "Report groups with links to JSON, Markdown, HTML and manifest.", "reports"),
    ("GET", "/api/v1/reports/{name}/manifest"): ("Verify a report manifest", "Re-hash the report files named by the manifest.", "reports"),
    ("GET", "/api/v1/jobs"): ("Jobs", "Recent background jobs with status and results.", "jobs"),
    ("POST", "/api/v1/jobs"): ("Submit a job", "Body {\"type\": capture|audit_session|audit_recording|train|evaluate|prune|docs_build|corroborate, \"params\": {...}}.", "jobs"),
    ("GET", "/api/v1/jobs/{id}"): ("Job detail", "Status, progress, log and result of one job.", "jobs"),
    ("POST", "/api/v1/jobs/{id}/cancel"): ("Cancel a job", "Request cancellation of a running job.", "jobs"),
    ("GET", "/api/v1/settings"): ("Settings", "App settings, model integrity and every tunable threshold with its override state.", "settings"),
    ("POST", "/api/v1/settings"): ("Update settings", "Body {\"app\": {...}, \"tunables\": {section: {KEY: value}}}; paths are confined, thresholds written to aero.toml.", "settings"),
    ("GET", "/api/v1/audit"): ("Audit log", "Hash-chained audit entries, filterable by action, actor and text.", "audit"),
    ("GET", "/api/v1/audit.csv"): ("Audit log CSV", "All audit entries as CSV with sequence, previous hash and hash.", "audit"),
    ("GET", "/api/v1/audit/verify"): ("Verify the audit chain", "Walk the chain and report the first broken line, if any.", "audit"),
    ("GET", "/api/v1/docs"): ("Documentation index", "Markdown documents available in-app.", "reference"),
    ("GET", "/api/v1/docs/{name}"): ("Document", "One Markdown document from docs/ or README.md.", "reference"),
    ("GET", "/api/v1/observability"): ("Observability snapshot", "KPIs, readiness checks and every metric with percentiles.", "observability"),
    ("GET", "/api/v1/logs"): ("Structured log tail", "Newest JSON log events, filterable by level and event substring.", "observability"),
    ("GET", "/api/v1/openapi.json"): ("This document", "OpenAPI 3.1 description of the API, generated from the router.", "reference"),
    ("GET", "/api/v1/governance"): ("Governance posture", "Domains, controls with evidence, unified register, studies, policies and the posture index.", "governance"),
}

QUERY_PARAMS: dict[str, list[tuple[str, str]]] = {
    "/api/v1/flights": [("operator", "operator designator"), ("category", "operator category"), ("type_cat", "type class"), ("phase", "flight phase"),
                        ("airport", "nearest airport ICAO"), ("altband", "ground|low|mid|high"), ("severity", "worst finding severity"), ("source", "position source"),
                        ("q", "text search"), ("sort", "column, prefix + for ascending"), ("limit", "max rows")],
    "/api/v1/flights.csv": [("operator", ""), ("category", ""), ("type_cat", ""), ("phase", ""), ("airport", ""), ("altband", ""), ("severity", ""), ("source", ""), ("q", "")],
    "/api/v1/findings": [("severity", ""), ("rule", ""), ("category", ""), ("q", ""), ("limit", "")],
    "/api/v1/airports": [("country", "ISO country code")],
    "/api/v1/operators": [("category", "")],
    "/api/v1/audit": [("action", ""), ("actor", ""), ("q", ""), ("limit", "")],
    "/api/v1/logs": [("limit", "max events (<= 2000)"), ("level", "info|warning|error"), ("event", "event substring")],
}

PROBES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("GET", "/healthz"): ("Liveness", "Always 200 while the process serves; version and uptime.", "observability"),
    ("GET", "/readyz"): ("Readiness", "503 when static assets, writable state, the audit chain, the model registry or a fresh ingest fail.", "observability"),
    ("GET", "/metrics"): ("Prometheus metrics", "Text exposition format; needs the token in remote mode.", "observability"),
}

ERRORS = {"400": "Invalid input", "401": "Access token required (remote mode)", "403": "Refused by the guard (Host, Origin, CSRF token) or by mode", "404": "Not found",
          "413": "Body too large", "415": "Body must be application/json", "429": "Too many POST requests from this client", "500": "Unexpected error"}


def _openapi_path(path: str) -> tuple[str, list[str]]:
    names = re.findall(r"{(\w+)}", path)
    return path, names


def build_spec(router: Any) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for r in router.routes:
        key = (r.method, r.raw)
        meta = SUMMARIES.get(key)
        if meta is None:
            missing.append(f"{r.method} {r.raw}")
            continue
        _add(paths, r.method, r.raw, meta)
    if missing:
        raise KeyError("undocumented routes: " + ", ".join(missing))
    for (m, p), meta in PROBES.items():
        _add(paths, m, p, meta)
    return {
        "openapi": "3.1.0",
        "info": {"title": "aero-audit local API", "version": __version__,
                 "description": "Local, single-user API of the aero-audit app. JSON in, JSON out; POST bodies must be application/json and carry "
                                "X-Aero-Token (the CSRF token from GET /api/v1/app in loopback mode, or the shared token in remote mode). "
                                "Every response carries X-Request-Id. See SECURITY.md and docs/APP.md.",
                 "license": {"name": "MIT"}},
        "servers": [{"url": "/"}],
        "components": {"securitySchemes": {"AeroToken": {"type": "apiKey", "in": "header", "name": "X-Aero-Token",
                                                         "description": "Per-process CSRF token (loopback) or shared access token (remote)."}},
                       "schemas": {"Error": {"type": "object", "properties": {"error": {"type": "string"}}, "required": ["error"]}}},
        "tags": [{"name": t} for t in sorted({m[2] for m in list(SUMMARIES.values()) + list(PROBES.values())})],
        "paths": paths,
    }


def _add(paths: dict[str, dict[str, Any]], method: str, raw: str, meta: tuple[str, str, str]) -> None:
    summary, description, tag = meta
    path, names = _openapi_path(raw)
    op: dict[str, Any] = {"summary": summary, "description": description, "tags": [tag],
                          "operationId": (method.lower() + re.sub(r"[^a-zA-Z0-9]+", "_", raw)).strip("_"),
                          "parameters": [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in names]
                          + [{"name": q, "in": "query", "required": False, "schema": {"type": "string"}, "description": d} for q, d in QUERY_PARAMS.get(raw, [])],
                          "responses": {"200": {"description": "OK", "content": {"text/csv" if raw.endswith(".csv") else ("text/plain" if raw == "/metrics" else "application/json"): {}}}}}
    if method == "POST":
        op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}
        op["security"] = [{"AeroToken": []}]
    for code in ("400", "403", "404", "500") if method == "GET" else tuple(ERRORS):
        op["responses"][code] = {"description": ERRORS[code], "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    paths.setdefault(path, {})[method.lower()] = op


def render_markdown(spec: dict[str, Any]) -> str:
    lines = [f"# API v1 (generated from the router, {spec['info']['version']})", "", spec["info"]["description"], "",
             "| Method | Path | Tag | Summary | Description |", "|---|---|---|---|---|"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            lines.append(f"| {method.upper()} | `{path}` | {op['tags'][0]} | {op['summary']} | {op['description']} |")
    lines += ["", "Errors are JSON objects with an `error` string: " + "; ".join(f"{c} {d}" for c, d in ERRORS.items()) + ".", ""]
    return "\n".join(lines)


__all__ = ["ERRORS", "PROBES", "QUERY_PARAMS", "SUMMARIES", "build_spec", "render_markdown"]
