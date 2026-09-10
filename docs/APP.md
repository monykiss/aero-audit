# The local app

`aero app` starts a local web application on `http://127.0.0.1:8787/` and opens your browser.
Nothing leaves your machine except requests to the public feeds you choose and map tiles.

```bash
.venv/bin/aero demo                   # offline: bundled sample + scripted attack tour
.venv/bin/aero app                    # home screen, choose a source there
.venv/bin/aero app --port 9000 --no-open
.venv/bin/aero serve                  # same app, with the newest recording already replaying
.venv/bin/aero serve --live --region nyc --radius 150
.venv/bin/aero app --host 0.0.0.0 --token "$(openssl rand -hex 24)"   # beyond loopback: every API call authenticated
```

## Pages

| Page | What it is for |
|---|---|
| Home | One-click **Show me America live** (OpenSky over the contiguous states, ~5,000 aircraft per poll) or **Replay the newest recording**; otherwise pick a source: replay (speed, demo controls) or go live with a grouped picker: whole country, continent, US hubs, international hubs, global feeds. Poll interval and radius default per choice. |
| Flights | Every aircraft in the picture as a dense grid: callsign, operator, type and class, flight phase, nearest airport, altitude, speed, track, vertical speed, squawk, source, trust, worst finding, fix age. Dropdown filters for operator, operator category, type class, phase, airport, altitude band, finding severity and source; sortable columns; CSV export; click for the full record and findings. |
| Airports | 132 North American airports with live activity: aircraft within 40 nm, on ground, departing, arriving (and on final), terminal, overhead, holds, emergencies, findings, FAA ground stops / delay programmes / closures (public FAA NAS status feed, refreshed every 5 min in live mode), METAR. Click for the airport's flights and weather. |
| Operators | Airlines, regionals, cargo, business, GA, military: fleet in the picture, airborne / ground, mean altitude, top types, phase mix, integrity compliance, findings, worst severity; aircraft-type table alongside. |
| Audit log | Append-only record of every source change, injection, settings edit and job (user or system), filterable and exportable. |
| Live picture | Canvas-rendered map that stays smooth with 10,000 aircraft; colour by findings, altitude, speed, or trust (legend switch); hover for a tooltip, click for the drawer; rings mark emergencies, injections, and the selection; a **?** button explains the picture. KPI strip, Findings / Safety / Security / Operations panels, demo buttons, search box. |
| Findings | Every finding this session, filterable by severity, rule, and text; click for evidence and the full playbook; export CSV. |
| Risk | Register re-scored from this session's evidence, threat coverage with measured recall, holding cost. |
| Reports | Generate a report from the running session or from any recording; browse and view past reports (HTML, Markdown, JSON). |
| Data & model | Capture live traffic to a recording, see the inventory, replay / audit / evaluate any recording, train the anomaly model, run the injected-scenario evaluation, retention pruning, job history with logs. |
| Settings | Demo mode, retention, alert log and webhook, model and watchlist paths; every detection threshold, applied live and written to `aero.toml`. |
| Help | Rule catalogue with plain-language meanings, playbooks, and the full documentation rendered in-app. |

Sources can be started, stopped, and switched at any time from Home, the Data page, or the top
bar; long tasks run as background jobs with progress and logs and survive page changes.

## Security of the local app

A server on 127.0.0.1 is reachable from every web page you have open. The app therefore validates
the `Host` header (DNS rebinding), requires a per-process token in `X-Aero-Token` on every POST
together with same-origin `Origin` / `Sec-Fetch-Site` and a JSON content type (CSRF), serves a
strict Content-Security-Policy with no inline script, confines every path parameter to the
project's data directories, accepts only `http(s)` webhooks, and loads a model only when its
SHA-256 matches `models/registry.json`. Binding beyond loopback needs `--token` (then every API
call carries it; the page asks once) or an explicit `--allow-unauthenticated`. Details and the
threat table: [SECURITY.md](../SECURITY.md); tests: `tests/test_app_security.py`.

## Auditability

- **Audit log** (`data/app/audit.jsonl`): hash-chained. Each entry has `seq`, `prev` (SHA-256 of
  the previous entry) and `hash`. The Audit log page shows **CHAIN VERIFIED** or the first broken
  line; `aero log verify` does the same from the shell; `GET /api/v1/audit/verify` for scripts.
- **Reports**: every report carries a provenance block (tool version, git commit, input recording
  and its hash, model hash and registry status, evaluation hash, threshold overrides) and a
  `<name>.manifest.json` with the SHA-256 of each file. **verify** on the Reports page and
  `aero log verify-report <manifest>` re-hash them.
- **Audible alerts**: `SND` in the header cycles off, tones, voice; only new high and critical
  findings sound, never the backlog.
- **Demo tour**: `TOUR` runs the eight scripted injections with narration in the banner; every
  injection is logged with actor `tour`.

## Terminal chrome

- **Command line** (top left, or press `/`): mnemonics `HOME LIVE FLT AIRP OPS FIND RISK RPT DATA LOG SET HELP`, plus
  `STOP`, `USA` (start the nationwide live feed), `TOUR` (scripted demo) and `SND` (audible alerts). Arguments narrow the view: `FLT AAL`, `FLT B738`,
  `AIRP JFK`, `FIND SEC-010`, `FIND HIGH`, `OPS cargo`, `LOG inject`.
- **Function keys** F1 to F8 jump to Help, Live, Flights, Airports, Operators, Findings, Risk, Audit log.
- **Ticker**: the latest findings scroll under the header; hover to pause.
- **Status bar**: aircraft, findings, and departures / arrivals / cruisers in the picture.

## The ecosystem model

Every aircraft is enriched (`aero_audit/ecosystem.py`) with an operator from its callsign designator
(`knowledge/airlines.py`), an aircraft type and class (`knowledge/types.py`), the nearest of 132
airports within 40 nm (`knowledge/airports.py`), and a flight phase from altitude above field,
vertical rate, and distance: ground, departure, climb, cruise, level, descent, arrival, approach,
pattern, terminal. Airport, operator, and type tables are rebuilt on every poll; FAA programmes are
joined by IATA code. All of this is offline reference data except the FAA feed and METARs.

## Nationwide and continental feeds

| Choice | Feed | How it works | Notes |
|---|---|---|---|
| `conus` | OpenSky | one bounding box 24-50N, 125-66W per poll, ~4,900 aircraft | 4 API credits per poll; anonymous accounts get ~400 a day, so the default is one poll a minute (about 100 minutes of national coverage per day). OpenSky credentials in `.env` raise the quota. |
| `americas` | OpenSky | one box from Tierra del Fuego to the Arctic | same cost as `conus`; larger payloads |
| `usa-hubs` | adsb.lol | 15 hubs at 250 nm polled in turn (Seattle to Miami) | no daily quota; each hub revisited every ~150 s at a 10 s interval, so one-off kinematic checks have a longer clock (see docs/THREAT_MODEL.md) but integrity fields are present |
| `world-hubs` | adsb.lol | 8 major hubs worldwide in turn | same trade-off |

Groups are defined in `aero_audit/config.py` (`GROUPS`); add a group by listing region keys.

## Architecture (for expanding it)

```
browser  ── static/index.html + app.css + app.js (router, store, pages) + live.js (map page)
   │  JSON over HTTP, polled every 3 s
server   ── web/app.py       App: routes (@router.route), settings, reports, docs, job registry
            web/router.py    tiny pattern router for the stdlib server
            web/sources.py   SourceManager: replay / live threads, engine construction, METAR loop
            web/state.py     LiveState: engine + latest batch + trails + events + demo injections
            web/jobs.py      JobManager: threads, progress, logs, persisted history (data/app/jobs.json)
            web/security.py  Guard: Host / CSRF / Origin checks, security headers, path confinement
            web/audit.py     AuditLog: hash-chained append-only record + verify
            web/tour.py      DemoTour: scripted injections on a timeline
engine   ── audit/engine.py and everything below it (rules, ML, trust, policy, risk)
```

- **API v1** lives under `/api/v1/…` and is the only contract the front end uses. `GET /api/v1/app`
  is the health and status call; `GET /api/v1/state` is the live snapshot.
- **Add an endpoint**: a function decorated with `@router.route("GET", "/api/v1/thing/{id}")` in
  `web/app.py`; it receives `(app, req)` with `req["params"]`, `req["query"]`, `req["body"]` and
  returns a JSON-able object, `(object, status)`, or `(bytes, content_type)`.
- **Add a background task**: a function `(job, params) -> result` registered in `App._job_types`;
  call `job.say()` for log lines, set `job.progress`, check `job.stop` to support cancellation.
- **Add a page**: an entry in `pages` in `static/app.js` with `render(el)` and an optional
  `tick(app, state)` called every 3 s; add a link in `index.html`'s nav.
- **Add a source type**: a `start_*` method on `SourceManager` that builds a `LiveState` and a
  daemon thread calling `state.ingest(batch)`.
- **State on disk**: `data/app/settings.json` (app settings, last source), `data/app/jobs.json`
  (finished jobs), `data/app/inventory.json` (recording summaries keyed by file mtime),
  `data/app/audit.jsonl` (hash-chained audit log), `aero.toml` (threshold overrides),
  `data/recordings/` (captures, `.jsonl` or `.jsonl.gz`), `data/samples/` (bundled, read-only),
  `reports/` (reports and manifests), `models/` (model, card, registry, evaluation).

## Where it can go next

- Several concurrent sources (one per region) with a region switcher; `SourceManager` already
  isolates each source's state and threads.
- Swap the stdlib server for FastAPI or Starlette when async endpoints or WebSockets are wanted;
  the route functions are framework-agnostic.
- Authentication and multi-user roles once it leaves a single desk; persist findings and jobs in
  SQLite or Postgres instead of JSON files.
- Package as a desktop app (PyInstaller, or Tauri around the same static front end).
- Alert integrations (Slack, Teams, PagerDuty) through `alerts.py` sinks and the Settings page.
- Fine-tuned aerial detector for the apron panel; receiver-level feeds for provenance.
