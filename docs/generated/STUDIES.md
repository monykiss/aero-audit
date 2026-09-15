# Study registry (generated)

| Id | Study | Domain | Status | Inputs | Metrics | Adopts |
|---|---|---|---|---|---|---|
| ST-01 | ADS-B integrity compliance by operator | air-surveillance | runnable | recording (.jsonl / .jsonl.gz) | compliance per operator, fixes, aircraft | - |
| ST-02 | Detection recall versus revisit interval | air-surveillance | runnable | models/evaluation.json | recall per scenario, median TTD, median revisit | - |
| ST-03 | Launch telemetry plausibility | space-launch | runnable | telemetry CSV | findings by rule, max speed, max altitude | - |
| ST-04 | NASA-3D asset coverage | space-assets | runnable | data/space/nasa3d_catalog.json | assets by kind, subjects, models with preview | - |
| ST-05 | Holding cost by airport | air-operations | runnable | recording | holds, minutes, fuel, CO2, cost | - |
| ST-06 | Conjunction screening trend | space-orbital | runnable | TLE file (aero space conjunctions --group ...) | approaches under threshold, median element age, propagation errors | brandon-rhodes/python-sgp4, skyfielders/python-skyfield, open-space-collective/ccsds-data-messages |
| ST-07 | Well-clear violation rates | uas-utm | runnable | recording | violations per flight hour, NMAC-proximate pairs, median alert lead time | nasa/daidalus, nasa/WellClear |
| ST-08 | Encounter and NMAC-proximate rates | uas-utm | runnable | recording | encounters per flight hour, NMAC-proximate per flight hour | mit-ll/air-risk-class, mit-ll/em-core |
| ST-09 | UTM API conformance | uas-utm | runnable | OpenAPI document, captured exchange | conformance failures | nasa/utm-apis |
| ST-13 | Debris-mitigation checklist | space-orbital | runnable | mission JSON | checks passed / failed, estimated lifetime | nasa/GMAT |
| ST-14 | Scene classifier evaluation | space-assets | runnable | dataset manifest | accuracy, per-class precision/recall | - |
| ST-16 | Airspace density classes and DAA risk ratio | uas-utm | runnable | recording | cells per class per band, observed risk ratio | mit-ll/air-risk-class, ASTM F3442 |
| ST-17 | Space weather exposure of observed traffic | space-environment | runnable | SWPC product (sample bundled), recording (optional) | conditions per effect, exposed aircraft | NOAA SWPC |
| ST-18 | Traffic near launch pads during windows | space-launch | runnable | launch file (sample bundled), recording | aircraft inside during window, baseline outside window | TheSpaceDevs/Launch Library 2 |
| ST-19 | Encounter model Monte Carlo | uas-utm | runnable | recording | P(NMAC) unmitigated / mitigated, model risk ratio, NMAC per flight hour | mit-ll/em-core, ASTM F3442 |
| ST-20 | Element history: manoeuvres and decay | space-orbital | runnable | two or more element files | manoeuvre-scale changes, objects decaying within 30 days | CelesTrak, CCSDS 502.0-B |
| ST-15 | Data catalogue reconciliation | air-surveillance | runnable |  | added, removed, changed | nasa/Common-Metadata-Repository, nasa/cumulus |
| ST-11 | Airports inside a crisis extent | earth-crisis | runnable | GeoJSON extent | airports inside, airports near, major hubs affected | nasa/CrisisMappingToolkit |
| ST-12 | Conjunction data message assessment | space-orbital | runnable | CDM file (KVN) | Pc, miss distance, consistency | open-space-collective/ccsds-data-messages, nasa/GMAT |
| ST-10 | Cross-feed corroboration baseline | air-surveillance | needs-network | two live feeds | median separation, p95, disagreements | - |

Run one: `aero gov run-study ST-01 --recording data/samples/<file>.jsonl.gz`; results land in `reports/studies/` with provenance.
