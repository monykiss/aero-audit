# Holistic plan: air and space navigation compliance, risk, study and governing

*Private branch. Delimited on 2026-09-10 after a survey of NASA, NASA-AMMOS, JPL, MIT Lincoln
Laboratory, EUROCONTROL and open aviation and astrodynamics repositories.*

## 1. Delimitation

**Purpose.** One bird's-eye view over how aircraft and spacecraft are observed, how those
observations are trusted, which rules apply, what the risks are, what has been measured, and who
owns what. Everything sits on evidence the toolkit already produces or can reproduce.

**In scope**

| Domain | Status | What "compliance, risk, study, governing" mean here |
|---|---|---|
| Air: surveillance integrity | active | ADS-B/Mode S physics, integrity minimums, identity, stream health, corroboration; measured recall; threat catalogue; register |
| Air: operations and ecosystem | active | Holding, level busts, coverage, airports, operators, FAA programmes, apron capacity; impact model |
| Space: open assets | active | NASA-3D-Resources and the NASA Image and Video Library with integrity and licence provenance |
| Space: launch and ascent | scaffold | Telemetry plausibility rules, footage frames, caption milestones; inputs supplied as files |
| Space: orbital operations | planned | TLE propagation, CCSDS orbit and conjunction messages, conjunction screening, debris compliance |
| Air: UAS, detect-and-avoid, UTM | planned | Well-clear metrics from NASA DAIDALUS/WellClear, encounter-model risk classes, UTM API conformance |
| Earth observation: crisis overlays | scaffold | Flood, fire and disaster extents (Crisis Mapping Toolkit lineage) intersected with airports and hubs; relief-operation coverage |

**Out of scope, by decision**

- Anything active: transmitting, commanding, or influencing aircraft, ATC, launch or spacecraft systems.
- Real-time detect-and-avoid decisions; the DAA work is offline metrics on recorded encounters.
- Reimplementing CCSDS stacks, flight software or mission control; adopt formats and patterns, consume outputs.
- Proprietary or paywalled feeds; every source stays keyless or credential-optional and licence-clear.
- Publishing the space and UAS material before licence questions are settled and an upstream home exists (policy P-08).

**Four pillars, one evidence base**

| Pillar | Object | Where it lives | Checkable by |
|---|---|---|---|
| Compliance | standards library, controls with typed evidence | `governance/standards.py`, `governance/controls.py` | `aero gov controls`, `validate()` in tests, `docs/generated/CONTROLS.md` |
| Risk | unified register: air rows evidence-adjusted, space and UAS rows residual from control status | `governance/register.py` on top of `risk/register.py` | `aero gov risks`, `aero risk assess` |
| Study | registry of reproducible analyses with provenance; five run today | `governance/studies.py` | `aero gov run-study`, `reports/studies/` |
| Governing | policies, owners, cadences, posture index | `governance/posture.py`, `POLICIES` | `aero gov posture`, `/api/v1/governance`, the GOV page |

## 2. Landscape: what exists, what we take

Verified on 2026-09-10 through the GitHub API (stars and licences as listed there; NOASSERTION means a
custom licence such as the NASA Open Source Agreement, which we do not vendor, only learn from).

| Repository | Stars | Licence | What it is | What this programme takes from it |
|---|---|---|---|---|
| nasa/daidalus | 85 | NOSA | Detect-and-avoid alerting logic with dynamic well-clear | The well-clear definitions and alert levels for the UAS domain's metrics; use as the reference implementation, never re-derive the maths (C-11, ST-07) |
| nasa/WellClear | 54 | NOSA | Well-clear boundary models for UAS in the NAS | Parameter sets and boundary semantics for encounter scoring |
| nasa/icarous | 177 | NOSA | UAS autonomy architecture (geofencing, DAA, planning) | Separation of concerns: monitors, resolvers, planners; geofence containment via PolyCARP |
| nasa/utm-apis | 63 | - | OpenAPI documents for NASA's UTM project | Contract-first conformance checking (C-12, ST-09) |
| nasa/DANTi | 10 | - | DAA display for manned aviation | Alerting presentation conventions for the Live page's separation screen |
| nasa/openmct | 13,115 | NOSA | Web mission-control framework | Telemetry object and timeline model; plugin architecture is the template for the app's domain pages |
| nasa/hermes | 50 | Apache-2.0 | Lightweight spacecraft commanding and telemetry framework | Packet-to-dictionary decoding pattern for a future live launch telemetry source (C-08) |
| NASA-AMMOS/AIT-Core | 56 | MIT | AMMOS Instrument Toolkit: telemetry dictionaries, CCSDS packets | Telemetry dictionary format and CCSDS packet handling for the space-launch domain |
| nasa/cFS (HS app) | 1,494 | Apache-2.0 | Core Flight System; Health and Safety application | Health-and-safety monitoring pattern: watchdogs, event escalation; mirrors our stream-health rules |
| nasa/fprime | 11,732 | Apache-2.0 | Flight software framework | Component/port discipline and the assurance evidence NPR 7150.2 expects (C-31) |
| nasa/CryptoLib | 168 | NOSA | CCSDS Space Data Link Security implementation | The expectation that space links are authenticated; our "ADS-B has no crypto" argument in space terms (C-32) |
| nasa/GMAT | 100 | Apache-2.0 | General Mission Analysis Tool | Reference trajectories for validating conjunction screening (C-09) |
| nasa/fmdtools | 59 | NOSA | Resilience modelling and assessment | Function-model fault propagation as the method for the register's residual reasoning |
| nasa/progpy | 131 | NOSA | Prognostics framework | Degradation models for feed health and receiver ageing (future OPS rule) |
| nasa/trick | 167 | NOSA | Simulation environment | Scenario injection discipline; our `aero evaluate` is a small cousin |
| NASA-AMMOS/slim | 35 | Apache-2.0 | Software Lifecycle Improvement and Modernization guides | Repository governance templates: security, CI, docs, contributing; the checklist behind policy P-06 |
| NASA-AMMOS/plandev | 128 | MIT | Spacecraft modelling and planning framework | Activity and constraint model for mission-ops governance studies |
| NASA-AMMOS/MMGIS, 3DTilesRendererJS | 231 / 2,457 | Apache-2.0 | Multi-mission GIS; 3D Tiles renderer | Future geospatial and 3D views of NASA-3D assets and trajectories |
| nasa/NASA-3D-Resources | 3,779 | NOSA | Models, textures, imagery | The asset domain; catalogue and integrity tooling is our candidate upstream contribution |
| nasa/CrisisMappingToolkit | 207 | Apache-2.0 | NASA Ames flood-extent algorithms (MODIS, SAR, Landsat) on Google Earth Engine; XML domain specs | Crisis extents as GeoJSON into ST-11 / C-34; the configurable domain-specification idea; algorithms cited, not vendored (needs an Earth Engine account and PyQt4) |
| sksalahuddin2828/NASA | 234 | none ("educational, don't sell") | Personal pygame solar-system and TLE orbit visualisers | Reviewed, not adopted: no licence, unmaintained since 2023; the intent (TLE orbit visualisation) is served by phase 3 with python-sgp4/skyfield |
| NASAWorldWind/WorldWindJava | 790 | NOSA (custom) | NASA WorldWind Java SDK: 3D virtual globe for desktop apps; last push 2024 | Reference for globe rendering (terrain, layers, picking); we stay web-native and use MMGIS / 3D Tiles as the web analogues; not vendored |
| corincerami/mars-photo-api | 399 | GPL-3.0, archived | Rails wrapper around the NASA Mars Rover Photos API | Not adopted; the underlying `api.nasa.gov` rover-photos endpoint (keyless with DEMO_KEY) is a planned space-assets source with the same provenance sidecars |
| nasa/Common-Metadata-Repository | 396 | Apache-2.0 | Earth-science metadata catalogue (UMM models, granule/collection search) | The model for a metadata registry over our recordings, assets and reports: collection/granule split, provenance fields, search by time and space (phase 7 data governance) |
| nasa/cumulus | 304 | NOSA | Earthdata ingest framework: workflows, provenance, granule lifecycle | Workflow-with-provenance pattern for `aero` jobs; retention and reconciliation reports as the model for `aero data` |
| nasa/opera-sds-pcm | 31 | Apache-2.0 | OPERA science data system: product control and management for remote-sensing products | Product-control discipline (job specs, PGE versioning, product provenance) for study outputs; a source of surface-water and disturbance products for the crisis domain |
| nasa/spacewasm | 1,553 | Apache-2.0 | Flight-compliant WebAssembly interpreter (JPL) for on-board code | Out of scope for analysis; noted as the assurance reference for sandboxed on-board logic (C-31 context) |
| nasa/HDTN, nasa-jpl/ION-DTN | 146 / 140 | Apache / NOSA | Delay-tolerant networking | Out of scope; noted so nobody re-plans it |
| openskynetwork/opensky-api | 466 | GPL-3.0 | OpenSky REST bindings | Already a feed; bindings not vendored (licence) |
| wiedehopf/readsb, flightaware/dump1090 | 672 / 1,141 | custom / custom | ADS-B decoders | Receiver-level provenance for the next corroboration step |
| junzis/pyModeS | 668 | GPL-3.0 | Mode S / ADS-B decoder | Message-level checks (CRC, type codes) if raw frames are ever ingested; kept at arm's length (GPL) |
| xoolive/traffic | 512 | MIT | Air-traffic analysis toolbox | Trajectory analytics patterns; candidate dependency for studies |
| euctrl-pru/HexAeroPy, trrrj | 5 / 16 | custom | Runway, taxiway and stand inference; trajectory analysis | Surface-movement studies for the operations domain |
| mit-ll/em-core, mit-ll/air-risk-class | 1 / 10 | BSD-2 | Aerospace encounter models; ASTM-based collision risk classes | Encounter-model methodology and risk classes (C-21, ST-08) |
| brandon-rhodes/python-sgp4, skyfielders/python-skyfield | 470 / 1,765 | MIT | SGP4 propagation; astronomy | Orbit propagation for conjunction screening (C-09, ST-06) |
| poliastro/poliastro | 1,013 | MIT | Astrodynamics (archived 2023) | Reference only |
| open-space-collective/ccsds-data-messages | 0 | Apache-2.0 | CCSDS ODM parser and generator | Candidate for ODM/CDM ingestion; evaluate before adopting |

## 3. Target architecture

```
                 domains: air-surveillance · air-operations · space-assets · space-launch · space-orbital · uas-utm
                 ┌──────────────────────────────────────────────────────────────────────────────┐
 evidence base   │ rules (SEC/OPS/SAF/ML/SPC) · evaluation scenarios · corroboration · manifests │
                 │ audit chain · model registry · licences · tests · CI · studies               │
                 └───────┬───────────────────┬──────────────────┬───────────────────┬──────────┘
                    compliance             risk               study             governing
                 standards + controls   unified register   study registry   policies · owners · cadence
                 typed evidence         residual by status  provenance       posture index
                         └───────────────────────┴──────────────────┴───────────────────┘
                                          aero gov · /api/v1/governance · GOV page · docs/generated
```

The layer never invents evidence: every control lists rule ids, tests, artefacts, commands,
workflows or modules, and `validate()` fails the test suite if a reference dangles. The posture
index is a weighted sum of control implementation (40%), standards touched (20%), share of risks
at low or medium residual (20%), runnable studies (10%) and evidence freshness on disk (10%).

## 4. Phases

| Phase | Outcome | Acceptance |
|---|---|---|
| 0. Scaffold (this branch) | Governance package, unified register, study registry with five runnable studies, posture CLI/API/page, generated docs | `tests/test_governance.py` green; `aero gov posture` renders; controls validate |
| 1. Space assets to training data | Render NASA 3D models from many viewpoints; pair with library imagery; fine-tune the detector; footage detections become real | **2026-09-15**: dataset pipeline (library + 3D previews, hashed, attributed, deterministic splits), scene classifier with card and registry gate, ultralytics fine-tune scaffold. **Later 2026-09-15**: numpy OBJ renderer for multi-view training images (`aero space render`). **2026-09-16**: mesh loaders for STL, GLB (Draco), 3DS, LightWave (607/622 NASA models); renders of real NASA models; YOLOv8n-cls fine-tune on CPU (top-1 0.905 on renders, 2 classes) registered with a card. **2026-09-17**: real NASA-library dataset (160 images, 4 classes): histogram baseline 52.5%, YOLOv8n-cls 77.5% top-1 on held-out real images, both registered. Open: larger classes, a second-source hold-out, GPU run |
| 2. Live launch telemetry | Packet or overlay source into the SPC rules (AIT-Core dictionary pattern, hermes-style decoding); milestone timing vs published profile | A recorded NASA launch audited end to end with provenance; SPC precision measured with injected faults |
| 3. Orbital operations | TLE ingest (CelesTrak), SGP4 propagation, CDM parser, conjunction screening with Pc; debris-rule checklist | **First cut 2026-09-10**: keyless elements, SGP4 screen, ORB-001..003, ST-06 runnable. **Second cut 2026-09-15**: CCSDS CDM parser, 2D Pc with covariance rotation, ORB-004/005, ST-12, synthetic sample CDM; `sgp4` hash-pinned in the lock. **Third cut 2026-09-15**: CDM inbox (KVN + XML) with ledger and event trends, Space-Track client, debris checklist DEB-001..008 with lifetime model (ST-13). Domain now active for supplied inputs. **Later 2026-09-15**: scheduled intake (C-40), SPACE page, integration inventory (C-41); element-history manoeuvre and decay detection ORB-006/007 (ST-20) |
| 4. UAS and DAA | Encounters from recorded tracks scored with DAIDALUS well-clear; ASTM risk classes; UTM API conformance | **2026-09-15**: well-clear and alert levels (DO-365 Phase 1), encounter extraction with NMAC-proximate rates and lead time (DAA-001/002), schema-lite contract validator; ST-07/08/09 runnable; C-11/C-12/C-21 partial. **Later 2026-09-15**: density classes and observed risk ratio (DAA-003/004, ST-16), UAS page; domain active; encounter model with Monte Carlo NMAC estimates (ST-19) |
| 3b. Space environment and launch windows | NOAA space weather mapped to ICAO advisory effects with exposed traffic; launch windows joined to traffic near the pad | **2026-09-15**: `space/spaceweather.py` (SWX-001..005, C-38, ST-17), `space/launches.py` (LCH-001..003, C-39, ST-18), new `space-environment` domain, space-launch active with a keyless live source |
| 5. Software assurance | NPR 7150.2 classification of components; SLIM templates applied; SDLS expectations documented | **2026-09-15**: classification table with activities per class, SLIM checklist evaluated on the tree (docs/generated/ASSURANCE.md), SDLS expectations; C-31/C-32 partial. **Later 2026-09-15**: bidirectional traceability matrix (docs/generated/TRACEABILITY.md, C-42) with gaps closed to zero for rules, studies and standards. Open: practising the class-C reviews |
| 7b. Data governance registry | Metadata registry over recordings, assets, reports and study outputs modelled on CMR's collection/granule split, with cumulus-style reconciliation reports | **2026-09-15**: `aero data catalog build/search/reconcile` over 12 collections with hashes, time bounds and provenance pointers; ST-15; C-36 implemented |
| 7. Crisis overlays | Extents from CMT or Earth Engine exports intersected with airports, routes and live traffic; relief-flight coverage study | ST-11 on a real flood export; C-34 implemented; E01 residual falls |
| 8. Performance | Hot paths vectorised with scalar references kept and proven equivalent; bench suite and recorded numbers | **2026-09-15**: projection, rasteriser, screen, catalogue cache, page memo; `aero bench --suite space`; docs/PERFORMANCE.md |
| 6. Upstream | Catalogue and integrity tool offered to nasa/NASA-3D-Resources; library client published; branch becomes public | **2026-09-15**: standalone `scripts/nasa3d_catalog.py` (stdlib only) and the PR text in docs/UPSTREAM.md are ready; catalogue regenerated and verify run recorded 2026-09-16; the licence email is drafted in docs/UPSTREAM.md and waits on the user to send it (P-08) |

Open issues on nasa/NASA-3D-Resources that the catalogue tool answers directly (checked 2026-09-10): #44 "Miscategorization of a file" (our `kind_of` classification and subject grouping surface exactly this), #43 "LWO version missing images" (ST-04 reports models without a preview image); #17 "License" (closed) is the thread to cite when confirming terms. The first upstream offer should be a PR that adds a generated `CATALOG.json` plus a small script, referencing those issues.

## 5. Operating model

| Role | Owns | Cadence |
|---|---|---|
| Programme lead | scope, policies P-01/P-06/P-08, posture review | quarterly posture review; index and top residual risks |
| Data steward | feeds, retention, attribution, catalogue | monthly: prune, manifest verification, licence check |
| Security lead | app hardening, supply chain, secrets, audit chain | every release: CI evidence, CodeQL alerts zero, chain verified |
| ML lead | model release gate, evaluation refresh | per model: card, registry, holdout, injected-scenario evaluation |
| Operations lead | playbooks, triage SLAs, impact assumptions | quarterly SLA review; assumptions revisited with operator figures |

Every review consumes `aero gov posture` and the latest `reports/studies/`; decisions are recorded
in the audit chain by running them through the app or noted in `CHANGELOG.md`.

## 6. Risk taxonomy

Air rows keep their evidence-adjusted likelihoods (`aero risk assess`). Space and UAS rows carry
inherent scores from the survey and residuals bounded by the strongest control in place: an
implemented control removes 60% of inherent risk, a partial one 35%, a planned one nothing. That
is deliberately harsh: a planned control is a promise, not a mitigation, and the posture should
say so until it ships.

## 7. Study programme

Runnable now: ST-01 integrity by operator, ST-02 recall versus revisit, ST-03 telemetry
plausibility, ST-04 asset coverage, ST-05 holding cost by airport. Network: ST-10 corroboration.
Planned with named upstream methods: ST-06 conjunction trend, ST-07 well-clear rates, ST-08 risk
classes, ST-09 UTM conformance. Each result file carries inputs with hashes, the git commit and
the tool version.

## 8. Licensing notes

NASA Open Source Agreement (shown as NOASSERTION on GitHub) is not GPL-compatible and is not
vendored here; we adopt formats, parameters and patterns and cite the source. GPL libraries
(pyModeS, opensky-api) stay out of the dependency tree. MIT/Apache/BSD projects (sgp4, skyfield,
traffic, AIT-Core, em-core) are candidates for direct dependencies when their phase starts.

## Next actions (2026-09-17)

1. **You**: send the licence email in `docs/UPSTREAM.md`; decide the public shape in `docs/RELEASE_PLAN.md`.
2. **Data**: grow the scene dataset (100+ per class, a second-source hold-out) before any model labels a report.
3. **Ops**: run `aero space watch` under launchd (`ops/launchd/`) so the caches and ledger stay fresh without the app.
4. **Public main**: when the answer arrives, merge slice A (or everything) and release 0.7.0 with the 0.6.0 asset set.
