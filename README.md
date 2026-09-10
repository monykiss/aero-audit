# aero-audit

AI/ML and computer-vision auditing toolkit for aviation operations and ADS-B security.
It streams real aircraft positions from public feeds, replays recordings, runs explainable
audit rules plus an unsupervised anomaly model, detects aircraft in imagery, and writes
ranked findings mapped to the controls they violate.

```
live feeds ──► normalize ──► JSONL recording ──► TrackStore (kinematics) ──► rules + ML + watchlist ──► findings
 adsb.lol       StateVector    (replayable)        implied speed, turn,        SEC/OPS/SAF, ML-001       │
 OpenSky                                            climb, holding             stream checks (burst,     ▼
 NOAA METAR                                                                    collapse)            risk score ──► trust ledger ──► alerts
                                                                                                        │
 two feeds ──► cross-feed corroboration (dead-reckoned) ──► SEC-015                                      ▼
 imagery ──► YOLO (tiled) ──► apron zone occupancy ──► OPS-VIS findings                    reports · playbooks · risk register · impact
```

## The app

```bash
.venv/bin/aero app                        # opens http://127.0.0.1:8787 in your browser
```

A local application: Home (choose a replay or go live with dropdowns), Live picture (map,
KPIs, findings, safety, security, operations panels, demo injections), Findings (filter, evidence,
playbooks, CSV), Risk, Reports (generate and browse), Data & model (capture, inventory, train,
evaluate, prune, job logs), Settings (thresholds applied live), Help (rules, playbooks, docs).
Sources start, stop, and switch at runtime; long tasks are background jobs. See
[docs/APP.md](docs/APP.md) for the pages and how to extend it, and [docs/DEMO.md](docs/DEMO.md)
for the demo script.

## Documentation

| Document | What it covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Modules, data flow guarantees, extension points |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Feeds, fields, rate limits, ADS-B integrity semantics, recording format |
| [docs/RULES.md](docs/RULES.md) | Every rule: trigger, thresholds, false-positive modes, controls, tuning |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Adversaries, why detection works without crypto, gaps and mitigations |
| [docs/COMPLIANCE_MAPPING.md](docs/COMPLIANCE_MAPPING.md) | ICAO / FAA / EASA / DO-260B, NIST CSF 2.0, SP 800-53, ISO 27001, AI RMF |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Capture, audit, alert, corroborate, triage loop, retraining, retention |
| [docs/IMPACT.md](docs/IMPACT.md) | Stakeholders, why now, quantified holding impact, security impact, limits |
| [docs/ML.md](docs/ML.md) | Anomaly model, vision baseline, training-data strategy, roadmap |
| [docs/APP.md](docs/APP.md) | The local app: pages, architecture, how to add endpoints, jobs, pages, sources |
| [docs/DEMO.md](docs/DEMO.md) | Demo script: what each panel means for safety and operations, the injections |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Data, detection, response, vision, assurance backlog |
| [docs/generated/](docs/generated/) | Threat matrix with measured recall, playbooks, risk register, rule ids rendered from code (`aero docs-build`) |
| `models/` | Model card, registry (provenance), evaluation results that feed risk scoring |
| [SECURITY.md](SECURITY.md) | Supply chain, data handling, vulnerability reporting |

## Quick start

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"      # core
uv pip install -e ".[vision]"                                   # + YOLO / OpenCV (large)
.venv/bin/aero providers                # health-check live feeds
.venv/bin/aero synth                    # offline practice data with injected anomalies
.venv/bin/aero audit --recording data/recordings/synthetic_nyc.jsonl
.venv/bin/aero stream --region nyc --seconds 120                # record live traffic
.venv/bin/aero audit --live --region lhr --seconds 90           # audit live, record too
.venv/bin/aero train data/recordings/*.jsonl                    # fit anomaly model
.venv/bin/aero audit --recording <file> --model models/kinematic_iforest.joblib
.venv/bin/aero weather nyc
.venv/bin/aero vision detect data/samples/apron_hohn.jpg --tile 320 --conf 0.10
.venv/bin/aero vision apron data/samples/apron_hohn.jpg --conf 0.10

# security and risk layer
.venv/bin/aero stream --region nyc,ord,lax,lhr --radius 250 --interval 12 --seconds 1500   # 4 hubs, ~3k aircraft/cycle
.venv/bin/aero corroborate --region nyc --radius 150 --seconds 100      # two feeds, SEC-015 on disagreement
.venv/bin/aero security threats                                         # threat catalog + detection coverage
.venv/bin/aero security playbook SEC-010                                # triage / verify / escalate / contain
.venv/bin/aero security watchlist-example && .venv/bin/aero audit --recording <file> --watchlist data/watchlist.example.json
.venv/bin/aero audit --live --alert-log logs/alerts.jsonl --alert-webhook https://hooks.example/x --alert-min-severity high
.venv/bin/aero risk register                                            # baseline 5x5 register
.venv/bin/aero risk assess data/recordings/*.jsonl                      # evidence-adjusted register + heat map
.venv/bin/aero impact data/recordings/*.jsonl                           # holding minutes -> fuel, CO2, cost
.venv/bin/aero data inventory                                           # what is on disk
.venv/bin/aero data prune --days 30                                     # retention (dry run; --apply to delete)
.venv/bin/aero docs-build                                               # regenerate docs/generated

# measured accuracy and tuning
.venv/bin/aero evaluate <recording> --model models/kinematic_iforest.joblib --targets 25   # inject 8 attack scenarios; recall, TTD, precision
.venv/bin/aero config init && .venv/bin/aero config show rules          # aero.toml threshold overrides
scripts/run_pipeline.sh                                                 # train -> evaluate -> audit -> assess -> impact -> docs
```

Every audit writes three files: `.json` (machine-readable), `.md` (executive summary, ranked findings,
playbook steps), and a self-contained `.html` for non-technical readers.

## How scoring and risk assessment are made accurate

An unsupervised detector has no accuracy until something is measured, so the toolkit closes the
loop between detection, ranking, and risk:

1. **Ground truth by injection.** `aero evaluate` perturbs a sample of genuine aircraft in a real
   recording with eight attack scenarios (teleport, velocity forgery, altitude forgery, replay,
   hijack squawk, GNSS-style integrity degradation, slow drift, perfect ghost) and measures recall,
   median time-to-detect, and per-rule precision against untouched aircraft. Two scenarios are
   known gaps by design and are reported as such. Results: `reports/evaluation_*.md`,
   `models/evaluation.json`.
2. **Precision-weighted ranking.** `risk_score = severity x (1 + 0.5 log2 repeats) x evidence
   quality x measured precision`, with security findings from MLAT/TIS-B positions discounted and
   ML findings capped at the medium weight ([policy.py](aero_audit/audit/policy.py)).
3. **Evidence-adjusted register.** Hits x precision give expected true positives; the rate per
   1,000 aircraft is taken at the Wilson 95% lower bound before it moves a likelihood band, so a
   handful of hits on a small sample cannot escalate a risk. Every risk carries inherent and
   residual scores, the latter from detective-control effectiveness derived from threat coverage
   ([register.py](aero_audit/risk/register.py)).
4. **Model that knows its regime.** Twelve kinematic features, separate IsolationForests for
   terminal and en-route traffic, scores calibrated to training percentiles, two-fix persistence
   before an ML finding is raised, grouped holdout by aircraft, a model card, and a registry with
   data provenance and checksums.
5. **Confirmation tiers.** Emergency squawks are unconfirmed on one fix and escalate on the second;
   escalations bypass the de-duplication cooldown. Impossible jumps on MLAT solutions are filed as
   data quality, not spoofing.
6. **Operator control.** `aero config init` writes `aero.toml`; every threshold in the rules,
   engine, policy, model, corroboration, and trust modules can be overridden, and unknown keys
   fail loudly. `aero data prune` enforces retention.

## Measured results (2026-09-09, two capture rounds)

Data captured in one session, all keyless public feeds, one poller per host:

| Recording | Provider | Coverage | Polls | Aircraft | Integrity compliance |
|---|---|---|---|---|---|
| four hubs A | adsb.lol | NYC, ORD, LAX, LHR at 250 nm | 94 | 3,819 | 98.9% of 44,377 fixes |
| four hubs B | adsb.lol | SFO, DFW, ATL, HND at 250 nm | 91 | 2,811 | 95.4% of 34,217 fixes |
| US Northeast box | OpenSky | 36-45N, 80-69W | 60 | 1,498 | n/a (no integrity fields) |
| US Southwest box | OpenSky | 30-42N, 125-108W | 40 | 1,412 | n/a |
| global military feed | adsb.lol `/v2/mil` | worldwide | 12 | 333 | 95.9% |
| earlier short captures | adsb.lol | NYC, LHR at 60 nm | 9 | 424 | 98.7% |

Total on disk: 210,211 state vectors from 7,790 unique aircraft (`aero data inventory`).

**Anomaly model.** 150,226 airborne feature rows from 6,155 aircraft, 12 features, separate
terminal and en-route pipelines, split by aircraft (29,951 holdout rows from 1,231 unseen aircraft).
Holdout flag rate 1.17% against a 1% contamination target. Card: `models/kinematic_iforest.md`;
provenance: `models/registry.json`.

**Measured detection (`aero evaluate`, 25 real aircraft perturbed per scenario)**

| Scenario | 20 s polling (OpenSky NE) | 48 s round-robin (adsb.lol four hubs) | Detecting rules |
|---|---|---|---|
| teleport (30 nm position replacement) | 96%, TTD 0 s | 96%, TTD 43 s | SEC-010 |
| velocity forgery (speed halved) | 68% | 76% | SEC-011, ML-001 |
| altitude forgery (+6,000 ft) | 96% | 88% | SEC-018, ML-001 |
| replay (fix re-sent under same address) | 100% | 100% | SEC-014, SEC-010 |
| hijack squawk 7500 | 100% | 100% | SEC-003 |
| GNSS-style integrity degradation | 100% | 100% | SEC-012 |
| slow drift (0.2 nm per poll) | 12%, known gap | 12%, known gap | corroboration needed |
| perfect ghost aircraft | 0%, known gap | 0%, known gap | corroboration needed |

Per-rule precision on the primary feed (findings on untouched aircraft counted as false positives):
SEC-003, SEC-010, SEC-014 at 1.00; SEC-011 0.91; SEC-018 0.74; ML-001 0.25. These numbers weight
the risk score and the register. Velocity forgery is bounded by the 150 kt mismatch floor: halving
the speed of a 250 kt aircraft stays under it. The two gaps are structural for single-feed
kinematics and are what `aero corroborate` exists for.

**Audits with the final model.** Across 9,964 aircraft-observations: zero critical findings and
exactly one high, a squawk 7500 on a descending airliner that lasted one poll between identical
normal codes and is reported as unconfirmed. No spoofing, ghost, flooding, or coverage-collapse
rule fired on civil traffic. Four hubs A: 899 findings (200 medium), four hubs B: 713 (85 medium).

**Cross-feed corroboration** (NYC 150 nm, 4 rounds): 1,626 matched comparisons between adsb.lol
and OpenSky, median dead-reckoned separation 0.02 nm, 95th percentile 0.10 nm, one disagreement.

**Military feed** (not used for training): 333 aircraft, 44 without flight ID, four impossible
MLAT "jumps" of up to 96 nm over sparse receiver terrain, filed as data quality.

**Holding impact** (`aero impact`, default assumptions): 30 airline holds, 267 observed minutes,
about 10.7 t fuel, 33.7 t CO2, and 26,700 EUR of delay cost, all floors.

**Risk register** (recordings audited separately plus the corroboration report): "surveillance
picture poisoned by injected or modified ADS-B" high inherent, medium residual; "decisions built on
low-integrity positions" high, likelihood 5 on 505 hits (43 per 1,000 at the Wilson lower bound);
everything else medium or low. Full table with heat map: `reports/risk_assessment_*.md`.

### Rule tuning that came out of reading the evidence

| Observation on real data | Change |
|---|---|
| TIS-B tracks carry NIC/NACp/SIL = 0 by design | SEC-012 scoped to ADS-B sources |
| Single-snapshot selected-altitude gaps are pending clearances | OPS-004 needs 3 fixes over >= 60 s; gaps > 1,000 ft are info |
| 154 of 190 "holds" were training circuits below 3,000 ft | OPS-002 gets altitude/speed floors; pattern work is OPS-003 |
| Every speed mismatch at the default tolerance was an MLAT military track | SEC-011 tolerance x2.5 for MLAT, x2 for TIS-B |
| Top ML anomalies were fixes separated by long gaps or taxiing aircraft | ML excludes dt > 120 s and altitude < 1,000 ft |
| 2% per-fix contamination flagged ~20% of aircraft | 1% default plus two-fix persistence within 10 min |
| Concatenating recordings in one engine looked like bursts and collapses | `risk assess` audits each recording separately |
| MLAT solutions jump 96 nm over Wyoming | SEC-010 on non-ADS-B sources is data-quality, medium |
| Whole-image YOLOv8n found none of 12 parked transports | Tiled inference (`--tile 320`) finds 4; fine-tuning is next |
| adsb.lol returns 429 from several clients at once | One client, round-robin regions, 429-aware back-off |
| LuLu / VPN extension blocked Python sockets while curl worked | Providers fall back to a curl transport |
| Departures from Salt Lake City (4,227 ft elevation) looked like 4,300 ft altitude forgeries because ground fixes were stored as 0 ft | No implied vertical rate across ground transitions; mappers never fabricate 0 ft |
| A live 7500 lasted one poll between identical normal codes | Emergency codes unconfirmed on one fix, escalate on the second; escalations bypass the cooldown |
| Feed position timestamps lag the batch, so the harness discarded the first perturbed fix | Detections attributed by batch index; recall rose from ~64% to ~96% on teleport |
| Round-robin recordings interleave regions | Target presence measured per region; stale re-reported fixes disqualified |
| Zero watchlist hits were lowering the privacy risk | Rules needing optional configuration are not register evidence; corroboration reports are |

## Data sources (all free, no key)

| Source | What | Notes |
|---|---|---|
| adsb.lol | readsb JSON incl. NIC/NACp/SIL integrity, selected altitude | community feed; HTTP 429 if polled < ~10 s or from several clients at once. Run one capture at a time, interval >= 15 s |
| OpenSky Network | state vectors, position source (ADS-B/MLAT/FLARM) | anonymous is rate-limited; OAuth2 creds in `.env` raise limits |
| NOAA AWC | METAR weather | context for ops findings |
| airplanes.live | (not wired) | requires emailing for API access |

## Audit rules

| Rule | Category | What it catches | Control reference |
|---|---|---|---|
| SEC-001/002/003 | security | squawk 7700 / 7600 / 7500 | ICAO Doc 4444, FAA AIM 4-1-20 |
| SEC-004 | security | emergency status subfield set | RTCA DO-260B |
| SEC-010 | security | kinematically impossible jump (spoof/injection) | FAA AC 20-165B, ICAO Annex 17 |
| SEC-011 | security | reported vs position-derived speed mismatch | RTCA DO-260B |
| SEC-012 | data-quality | NIC/NACp/SIL below rule-airspace minimums | 14 CFR 91.227(c) |
| SEC-013 | security | airborne, no flight ID | ICAO Doc 4444, FAA AC 90-114 |
| SEC-014 | security | one ICAO24 at two distant positions (ghost) | ICAO Annex 10 Vol III |
| OPS-001 | operations | surveillance coverage gap | ICAO Doc 9924 |
| OPS-002 | operations | airline-style holding (>= 3,000 ft, >= 150 kt; feeds the impact model) | ICAO Doc 4444, GANP/ASBU |
| OPS-003 | operations | low-altitude / low-speed orbiting (pattern work, survey, helicopter) | FAA AC 90-66C |
| OPS-004 | safety | level flight away from selected altitude | level-bust programmes |
| OPS-005 | operations | VFR code 1200 above FL180 | 14 CFR 91.135 |
| SAF-003 | safety | vertical rate beyond FOQA-style threshold | ICAO Annex 6 |
| ML-001 | ml | IsolationForest kinematic outlier, with top feature deviations | NIST AI RMF |
| OPS-VIS-001/002 | operations | apron zone over capacity / idle | ICAO Annex 14, A-CDM |

| SEC-015 | security | cross-feed position disagreement after dead reckoning | ICAO Doc 9924 |
| SEC-016 | security | burst of never-seen addresses (flooding indicator) | ICAO Doc 9924 |
| SEC-017 | security | coverage collapse (jamming / feed outage indicator) | ICAO Annex 10 Vol IV |
| SEC-020 | security | watchlist match (detect or protect mode) | organisation policy |

Thresholds live at the top of `aero_audit/audit/rules.py`. The ranking policy that decides
what an operator sees first lives in `aero_audit/audit/policy.py`. Every finding links to a
response playbook; every rule maps to the threats it detects; the risk register is re-scored
from observed evidence.

## Layout

```
aero_audit/
  config.py        regions, units, settings
  models.py        StateVector / Batch schema
  ingest/          adsblol, opensky, metar, replay
  stream/          async poller + JSONL recorder
  features/        TrackStore: per-aircraft kinematics
  audit/           rules, findings, policy, engine, report
  ml/              IsolationForest anomaly model + trainer
  vision/          YOLO detection (tiled), apron zone occupancy
  security/        threat catalog, playbooks, trust ledger, watchlist, cross-feed corroboration
  risk/            5x5 risk register with evidence-adjusted assessment
  alerts.py        JSONL / webhook alert sinks
  impact.py        holding -> minutes, fuel, CO2, cost
  docs_build.py    renders code-owned tables into docs/generated
  synthetic.py     traffic generator with injected anomalies
  cli.py           `aero` CLI
docs/              architecture, data sources, rules, threat model, compliance, operations, impact, ML, roadmap
tests/             pytest suite (runs offline)
```

## Ethics and legal notes

- ADS-B is an unencrypted public broadcast; receiving and analysing it is legal in most
  jurisdictions and is exactly what the free feeds exist for. This project is **passive**: it
  never transmits, never interacts with aircraft or ATC systems.
- Respect feed terms: poll politely, credit the providers, do not resell their data.
- Findings are *audit signals*, not accusations. A spoofing rule firing on a real feed most
  often means a receiver merge glitch, an MLAT outlier, or a transponder fault. Verify.
- Regulatory references are pointers for the auditor, not legal determinations.

## Roadmap ideas

- Fine-tune YOLO on aerial datasets (DOTA, iSAID, RarePlanes); the bundled sample shows why.
- Separate surface-movement model (taxi times, runway occupancy) from the airborne one.
- Sequence models (GRU / Transformer) over whole tracks instead of pairwise kinematics.
- Runway/taxiway geometry to score taxi times, runway occupancy, and go-arounds.
- Receiver-level provenance (multiple feeders) to corroborate or refute spoof candidates.
- A dashboard artifact with a live map and finding stream.
