# Changelog

All notable changes to aero-audit. Dates are UTC.

## Unreleased (space-intake, private branch)

- Space: NASA-3D-Resources catalogue with blob-verified fetch; NASA image and video library client; footage frames
  and caption milestones; SPC launch telemetry rules; keyless CelesTrak elements with SGP4 screening (ORB-001..003);
  CCSDS CDM assessment with covariance-based Pc (ORB-004/005), KVN and XML inbox with event trends, Space-Track
  client; debris-mitigation checklist DEB-001..008 with a lifetime model; dataset pipeline with provenance and a
  registry-gated scene classifier; ultralytics fine-tune scaffold.
- UAS: DO-365 / DAIDALUS well-clear and alert levels, encounter extraction with NMAC-proximate rates and lead time
  (DAA-001/002), schema-lite OpenAPI contract validator.
- Governance: domains, standards, controls with typed evidence, unified register, study registry (15 studies, 13
  runnable), posture index, NPR 7150.2 assurance classification with a SLIM checklist, CMR-style data catalogue with
  reconciliation; `aero gov`, `aero uas`, `aero space`, `aero data catalog`; GOV page; docs/HOLISTIC_PLAN.md.
- Upstream package for nasa/NASA-3D-Resources (standalone script and PR text).
- Cross-domain feeds: NOAA space weather mapped to ICAO advisory effects with exposed high-latitude traffic (SWX-001..005);
  Launch Library 2 windows joined to traffic near the pad (LCH-001..003); airspace density classes and the observed DAA
  risk ratio (DAA-003/004); `space-environment` domain; C-38..C-41; ST-16..ST-18.
- App: SPACE and UAS pages with job buttons; `/api/v1/space`, `/api/v1/uas`, `/api/v1/integrations`, `/api/v1/schedule`;
  scheduled intake (`AERO_SCHEDULE`, `AERO_OFFLINE`) sharing one job registry with `aero space watch`; `aero accounts`
  and docs/ACCOUNTS.md; report kinds for every space and UAS report.

## 0.6.0 - 2026-09-15 - contract, evidence, release engineering

- API contract: OpenAPI 3.1 generated from the router at `/api/v1/openapi.json` and rendered to
  `docs/generated/API.md`; the test suite fails on any undocumented route.
- Evidence bundles: `aero log bundle` zips the audit chain with its verification, reports and
  manifests, model card / registry / evaluation, thresholds, generated docs and redacted settings
  with `BUNDLE.json` hashes; `aero log verify-bundle` re-checks them.
- POST rate limiting per client (token bucket, `AERO_POST_RATE_LIMIT`, 429 with Retry-After).
- Orderly shutdown on SIGTERM/SIGINT: sources and tour stopped, `app.stop` audit entry and log line,
  listener closed (containers stop cleanly).
- `aero bench`: engine throughput and per-batch percentiles with provenance; capacity numbers in docs.
- Release engineering: `release.yml` builds sdist and wheel, a CycloneDX SBOM and checksums and
  attaches them to the GitHub release; CI publishes the SBOM as an artifact; OpenSSF Scorecard
  workflow and badge; CODEOWNERS, issue and pull-request templates, pre-commit config.
- F9 jumps to Observability.

## 0.5.0 - 2026-09-15 - observable

- `aero_audit/observability.py`: dependency-free metrics registry (counters, gauges, histograms with
  labels) exposed as Prometheus text at `/metrics`, JSON at `/api/v1/observability`; liveness `/healthz`
  and readiness `/readyz` (static assets, writable state, audit chain, model registry, fresh ingest);
  structured JSON logs in `logs/app.jsonl` with `X-Request-Id` / W3C `traceparent` correlation and
  `/api/v1/logs`.
- Instrumented: HTTP (by route class and status, latency, guard denials), ingest batches and state
  vectors, engine time per batch, findings by rule and severity, feed calls by host and outcome,
  source loop errors, jobs, alerts, audit entries, tour injections, process uptime / RSS / threads.
- Observability page (`OBS`) with readiness checks, counters, latency percentiles and a log tail;
  `aero obs health | metrics | logs -f`.
- `ops/`: Prometheus scrape config and alert rules, Grafana provisioning and dashboard;
  `compose.observability.yaml` overlay (loopback-bound).
- `/metrics` needs the token in remote mode; probes stay open.

## 0.4.0 - 2026-09-10 - public, demoable, auditable

**Runs anywhere, offline**
- `aero demo`: one command replays a bundled real-traffic sample (two adsb.lol recordings, 4,300
  aircraft, ODbL) with a scripted eight-scenario attack tour; trains a small anomaly model on the
  samples when none exists.
- `scripts/bootstrap.sh`, `scripts/bootstrap.ps1`, `Makefile`: venv plus hash-verified install
  (`--require-hashes` against a universal lock file), `aero doctor` health check, then the demo.
- `Dockerfile` and `compose.yaml`: non-root image, no build step, port published on loopback only.
- `aero doctor`: Python, dependencies, samples, model integrity, writable dirs, port, feed
  reachability with the curl-fallback hint, audit-chain status.
- Recordings may be gzip-compressed (`.jsonl.gz`); the Home page lists bundled samples.

**Local app hardening** (`aero_audit/web/security.py`)
- Host-header validation against DNS rebinding; per-process CSRF token in `X-Aero-Token` on every
  POST plus `Origin` / `Sec-Fetch-Site` checks and a JSON-only content type; 1 MB body cap; strict
  Content-Security-Policy (no inline scripts, tiles only from OpenStreetMap) and hardening headers;
  `Server` banner without the Python version.
- Non-loopback binds require `--token` / `AERO_APP_TOKEN` (every API call authenticated) or an
  explicit `--allow-unauthenticated`; the front end asks for the token once.
- Every user-supplied path is confined: recordings to `data/recordings` and `data/samples`, models
  to `models/`, watchlists to `data/`, logs to `logs/`; webhooks must be `http(s)` without credentials.
- Models load only when their SHA-256 matches `models/registry.json` (`aero_audit/ml/registry.py`);
  override with `--allow-unverified-model` or `AERO_ALLOW_UNVERIFIED_MODEL=1`.
- Inline event handlers removed from the front end so the CSP can forbid inline script.

**Auditability**
- Hash-chained audit log: each entry carries `seq`, `prev` and its own SHA-256; `aero log verify`
  and `GET /api/v1/audit/verify` walk the chain and name the first broken line.
- Provenance in every report (tool version, git commit, input recording hash, model hash and
  registry status, evaluation hash, threshold overrides) and a `.manifest.json` with the SHA-256 of
  each report file; `aero log verify-report` and the Reports page re-check them.
- Audible alerts in the app: tones or spoken announcements for new high and critical findings
  (`SND` in the header or on the command line).
- Scripted demo tour with narration in the banner (`TOUR`); targeted injections now last N polls
  *of the target* so they work on round-robin feeds.

**Repository**
- MIT licence, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY policy rewritten, CHANGELOG.
- CI: hash-verified install, ruff, pytest, docs drift check, pip-audit, gitleaks over history,
  container build; CodeQL for Python and JavaScript; Dependabot; actions pinned to commit SHAs.
- Lock file regenerated without machine-specific paths; `models/registry.json` is now local state.

## 0.3.0 - 2026-09-10

- Continental ecosystem: 132 airports, ~80 operators, ~180 types, flight phases from altitude
  above field, FAA NAS status feed, per-poll airport / operator / type tables.
- Terminal-style UI: command line with mnemonics, F-keys, ticker, Flights / Airports / Operators /
  Audit log pages with dropdown filters, sortable grids and CSV export.
- Nationwide feeds (OpenSky CONUS box, adsb.lol 15-hub round-robin), canvas map with colour modes.
- Local multi-page app with jobs, settings (writes `aero.toml`), reports, in-app docs.

## 0.2.0 - 2026-09-09

- Evaluation harness with eight injected attack scenarios; precision-weighted risk scoring;
  Wilson-bound risk register with residual risk; model registry and card; HTML reports.
- Security layer: threat catalog, playbooks, trust ledger, watchlist, cross-feed corroboration,
  stream burst / collapse checks, alert sinks, holding impact model.

## 0.1.0 - 2026-09-09

- Ingest from adsb.lol and OpenSky, JSONL recordings, kinematic features, rules engine,
  IsolationForest anomaly model, tiled YOLO apron detection, CLI.
