# Changelog

All notable changes to aero-audit. Dates are UTC.

## 1.1.0 - 2026-09-19

- **Overview board**: `aero overview`, `GET /api/v1/overview` and the top of the HOME page show air and space in one
  glance from cached products and reports: space-operations TFRs in effect and the next one, launches within 24 h (crewed
  flagged), space weather scales and advisories, decaying objects, the last conjunction screen, well-clear rate, reports
  of the last 24 h.
- **ST-25 traffic displacement by launch airspace**: across every cached TFR product and recording, distinct aircraft
  inside each restriction per minute while in effect against the same volume outside its effective time; grows with
  history (`airspace.displacement`).
- The `mission` job defaults to the next launch with a pad when no launch is named (SPACE page button).

## 1.0.0 - 2026-09-18

The 1.0 bar: every control implemented, the public contract frozen, the honest numbers written into the reports.

- **Space data link security practised** (C-32): SDLS-style packet streams (SPI, sequence, HMAC-SHA256 MAC) verified per packet
  with keys from `AERO_SDLS_KEY_<spi>`, anti-replay on the sequence, and the authentication status of the transport recorded
  in every telemetry report; SPC-006 (failed authentication), SPC-007 (accepted on trust), SPC-008 (replay); `space/sdls.py`.
- **Assurance reviews practised** (C-31): a dated review record per component with cadence by class and safety relevance,
  self-reviews labelled as such, automatic evidence (tests importing the component, lint, CodeQL, fuzzing, traceability,
  documentation); `aero gov reviews`, `docs/generated/REVIEWS.md`, `docs/assurance/review_log.json`.
- **Apron capacity closed the loop** (C-07): zones with declared capacity from JSON, detections from the detector or any
  annotation file, detector recall and precision against annotations measured and written into every report (the COCO
  baseline draws 5 boxes on the sample of which 2 match the 12 annotated transports; the number ships with the finding); `aero vision apron
  --detections/--truth/--out`.
- **Contract and stability policy**: `contracts/contract-1.0.json` snapshots CLI commands, rule ids, API routes, jobs,
  studies, controls, playbooks, environment variables and the report envelope; `aero gov contract --check` and PUB-13
  fail on any removal; `docs/STABILITY.md` states what is frozen and how deprecation works; PUB-12 requires every control
  implemented; classifier Production/Stable.
- TFR documents in local time zones are converted (US zone abbreviations; unknown zones flagged); launch records keep
  mission type, orbit and a crewed flag, shown in the mission dossier; bench rows for the airspace join and reentry
  subpoints.

## 0.8.0 - 2026-09-18

- The air/space seam: FAA temporary flight restrictions fetched keyless (list plus XNOTAM geometry, times and
  limits; `ingest/tfr.py`) and joined to recorded traffic and to launch windows (TFR-001..003, `space/airspace.py`);
  reentry corridors of decaying objects with a checked TEME-to-geodetic conversion against airports and traffic
  (REN-001..003, `space/reentry.py`); a spaceport table with SATCAT site codes (`knowledge/spaceports.py`); the
  per-launch mission dossier (`space/mission.py`, `aero space mission`). Commands `aero space tfr`, `reentry`,
  `mission`; jobs `tfr`, `reentry`, `mission`; studies ST-22..ST-24; controls C-45..C-47; live-check and demo steps;
  `faa_tfr` in the integration inventory; synthetic samples `tfr_sample.json` and `decaying_sample.tle`.
- Upstream: nasa/NASA-3D-Resources#50 withdrawn; the contribution package lives in `upstream/nasa3d/` (no public fork).
- SATCAT rows keep the launch-site code.

## 0.7.0 - 2026-09-18

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
- Depth: numpy OBJ renderer for multi-view training images; element-history manoeuvre and decay detection (ORB-006/007,
  ST-20); encounter model with Monte Carlo NMAC estimates (ST-19); traceability matrix with gap lists (C-42,
  docs/generated/TRACEABILITY.md); `aero space render|maneuvers`, `aero uas encounter-model`, `aero gov traceability`.
- Licence position determined and recorded (docs/LICENSE_DETERMINATION.md): PUB-10 passes; ten controls that were
  complete moved from partial to implemented with honest notes (implementation index 95%).
- `aero gov digest`: the periodic brief (reports by kind, findings by rule and severity, worst findings, posture, live check,
  hold-out, jobs, publication gate) with a manifest; `digest` job and launchd schedule; C-44.
- Demo and live check cover the gap fills: bundled public-domain Falcon 9 telemetry sample, UTM conformance and crisis
  airports when their inputs are fetched; live-check adds NWS alerts and the UTM contract fetch (7 keyless paths).
- Second-source hold-out (149 NASA-library images from other queries, de-duplicated by id): histogram 40.9%, YOLOv8n-cls
  56.4% top-1, recorded next to the in-distribution numbers as the ones to quote.
- Gap fills: JSON telemetry loader and a real Falcon 9 ascent audited with a manifest; UTM validator resolves external
  refs to sibling contracts, `aero uas utm-fetch`, ST-09 on NASA's real contracts with run-study options; live NWS crisis
  extents (`aero data crisis-fetch`, ST-11 on real flood warnings); `aero space classify-eval` on a second-source hold-out;
  YOLO classifier behind the registry gate for `aero space classify`.
- Real-imagery evaluation: 400-image NASA library dataset (4 scene classes); histogram classifier 64.0%, YOLOv8n-cls
  fine-tune 80.2% top-1 on 86 held-out real images, both registered with cards; `scripts/release_candidate.sh` (local,
  push-guarded release preparation) and the recommendation in docs/RELEASE_PLAN.md; docs/RELEASE_PLAN.md (three slices, decision
  points, mechanical gate); launchd example for `aero space watch`; empty-dataset guard in `aero space dataset`.
- `aero space live-check`: every keyless space client end to end against the live feeds, one report, exit code on failure.
- Space-Track made optional: CelesTrak SATCAT client (keyless, 70k objects) for identity, owner, type, orbit and decay
  dates; ORB-008; catalogue enrichment on every conjunction screen; `aero space satcat`, satcat job and page section;
  capability matrix in docs/ACCOUNTS.md; Space-Track rows carry the user-agreement restriction and stay out of bundles.
- Accounts wired: `aero accounts --probe` (harmless authenticated reads, values never printed), `.env.example` with the space
  variables, Space-Track call-out and pull button on the Space page, `aero space watch` adds the Space-Track pull when
  credentials exist; NASA DONKI notifications with DEMO_KEY fallback cross-checked against the SWPC assessment
  (`aero space weather --donki`, job param, Space page card). Account creation itself stays with the user.
- Formats and detector: space/mesh.py reads STL, glTF binary (Draco via the DracoPy wheel), 3DS and LightWave LWO2/LWOB,
  covering 607 of the 622 NASA-3D-Resources models without Blender or assimp; renders of two real NASA models feed a dataset;
  the ultralytics classification fine-tune ran on CPU (YOLOv8n-cls, 3 epochs, top-1 0.905 on held-out renders) and
  `scripts/train_detector.py --register` files the weights with a card and a registry entry; upstream package: catalogue
  regenerated and verify run recorded in docs/UPSTREAM.md with the licence email drafted for the user.
- Availability and scale: network jobs degrade to the newest cached product with a `degraded` flag and metric; scheduler
  never stacks a running job type, applies politeness floors per feed and backs off on failures; feed health and job
  cards on the Space and UAS pages with auto-refresh when jobs settle; `aero uas trend` and ST-21 (DAA-005) across
  recordings.
- Evidence: every space and UAS report now ships JSON + Markdown + manifest with provenance and input hashes
  (audit/generic_report.py), from the CLI and from jobs alike; `aero space demo` runs every analysis offline on the
  bundled samples; `aero doctor` checks sgp4, OpenCV, cached elements, the CDM ledger and the space samples.
- Performance: vectorised well-clear projection (CONUS scoring ~60 s -> 11 s), rasteriser (1.1 s -> 0.04 s at 40k triangles),
  conjunction screen (SatrecArray + broadcasted distances), catalogue hash cache, memoised page summaries; scalar references
  kept and proven equivalent in tests/test_perf_equivalence.py; `aero bench --suite space`; docs/PERFORMANCE.md.

## 0.6.1 - 2026-09-18 - fuzzed, hardened

- Fuzzing: `fuzz/fuzz_targets.py` (atheris) covers recording replay, the rules engine's state vectors, request path
  confinement and report manifests; a CI job fuzzes each target on every push and the suite smoke-tests the harness.
- Fixed, found by the fuzzer on its first runs: a report manifest that is not a JSON object (or has malformed file
  entries) is reported as invalid instead of raising; a request path whose home expansion fails (`~nobody/x`) is refused
  instead of raising.
- The demo tour's stop() waits for its thread, so a step already sleeping cannot inject after the caller has moved on.
- Supply chain: `pip-audit` pinned in CI and release workflows; SECURITY.md carries the advisory URL, a 7-day
  acknowledgement and 90-day fix window, supported versions and the fuzzing note. First release signed with Sigstore.

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
