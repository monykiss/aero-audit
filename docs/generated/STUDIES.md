# Study registry (generated)

| Id | Study | Domain | Status | Inputs | Metrics | Adopts |
|---|---|---|---|---|---|---|
| ST-01 | ADS-B integrity compliance by operator | air-surveillance | runnable | recording (.jsonl / .jsonl.gz) | compliance per operator, fixes, aircraft | - |
| ST-02 | Detection recall versus revisit interval | air-surveillance | runnable | models/evaluation.json | recall per scenario, median TTD, median revisit | - |
| ST-03 | Launch telemetry plausibility | space-launch | runnable | telemetry CSV | findings by rule, max speed, max altitude | - |
| ST-04 | NASA-3D asset coverage | space-assets | runnable | data/space/nasa3d_catalog.json | assets by kind, subjects, models with preview | - |
| ST-05 | Holding cost by airport | air-operations | runnable | recording | holds, minutes, fuel, CO2, cost | - |
| ST-06 | Conjunction screening trend | space-orbital | runnable | TLE file (aero space conjunctions --group ...) | approaches under threshold, median element age, propagation errors | brandon-rhodes/python-sgp4, skyfielders/python-skyfield, open-space-collective/ccsds-data-messages |
| ST-07 | Well-clear violation rates | uas-utm | planned | surveillance recording, DAIDALUS parameters | violations per flight hour, alert lead time | nasa/daidalus, nasa/WellClear |
| ST-08 | Airborne collision risk classes | uas-utm | planned | surveillance recording | risk class distribution | mit-ll/air-risk-class, mit-ll/em-core |
| ST-09 | UTM API conformance | uas-utm | planned | captured exchanges, OpenAPI documents | conformance failures by endpoint | nasa/utm-apis |
| ST-11 | Airports inside a crisis extent | earth-crisis | runnable | GeoJSON extent | airports inside, airports near, major hubs affected | nasa/CrisisMappingToolkit |
| ST-12 | Conjunction data message assessment | space-orbital | runnable | CDM file (KVN) | Pc, miss distance, consistency | open-space-collective/ccsds-data-messages, nasa/GMAT |
| ST-10 | Cross-feed corroboration baseline | air-surveillance | needs-network | two live feeds | median separation, p95, disagreements | - |

Run one: `aero gov run-study ST-01 --recording data/samples/<file>.jsonl.gz`; results land in `reports/studies/` with provenance.
