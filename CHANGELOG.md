# Changelog

All notable changes to aero-audit. Dates are UTC.

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
