# Observability

Everything the process does is counted, timed and logged, with no dependencies beyond the
standard library, so the app can be scraped by Prometheus, tailed by a log shipper, probed by a
load balancer, and joined to an external tracer through request ids.

## Endpoints

| Path | What | Auth |
|---|---|---|
| `GET /healthz` | Liveness: version and uptime; always 200 while the process serves | open |
| `GET /readyz` | Readiness: static assets, writable state dirs, audit chain, model registry match, and (when a source is running) a fresh ingest within 300 s; 503 when any check fails | open |
| `GET /metrics` | Prometheus text exposition (counters, gauges, histograms) | token in remote mode |
| `GET /api/v1/observability` | KPIs, readiness, and a JSON snapshot of every metric with p50/p95/p99 | as the API |
| `GET /api/v1/logs?limit&level&event` | Tail of `logs/app.jsonl`, newest first | as the API |

Every response carries `X-Request-Id`; an incoming `X-Request-Id` or W3C `traceparent` is honoured
and stamped into every log line written while the request is handled.

## Metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `aero_http_requests_total` | counter | method, route, status | Requests; ids in paths are collapsed to `{id}` |
| `aero_http_request_seconds` | histogram | method, route | Request latency |
| `aero_http_denied_total` | counter | status | Refused by the guard (Host, CSRF, token, size) |
| `aero_ingest_batches_total` | counter | mode, provider, region | Batches through the engine |
| `aero_ingest_states_total` | counter | mode | State vectors ingested |
| `aero_ingest_feed_latency_seconds` | histogram | provider | Batch timestamp to arrival |
| `aero_engine_batch_seconds` | histogram | mode | Rule engine time per batch |
| `aero_findings_total` | counter | rule, severity | Findings raised |
| `aero_source_errors_total` | counter | kind | live, metar, faa loop errors |
| `aero_source_last_ingest_timestamp_seconds` | gauge | mode | Wall time of the last batch |
| `aero_source_tracked_aircraft` | gauge | | Aircraft in the latest batch |
| `aero_jobs_total`, `aero_job_seconds` | counter, histogram | type, status | Background jobs |
| `aero_jobs_running` | gauge | | Jobs in flight |
| `aero_alerts_sent_total` | counter | | Alerts delivered to sinks |
| `aero_feed_requests_total`, `aero_feed_request_seconds` | counter, histogram | host, outcome | Upstream feed calls |
| `aero_audit_entries_total` | counter | action | Audit chain entries written |
| `aero_tour_injections_total` | counter | kind | Demo tour injections |
| `aero_process_uptime_seconds`, `aero_process_rss_bytes`, `aero_process_threads`, `aero_build_info` | gauge | | Process |

Label cardinality is bounded by construction: routes are classified, hosts are feed hosts, rules
and severities are finite.

## Logs

`logs/app.jsonl` (rotating, 10 MB x 5): one JSON object per event with `ts`, `level`, `event`
and the event's fields. Events: `app.start`, `http.request` (errors, POSTs and slow requests
only; the rest is in metrics), `http.denied`, `http.error`, `ingest.batch`, `source.error`,
`feed.error`, `job.finish`, `tour.inject`. `AERO_LOG_STDERR=1` mirrors a text line to stderr;
`AERO_LOG_FILE` moves the file.

```bash
aero obs health                      # probes of the running app
aero obs metrics                     # KPIs; --raw for the exposition text
aero obs logs --level warning -f     # tail and follow the structured log
```

## Prometheus and Grafana

`ops/prometheus.yml` scrapes `host.docker.internal:8787/metrics` every 15 s;
`compose.observability.yaml` adds Prometheus and Grafana (provisioned datasource and the
`ops/grafana/aero-audit.json` dashboard: request rate and p95, ingest rate, engine time, findings
by severity, feed errors, readiness). Prometheus and Grafana bind to loopback only.

```bash
docker compose -f compose.yaml -f compose.observability.yaml up --build
# Grafana http://127.0.0.1:3000 (admin / admin on first start; change it), Prometheus http://127.0.0.1:9090
```

In remote mode set the scrape job's `authorization.credentials` to the app token (the metrics
endpoint needs `X-Aero-Token`; Prometheus sends it as a bearer only, so put the app behind a
reverse proxy that maps it, or run the scraper on the same host in loopback mode).

## Alert rules worth setting

- `rate(aero_source_errors_total[5m]) > 0` for 10 m: a feed or auxiliary loop keeps failing.
- `time() - aero_source_last_ingest_timestamp_seconds > 300` while a source is expected: stale picture.
- `histogram_quantile(0.95, rate(aero_engine_batch_seconds_bucket[5m])) > 2`: engine falling behind the poll interval.
- `increase(aero_http_denied_total[10m]) > 20`: something on the machine is probing the app.
- `increase(aero_findings_total{severity="critical"}[5m]) > 0`: page someone.
