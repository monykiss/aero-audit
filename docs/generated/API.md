# API v1 (generated from the router, 0.6.0)

Local, single-user API of the aero-audit app. JSON in, JSON out; POST bodies must be application/json and carry X-Aero-Token (the CSRF token from GET /api/v1/app in loopback mode, or the shared token in remote mode). Every response carries X-Request-Id. See SECURITY.md and docs/APP.md.

| Method | Path | Tag | Summary | Description |
|---|---|---|---|---|
| GET | `/api/v1/app` | app | App status | Version, uptime, active source, model registry entry, security mode, tour, audit chain head. |
| GET | `/api/v1/regions` | sources | Region catalogue | Presets, groups, boxes and global feeds with default provider and interval. |
| GET | `/api/v1/recordings` | sources | Recordings on disk | Inventory of recordings and bundled samples with polls, aircraft and span. |
| POST | `/api/v1/source/start` | sources | Start a source | Replay a recording (confined to data/recordings and data/samples) or go live on a provider and region. |
| GET | `/api/v1/security` | app | Security mode | Guard mode (loopback, token, open) and the CSRF token in loopback mode. |
| GET | `/api/v1/tour` | demo | Tour status | Scripted tour state: step, next injection, narration. |
| POST | `/api/v1/tour` | demo | Start or stop the tour | Body {"action": "start"|"stop"}. |
| POST | `/api/v1/source/stop` | sources | Stop the source | Stop the active replay or live source. |
| GET | `/api/v1/state` | picture | Live snapshot | Every aircraft in the latest batch with enrichment, KPIs, ranked findings, events, injections, METARs. |
| GET | `/api/v1/aircraft/{icao}` | picture | Aircraft detail | State, enrichment, trail, trust and findings for one ICAO24 address. |
| GET | `/api/v1/findings` | findings | Findings | Findings this session ranked by risk score, filterable by severity, rule, category and text. |
| GET | `/api/v1/findings.csv` | findings | Findings CSV | All findings as CSV. |
| GET | `/api/v1/risk` | risk | Risk register | Evidence-adjusted register for the session (baseline when no source runs). |
| GET | `/api/v1/threats` | risk | Threat coverage | Threat catalogue with rules and measured recall. |
| GET | `/api/v1/evaluation` | risk | Evaluation results | The latest injected-scenario evaluation (models/evaluation.json). |
| GET | `/api/v1/impact` | risk | Holding impact | Holding minutes, fuel, CO2 and delay cost for the session. |
| GET | `/api/v1/model` | risk | Model registry entry | Rows, aircraft, holdout flag rate, checksum and evaluation of the current model. |
| GET | `/api/v1/rules` | reference | Rule catalogue | Every rule id with category, description and whether a playbook exists. |
| GET | `/api/v1/playbooks` | reference | Playbooks | All response playbooks. |
| GET | `/api/v1/playbook/{rule}` | reference | Playbook | Triage, verify, escalate and contain steps for one rule. |
| POST | `/api/v1/inject` | demo | Inject a demo scenario | Teleport, hijack code, altitude or velocity forgery, ghosts, flood, collapse (demo mode only). |
| POST | `/api/v1/clear` | demo | Clear injections | Stop every active demo injection. |
| GET | `/api/v1/reports` | reports | Reports on disk | Report groups with links to JSON, Markdown, HTML and manifest. |
| GET | `/api/v1/ecosystem` | ecosystem | Ecosystem summary | Per-poll airport, operator and type tables, phases and categories. |
| GET | `/api/v1/flights` | picture | Flights grid | Filterable, sortable table of the current picture (operator, category, type class, phase, airport, altitude band, severity, source, text). |
| GET | `/api/v1/flights.csv` | picture | Flights CSV | The flights grid as CSV with the same filters. |
| GET | `/api/v1/airports` | ecosystem | Airports | Known airports with live activity, FAA programmes and METAR. |
| GET | `/api/v1/airports/{icao}` | ecosystem | Airport detail | One airport: activity, flights nearby, weather, FAA status. |
| GET | `/api/v1/operators` | ecosystem | Operators | Operators in the picture with fleet, phases, integrity compliance and findings; aircraft types alongside. |
| GET | `/api/v1/faa` | ecosystem | FAA NAS status | Ground stops, delay programmes and closures; fetched on demand when no source holds a copy. |
| GET | `/api/v1/audit` | audit | Audit log | Hash-chained audit entries, filterable by action, actor and text. |
| GET | `/api/v1/audit.csv` | audit | Audit log CSV | All audit entries as CSV with sequence, previous hash and hash. |
| GET | `/api/v1/governance` | governance | Governance posture | Domains, controls with evidence, unified register, studies, policies and the posture index. |
| GET | `/api/v1/openapi.json` | reference | This document | OpenAPI 3.1 description of the API, generated from the router. |
| GET | `/api/v1/observability` | observability | Observability snapshot | KPIs, readiness checks and every metric with percentiles. |
| GET | `/api/v1/logs` | observability | Structured log tail | Newest JSON log events, filterable by level and event substring. |
| GET | `/api/v1/audit/verify` | audit | Verify the audit chain | Walk the chain and report the first broken line, if any. |
| GET | `/api/v1/reports/{name}/manifest` | reports | Verify a report manifest | Re-hash the report files named by the manifest. |
| GET | `/api/v1/jobs` | jobs | Jobs | Recent background jobs with status and results. |
| POST | `/api/v1/jobs` | jobs | Submit a job | Body {"type": capture|audit_session|audit_recording|train|evaluate|prune|docs_build|corroborate, "params": {...}}. |
| GET | `/api/v1/jobs/{id}` | jobs | Job detail | Status, progress, log and result of one job. |
| POST | `/api/v1/jobs/{id}/cancel` | jobs | Cancel a job | Request cancellation of a running job. |
| GET | `/api/v1/settings` | settings | Settings | App settings, model integrity and every tunable threshold with its override state. |
| POST | `/api/v1/settings` | settings | Update settings | Body {"app": {...}, "tunables": {section: {KEY: value}}}; paths are confined, thresholds written to aero.toml. |
| GET | `/api/v1/docs` | reference | Documentation index | Markdown documents available in-app. |
| GET | `/api/v1/docs/{name}` | reference | Document | One Markdown document from docs/ or README.md. |
| GET | `/healthz` | observability | Liveness | Always 200 while the process serves; version and uptime. |
| GET | `/readyz` | observability | Readiness | 503 when static assets, writable state, the audit chain, the model registry or a fresh ingest fail. |
| GET | `/metrics` | observability | Prometheus metrics | Text exposition format; needs the token in remote mode. |

Errors are JSON objects with an `error` string: 400 Invalid input; 401 Access token required (remote mode); 403 Refused by the guard (Host, Origin, CSRF token) or by mode; 404 Not found; 413 Body too large; 415 Body must be application/json; 429 Too many POST requests from this client; 500 Unexpected error.
