# The local app

`aero app` starts a local web application on `http://127.0.0.1:8787/` and opens your browser.
Nothing leaves your machine except requests to the public feeds you choose and map tiles.

```bash
.venv/bin/aero app                    # home screen, choose a source there
.venv/bin/aero app --port 9000 --no-open
.venv/bin/aero serve                  # same app, with the newest recording already replaying
.venv/bin/aero serve --live --region nyc --radius 150
```

## Pages

| Page | What it is for |
|---|---|
| Home | One-click **Show me America live** (OpenSky over the contiguous states, ~5,000 aircraft per poll) or **Replay the newest recording**; otherwise pick a source: replay (speed, demo controls) or go live with a grouped picker: whole country, continent, US hubs, international hubs, global feeds. Poll interval and radius default per choice. |
| Live picture | Canvas-rendered map that stays smooth with 10,000 aircraft; colour by findings, altitude, speed, or trust (legend switch); hover for a tooltip, click for the drawer; rings mark emergencies, injections, and the selection; a **?** button explains the picture. KPI strip, Findings / Safety / Security / Operations panels, demo buttons, search box. |
| Findings | Every finding this session, filterable by severity, rule, and text; click for evidence and the full playbook; export CSV. |
| Risk | Register re-scored from this session's evidence, threat coverage with measured recall, holding cost. |
| Reports | Generate a report from the running session or from any recording; browse and view past reports (HTML, Markdown, JSON). |
| Data & model | Capture live traffic to a recording, see the inventory, replay / audit / evaluate any recording, train the anomaly model, run the injected-scenario evaluation, retention pruning, job history with logs. |
| Settings | Demo mode, retention, alert log and webhook, model and watchlist paths; every detection threshold, applied live and written to `aero.toml`. |
| Help | Rule catalogue with plain-language meanings, playbooks, and the full documentation rendered in-app. |

Sources can be started, stopped, and switched at any time from Home, the Data page, or the top
bar; long tasks run as background jobs with progress and logs and survive page changes.

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
  (finished jobs), `data/app/inventory.json` (recording summaries keyed by file mtime), `aero.toml`
  (threshold overrides), `data/recordings/`, `reports/`, `models/`.

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
