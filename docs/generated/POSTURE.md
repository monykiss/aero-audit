# Governance posture (baseline, generated)

Governance index: **88%** (controls 82%, standards 97%, risk share low/medium 90%, studies runnable 93%). Basis: baseline (no session evidence).

## Domains

| Domain | Status | Rules | Controls implemented / partial / planned | Data sources |
|---|---|---|---|---|
| Air: surveillance integrity (ADS-B / Mode S) | active | 17 | 22 / 5 / 0 | adsb.lol /v2 (readsb JSON, NIC/NACp/SIL); OpenSky Network states/all; cross-feed corroboration |
| Air: operations, airports and ecosystem | active | 11 | 12 / 3 / 0 | adsb.lol / OpenSky; NOAA AWC METAR; FAA NAS status XML; bundled airport / operator / type tables; apron imagery |
| Space: open assets with provenance | active | 0 | 4 / 2 / 0 | github.com/nasa/NASA-3D-Resources (tree API + raw); images-api.nasa.gov / images-assets.nasa.gov; api.nasa.gov Mars Rover Photos (planned) |
| Space: launch and ascent | scaffold | 5 | 5 / 6 / 0 | telemetry CSV (t, speed, altitude); local footage; NASA library captions (.srt) |
| Space: orbital operations and conjunction | active | 13 | 3 / 5 / 0 | CelesTrak GP elements (keyless); CCSDS CDM 508.0-B files (KVN / XML); space-track.org cdm_public (free account); mission descriptions (JSON) |
| Earth observation: crisis overlays for operations | scaffold | 0 | 0 / 1 / 0 | GeoJSON crisis extents (from CMT / Earth Engine exports); bundled airport table |
| Air: UAS integration, detect-and-avoid, UTM | scaffold | 2 | 1 / 4 / 0 | surveillance recordings (ADS-B); UTM operator/USS APIs (OpenAPI); encounter models (planned) |

## Pillars

| Pillar | Implemented | Partial | Planned |
|---|---|---|---|
| compliance | 7 | 7 | 0 |
| risk | 4 | 1 | 0 |
| study | 2 | 3 | 0 |
| governance | 11 | 2 | 0 |

## Risk (residual, all domains)

| Id | Domain | Risk | Inherent | Residual |
|---|---|---|---|---|
| S05 | space-orbital | Conjunction not screened or screened on stale elements | 15 critical | 10 high |
| U01 | uas-utm | Well-clear violation undetected or alerted too late | 15 critical | 10 high |
| R08 | air-surveillance | Toolchain compromise silently degrades detection | 8 medium | 8 medium |
| S01 | space-launch | Launch telemetry stream manipulated, spliced or replayed | 12 high | 8 medium |
| R01 | air-surveillance | Surveillance picture poisoned by injected or modified ADS-B | 10 high | 7 medium |
| R07 | air-surveillance | Privacy harm from tracking sensitive flights | 9 medium | 6 medium |
| S02 | space-launch | Telemetry dropout hides an in-flight event | 9 medium | 6 medium |
| E01 | earth-crisis | Operations planned into a flooded or otherwise unusable airport | 8 medium | 5 medium |
| G01 | space-launch | Flight-software class and assurance level not established before use | 8 medium | 5 medium |
| R06 | air-surveillance | Upstream feed compromise propagates to every consumer | 8 medium | 5 medium |
| S06 | space-orbital | Mission design non-compliant with debris mitigation rules | 8 medium | 5 medium |
| S07 | space-orbital | Unauthenticated space data link accepted as truth | 8 medium | 5 medium |
| R05 | air-surveillance | Identity confusion (wrong aircraft attributed) | 6 medium | 4 low |
| U02 | uas-utm | UTM exchanges non-conformant with the published API contracts | 6 medium | 4 low |
| R03 | air-surveillance | Loss of surveillance through flooding or jamming | 5 medium | 3 low |
| R04 | air-surveillance | Decisions built on low-integrity positions | 8 medium | 3 low |
| R09 | air-operations | Operational inefficiency (holding, taxi, apron congestion) goes unmeasured | 8 medium | 3 low |
| R02 | air-surveillance | False security response triggered by spoofed emergency codes | 5 medium | 2 low |
| S03 | space-assets | Tampered or substituted external asset (model, texture, imagery) enters analysis or training | 6 medium | 2 low |
| S04 | space-assets | NASA media or NOSA terms breached (insignia, endorsement, attribution) | 4 low | 2 low |

By residual rating: {'critical': 0, 'high': 2, 'medium': 10, 'low': 8}

## Studies

| Id | Study | Domain | Status |
|---|---|---|---|
| ST-01 | ADS-B integrity compliance by operator | air-surveillance | runnable |
| ST-02 | Detection recall versus revisit interval | air-surveillance | runnable |
| ST-03 | Launch telemetry plausibility | space-launch | runnable |
| ST-04 | NASA-3D asset coverage | space-assets | runnable |
| ST-05 | Holding cost by airport | air-operations | runnable |
| ST-06 | Conjunction screening trend | space-orbital | runnable |
| ST-07 | Well-clear violation rates | uas-utm | runnable |
| ST-08 | Encounter and NMAC-proximate rates | uas-utm | runnable |
| ST-09 | UTM API conformance | uas-utm | runnable |
| ST-13 | Debris-mitigation checklist | space-orbital | runnable |
| ST-14 | Scene classifier evaluation | space-assets | runnable |
| ST-15 | Data catalogue reconciliation | air-surveillance | runnable |
| ST-11 | Airports inside a crisis extent | earth-crisis | runnable |
| ST-12 | Conjunction data message assessment | space-orbital | runnable |
| ST-10 | Cross-feed corroboration baseline | air-surveillance | needs-network |
