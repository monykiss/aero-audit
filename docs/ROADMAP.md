# Roadmap

## Data
- [ ] OpenSky OAuth2 credentials for higher resolution; historical Trino access for months of data.
- [ ] Raw feeder ingestion (readsb) for receiver counts, RSSI, and message-level timestamps.
- [ ] FAA / OpenSky aircraft registry for ICAO24 <-> registration <-> type cross-checks (SEC-021).
- [ ] Continuous capture via launchd/cron with rotation and 30-day retention.

## Detection
- [ ] Track-level sequence model; flight-plan conformance where plans are available.
- [ ] GNSS-interference index: regional NIC/NACp degradation rate over time.
- [ ] Receiver-provenance corroboration (seen-by-N) once raw feeds are available.
- [ ] Runway / taxiway geometry for taxi-time, runway-occupancy, and go-around detection.

## Response and risk
- [ ] Slack / Teams / PagerDuty sinks with de-duplicated threads per aircraft.
- [ ] Case tracker for playbook outcomes; precision per rule feeds the scoring policy.
- [ ] Register owners and review cadence; export to GRC tools.

## Vision
- [ ] Fine-tune on DOTA / iSAID / RarePlanes; evaluate on held-out apron imagery (the 1.0 baseline: 2 of 12 parked transports matched on the sample, measured in every apron report).
- [ ] Multi-frame tracking for stand occupancy and turnaround durations.

## Assurance
- [x] CI: tests, ruff, `uv lock --check`, dependency audit, weight checksum (0.6).
- [x] Signed releases; SBOM (0.6.1); fuzzing of the parsers (0.7); contract snapshot and stability policy (1.0).
- [x] NPR 7150.2 classification with practised reviews (1.0); SDLS per-packet authentication status (1.0).
- [ ] A second reviewer: turn the self-reviews into peer reviews.

## Space (1.0 shipped; what is next)
- [ ] Reentry predictions (TIP) from a source without a redistribution agreement; until then the corridor is exposure, not prediction.
- [ ] TFR history: keep every product to measure traffic displacement per launch over time.
- [ ] Hand-curated labels and richer classes for the scene classifier; GPU fine-tune.
- [ ] Rocket-class detector for footage frames.
