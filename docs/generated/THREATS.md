# Threat catalog and detection coverage (generated)

| ID | Threat | Tactic | Coverage | Detecting rules | Measured recall (aero evaluate) | L | S | L*S |
|---|---|---|---|---|---|---|---|---|
| T01 | Ghost aircraft injection | injection | partial | SEC-010, SEC-014, SEC-015, SEC-016, ML-001 | teleport 96%, ghost_perfect 0% | 2 | 4 | 8 |
| T02 | Position modification of a real aircraft | modification | partial | SEC-010, SEC-011, SEC-014, SEC-015, SEC-018 | teleport 96%, altitude_forge 88%, slow_drift 12% | 1 | 5 | 5 |
| T03 | Velocity / heading falsification | modification | covered | SEC-011, SEC-018, ML-001 | velocity_forge 76% | 2 | 3 | 6 |
| T04 | Emergency / hijack squawk spoofing | injection | covered | SEC-001, SEC-002, SEC-003, SEC-004, SEC-015 | squawk_hijack 100% | 1 | 5 | 5 |
| T05 | Aircraft flooding (many ghosts) | injection | partial | SEC-016, SEC-017 | - | 1 | 5 | 5 |
| T06 | Jamming / message deletion | deletion | partial | SEC-017, OPS-001 | - | 1 | 5 | 5 |
| T07 | Replay attack | injection | partial | SEC-010, SEC-014, ML-001 | replay 100% | 1 | 3 | 3 |
| T08 | Identity spoofing / impersonation | misuse | partial | SEC-013, SEC-014, SEC-020 | - | 2 | 3 | 6 |
| T09 | Degraded integrity equipment / misconfiguration | integrity | covered | SEC-012 | integrity_degrade 100% | 4 | 2 | 8 |
| T10 | Upstream feed compromise or poisoning | supply-chain | partial | SEC-015, SEC-010, SEC-017 | - | 2 | 4 | 8 |
| T11 | Privacy misuse of surveillance data | privacy | partial | SEC-020 | - | 3 | 3 | 9 |
| T12 | Toolchain supply chain (dependencies, model weights) | supply-chain | gap | - | - | 2 | 4 | 8 |

Measured on `data/recordings/adsblol_nyc+ord+lax+lhr_20260909T220203Z.jsonl` (2026-09-09 23:25:40Z); median revisit 48 s. Recall for one-off manipulations rises with polling rate.

## T01 Ghost aircraft injection

Adversary transmits ES messages for an aircraft that does not exist, creating a phantom target on ATC displays, TCAS-like tools, or analytics.

- Capability required: SDR transmitter, line of sight to receivers (~$300 and public code).
- Impact: False alerts, ATC workload, forced separation manoeuvres, analytics poisoning.
- Mitigations: Multi-receiver / MLAT corroboration (TDOA physics cannot be forged from one antenna); Cross-feed corroboration (SEC-015); Primary radar fusion where available; New-address burst detection (SEC-016)
- References: Costin & Francillon 2012, 'Ghost in the Air(Traffic)'; Strohmeier et al. 2015 survey

## T02 Position modification of a real aircraft

Adversary overshadows or replays messages for a genuine ICAO address with altered position, so the aircraft appears somewhere it is not.

- Capability required: Higher-power transmitter than the aircraft at the receiver, or selective jamming + replay.
- Impact: Misleading surveillance picture, wrong conflict detection, misdirected response.
- Mitigations: Kinematic consistency checks; Cross-feed and MLAT corroboration; Track continuity checks against filed flight plan

## T03 Velocity / heading falsification

Only the airborne-velocity message is forged, so reported speed and heading disagree with what successive positions imply.

- Capability required: Same as T01; simpler because position messages are left alone.
- Impact: Corrupted trajectory prediction, mis-sequencing, analytics errors.
- Mitigations: Reported-vs-implied speed comparison (SEC-011); Sequence-level ML on tracks

## T04 Emergency / hijack squawk spoofing

Forged 7500/7600/7700 or emergency-status subfield for a real aircraft to trigger security response, or to mask a real emergency with noise.

- Capability required: SDR transmitter; trivial once T01 works.
- Impact: Law-enforcement / military response, airspace closure, alert fatigue.
- Mitigations: Always corroborate via voice/ACARS/CPDLC before response; Cross-feed check that the squawk is seen by independent receivers

## T05 Aircraft flooding (many ghosts)

Hundreds of fabricated targets saturate displays, receivers, and downstream systems.

- Capability required: SDR transmitter with message generator.
- Impact: Denial of surveillance, ATC overload, tooling crashes.
- Mitigations: New-address burst detection (SEC-016); Rate limiting / sanity caps in consumers; Receiver-level signal metrics (RSSI clustering) for future work

## T06 Jamming / message deletion

RF jamming or destructive interference removes real aircraft from the picture.

- Capability required: Jammer within range of receivers; illegal and detectable by RF monitoring.
- Impact: Loss of surveillance, safety degradation.
- Mitigations: Coverage-collapse detection (SEC-017); Independent receiver networks; Fallback to primary/secondary radar

## T07 Replay attack

Previously recorded genuine messages are re-transmitted later, possibly time-shifted.

- Capability required: Record-and-replay with an SDR.
- Impact: Stale or duplicated tracks, identity confusion.
- Mitigations: Timestamp / track continuity checks; Cross-feed corroboration

## T08 Identity spoofing / impersonation

A transponder is configured with another aircraft's ICAO address or a false callsign (deliberately or by maintenance error).

- Capability required: Physical access to avionics config, or a forged transmitter.
- Impact: Wrong aircraft tracked, registry mismatches, evasion of monitoring.
- Mitigations: Registry cross-check of ICAO24 vs registration vs type (future work); Watchlist (SEC-020); Duplicate-address detection (SEC-014)

## T09 Degraded integrity equipment / misconfiguration

Aircraft transmits positions with NIC/NACp/SIL below what the airspace requires; not an attack, but it lowers the trustworthiness of everything derived from it.

- Capability required: None (fault or non-compliance).
- Impact: Separation assurance degraded; false anomaly alerts downstream.
- Mitigations: Integrity thresholds per 14 CFR 91.227 / EU 1207/2011 (SEC-012); Trust ledger downgrades positions from low-integrity sources

## T10 Upstream feed compromise or poisoning

An aggregator or receiver feeding this tool is compromised, mis-merged, or fed bad data.

- Capability required: Compromise of a community feeder or API; MITM without TLS.
- Impact: Every downstream decision inherits the poisoned picture.
- Mitigations: Ingest from >= 2 independent feeds and corroborate (SEC-015); TLS to all providers; Record raw batches for forensic replay

## T11 Privacy misuse of surveillance data

Tracking of specific individuals' aircraft (VIP, law enforcement, medical) using the same open data this tool consumes.

- Capability required: None; the data is public.
- Impact: Personal safety, operational security of sensitive flights.
- Mitigations: Respect PIA/LADD programmes; do not publish tracks of protected aircraft; Watchlist as a *protection* list with restricted reporting; Data retention limits

## T12 Toolchain supply chain (dependencies, model weights)

Malicious or vulnerable dependencies, or tampered model weights, alter detections.

- Capability required: Package registry compromise, typosquatting, unsigned weights.
- Impact: Silent false negatives or code execution on the analyst host.
- Mitigations: Pinned lockfile (uv.lock); Verify weight checksums; Model card + regression tests; Least-privilege execution; no secrets in recordings