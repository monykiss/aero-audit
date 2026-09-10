# Architecture

aero-audit is a passive surveillance-auditing pipeline. It never transmits and never talks to
aircraft or ATC systems; it consumes public feeds and imagery and produces ranked, explainable
findings with response playbooks and a risk posture.

```
                 ┌──────────────┐
  adsb.lol ────► │              │      ┌────────────┐     ┌──────────────────┐
  OpenSky  ────► │  ingest/     │ ───► │ stream/    │ ──► │ data/recordings/ │  (JSONL, one batch per line)
  NOAA METAR ──► │  normalize   │      │ poller     │     └────────┬─────────┘
                 └──────────────┘      └────────────┘              │ replay
                                                                    ▼
   ┌────────────────────────────────────────────────────────────────────────────────┐
   │ audit/engine.AuditEngine                                                       │
   │   features/TrackStore ──► per-aircraft kinematics (implied speed, turn, climb) │
   │   audit/rules      (SEC / OPS / SAF, deterministic, control-referenced)        │
   │   engine stream checks (SEC-016 burst, SEC-017 collapse)                       │
   │   security/watchlist (SEC-020)                                                 │
   │   ml/anomaly       (IsolationForest, ML-001, with feature explanations)        │
   │   cooldown de-dup ──► policy.risk_score ──► security/trust ledger ──► alerts   │
   └───────────────────────────────┬────────────────────────────────────────────────┘
                                   ▼
             audit/report (Markdown + JSON) · risk/register.assess · playbooks

   imagery ──► vision/detect (YOLO, tiled) ──► vision/apron zones ──► OPS-VIS findings
   two feeds ──► security/corroborate (dead-reckoned comparison) ──► SEC-015
```

## Modules

| Module | Responsibility | Key types |
|---|---|---|
| `config.py` | Regions (12 hub presets, radius override, custom bbox), unit constants, `.env` settings | `Region`, `Settings` |
| `models.py` | Provider-independent schema | `StateVector`, `Batch`, `Source` |
| `ingest/adsblol.py` | readsb JSON -> `StateVector` incl. NIC/NACp/SIL, selected altitude, emergency field | `AdsbLolProvider` |
| `ingest/opensky.py` | OpenSky state vectors -> `StateVector`, unit conversion, optional OAuth2 | `OpenSkyProvider` |
| `ingest/metar.py` | NOAA AWC METAR fetch + one-line summary | `fetch_metars` |
| `ingest/replay.py` | Iterate JSONL recordings | `iter_recording` |
| `stream/poller.py` | Async round-robin polling, 429-aware back-off, JSONL recorder | `stream_batches`, `JsonlRecorder` |
| `features/tracks.py` | Rolling window of fixes per aircraft; derived kinematics | `TrackStore`, `TrackFeatures` |
| `audit/rules.py` | Deterministic rules with thresholds as module constants; `RULE_CATALOG` | `RULES`, `BATCH_RULES`, `RuleContext` |
| `audit/engine.py` | Orchestrates rules, watchlist, ML, stream checks, de-dup, scoring, trust, alerts | `AuditEngine` |
| `audit/policy.py` | Risk-scoring policy: severity x repeat factor x evidence quality x measured precision, ML capped | `risk_score` |
| `audit/report.py` | JSON + Markdown reports with executive summary and playbook pointers | `write_reports` |
| `audit/html_report.py` | Self-contained HTML rendering (KPI tiles, charts, ranked findings) | `render_html` |
| `ml/anomaly.py` | IsolationForest pipeline with imputation/scaling, explanations, persistence | `KinematicAnomalyModel` |
| `ml/train.py` | Grouped holdout training, model card, registry entry | `train` |
| `ml/evaluate.py` | Injected-scenario evaluation on real traffic: recall, time-to-detect, per-rule precision | `evaluate`, `SCENARIOS` |
| `tuning.py` | `aero.toml` threshold overrides applied at CLI start | `apply`, `effective` |
| `security/threats.py` | Threat catalog and coverage matrix (validated against rules by tests) | `THREATS` |
| `security/playbooks.py` | Triage / verify / escalate / contain per rule, with SLAs | `PLAYBOOKS` |
| `security/trust.py` | Per-aircraft trust score eroded by findings, restored by clean fixes | `TrustLedger` |
| `security/watchlist.py` | Detect / protect entries by address, callsign prefix, registration | `Watchlist` |
| `security/corroborate.py` | Cross-feed dead-reckoned position comparison | `corroborate` |
| `risk/register.py` | 5x5 register: precision-weighted evidence, Wilson lower-bound rates, inherent and residual scores | `RISK_REGISTER`, `assess` |
| `alerts.py` | JSONL and webhook sinks with severity threshold | `Alerter` |
| `impact.py` | Converts holding findings into minutes, fuel, CO2, and cost estimates | `estimate_holding_impact` |
| `vision/detect.py` | YOLO detection, tiled inference, NMS, annotation | `detect`, `detect_tiled` |
| `vision/apron.py` | Polygon zones, occupancy, capacity findings | `Zone`, `occupancy` |
| `synthetic.py` | Deterministic traffic generator with 8 injected anomaly types | `generate` |
| `web/state.py` | Thread-safe live state: engine, latest batch, trails, events, demo injections, JSON snapshots | `LiveState` |
| `web/server.py` | Stdlib HTTP server: JSON API + page; live, replay, and METAR source threads | `serve`, `start_live`, `start_replay` |
| `web/index.html` | Single-page dashboard (Leaflet map, panels, demo controls) | |
| `cli.py` | `aero` command groups: stream, audit, train, evaluate, corroborate, serve, security, risk, config, data, vision | |

## Data flow guarantees

- **Replayability.** Every live run records raw batches first; audits are re-runnable from the
  recording. Findings carry the evidence used, so a report is reproducible.
- **Provider independence.** Rules only see `StateVector`; adding a feed is one mapping function.
- **De-duplication.** A (rule, aircraft) pair fires at most once per cooldown window (120 s by
  default, longer for slow conditions); suppressed repeats still increment `occurrences`, which the
  scoring policy uses. A more severe finding for the same pair always passes (escalation bypass).
- **Explainability.** Deterministic rules cite thresholds and controls; ML findings carry the
  top standardized feature deviations.

## Scoring and risk math

- `risk_score = severity_weight x (1 + 0.5 log2(repeats)) x evidence_quality x precision`, with
  security findings from MLAT/TIS-B positions discounted (0.6 + 0.4 x source trust), rule
  precision from `models/evaluation.json` floored at 0.2, and ML findings capped at the MEDIUM
  weight so a model never outranks a HIGH hard rule.
- Register likelihood: expected true positives = hits x precision; rate per 1,000 aircraft is
  taken at the Wilson 95% lower bound before mapping to a band (+2 at >= 50, +1 at >= 10, -1 only
  with >= 500 aircraft and zero evidence). Residual = inherent x (1 - detective control
  effectiveness), where effectiveness comes from threat coverage (covered 0.6, partial 0.35, gap 0).

## Extension points

1. New feed: implement `Provider.fetch(region) -> Batch` and register in `ingest/__init__.py`.
2. New rule: decorate a function with `@rule("ID")` in `audit/rules.py`, add it to
   `RULE_CATALOG`, a playbook in `security/playbooks.py`, and (if relevant) a threat mapping.
   The test suite fails if a threat references a rule id that does not exist.
3. New scoring policy: edit `audit/policy.py`; invariants are pinned in `tests/test_policy.py`.
4. New alert channel: implement `AlertSink.send(finding)` in `alerts.py`.
5. New model: subclass or replace `KinematicAnomalyModel.findings()`; keep the `explain()`
   contract so ML findings remain reviewable.
