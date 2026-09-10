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
- [ ] Fine-tune on DOTA / iSAID / RarePlanes; evaluate on held-out apron imagery.
- [ ] Multi-frame tracking for stand occupancy and turnaround durations.

## Assurance
- [ ] CI: tests, ruff, `uv lock --check`, dependency audit, weight checksum.
- [ ] Signed releases; SBOM.
