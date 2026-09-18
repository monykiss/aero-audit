# Software assurance (generated)

## NPR 7150.2 classification

| Component | Paths | Class | Safety-related | Rationale | Required activities |
|---|---|---|---|---|---|
| Rules engine and scoring | `aero_audit/audit` | D | yes | Analysis producing safety and security findings people act on; no vehicle interaction. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Feed ingest and recording | `aero_audit/ingest, aero_audit/stream` | D | no | Data acquisition from public feeds; replayable evidence. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Anomaly model and evaluation | `aero_audit/ml` | D | yes | Model whose output ranks findings; gated by registry checksum and evaluation. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Local app and API | `aero_audit/web` | D | yes | Operator-facing; hardened guard, hash-chained audit log, provenance on reports. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Space assets and footage | `aero_audit/space (nasa3d, nasa_images, footage, dataset, classifier)` | E | no | Exploratory intake and scene classification; no operational decisions. | version control; a README stating purpose and limits |
| Launch telemetry and orbital analysis | `aero_audit/space (telemetry, orbital, cdm, cdm_inbox, debris)` | D | yes | Physics checks and conjunction assessment on supplied data; advisory to operators. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| UAS well-clear metrics | `aero_audit/uas` | D | yes | Offline DO-365 metrics on recordings; never real-time guidance. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Launch and reentry airspace | `aero_audit/ingest/tfr, aero_audit/space (airspace, reentry, mission), aero_audit/knowledge/spaceports` | D | yes | Published restrictions and decaying-object corridors joined to traffic; advisory after the fact, the NOTAM and the tracking authority stay authoritative. | version control; documented requirements and design; unit and regression tests run in CI; release records with provenance; coding standard checks |
| Governance layer | `aero_audit/governance` | E | no | Registry of controls, risks, studies and posture; documentation-grade. | version control; a README stating purpose and limits |

## SLIM repository checklist: 24 / 24 (100%)

| Id | Check | Status |
|---|---|---|
| SLIM-01 | README with purpose, quick start and licence | pass |
| SLIM-02 | OSI licence file | pass |
| SLIM-03 | Contributing guide | pass |
| SLIM-04 | Code of conduct | pass |
| SLIM-05 | Security policy and reporting path | pass |
| SLIM-06 | Changelog | pass |
| SLIM-07 | Code owners | pass |
| SLIM-08 | Issue templates | pass |
| SLIM-09 | Pull request template | pass |
| SLIM-10 | Continuous integration with tests | pass |
| SLIM-11 | Static analysis (CodeQL) | pass |
| SLIM-12 | Dependency updates (Dependabot) | pass |
| SLIM-13 | Secret scanning in CI | pass |
| SLIM-14 | Pinned dependencies with hashes | pass |
| SLIM-15 | GitHub Actions pinned to commit SHAs | pass |
| SLIM-16 | SBOM produced at release | pass |
| SLIM-17 | Release artifacts signed | pass |
| SLIM-18 | Pre-commit hooks | pass |
| SLIM-19 | Container image definition | pass |
| SLIM-20 | Generated documentation kept in sync by CI | pass |
| SLIM-21 | API contract published | pass |
| SLIM-22 | Observability endpoints | pass |
| SLIM-23 | Test suite present | pass |
| SLIM-24 | Supply-chain scorecard workflow | pass |

## Space data link security expectations (CCSDS 355.0-B)

- Spacecraft telemetry accepted for analysis should arrive over links protected with CCSDS Space Data Link Security (355.0-B): authenticated frames, replay protection via sequence numbers, key rotation per mission policy.
- Where a link is unauthenticated (ground-station relays, hobbyist decoders), treat the stream like ADS-B: physics plausibility (SPC rules), continuity, and corroboration before any operational conclusion.
- Record the security association identifier and authentication status alongside each ingested packet so findings can state which data was authenticated.
- Never store link keys in this repository or its data directories; SDLS key management stays with the mission's ground segment (reference implementation: nasa/CryptoLib).
