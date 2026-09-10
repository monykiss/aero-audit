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
| Home | Pick a source: replay a recording (speed, demo controls) or go live (feed, region, radius, poll interval). Shows what is running and what is on the machine. |
| Live picture | Map of every tracked aircraft, KPI strip, and the Findings / Safety / Security / Operations panels. Demo buttons inject attacks. Click an aircraft for its drawer; use the search box for a callsign or ICAO address. |
| Findings | Every finding this session, filterable by severity, rule, and text; click for evidence and the full playbook; export CSV. |
| Risk | Register re-scored from this session's evidence, threat coverage with measured recall, holding cost. |
| Reports | Generate a report from the running session or from any recording; browse and view past reports (HTML, Markdown, JSON). |
| Data & model | Capture live traffic to a recording, see the inventory, replay / audit / evaluate any recording, train the anomaly model, run the injected-scenario evaluation, retention pruning, job history with logs. |
| Settings | Demo mode, retention, alert log and webhook, model and watchlist paths; every detection threshold, applied live and written to `aero.toml`. |
| Help | Rule catalogue with plain-language meanings, playbooks, and the full documentation rendered in-app. |

Sources can be started, stopped, and switched at any time from Home, the Data page, or the top
bar; long tasks run as background jobs with progress and logs and survive page changes.

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
