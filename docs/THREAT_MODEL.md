# Threat model: ADS-B surveillance and this toolkit

## System under consideration

- **Assets.** The surveillance picture (who is where, doing what), the decisions built on it
  (separation, security response, operational KPIs), the recordings and reports this tool
  produces, and the analyst host running it.
- **Trust boundaries.** Aircraft transponder -> RF -> community receivers -> aggregator API ->
  this tool -> reports/alerts -> humans. Nothing before "this tool" is authenticated: ADS-B is a
  plaintext broadcast and the feeds are volunteer-run.
- **Adversaries.** Hobbyist with an SDR (capability: inject/replay near one receiver cluster);
  organised actor with multiple transmitters (flooding, targeted modification); insider or
  maintenance error (misconfigured transponder); compromised upstream feeder or dependency.
- **Out of scope.** Attacks on aircraft avionics, ATC systems, or GNSS itself (we observe their
  *effects*: GNSS spoofing shows up as NIC/NACp degradation and position jumps).

## Why detection is possible without cryptography

1. **Physics.** Consecutive position reports imply speed, climb, and turn rates. Forged
   messages that ignore the aircraft's real trajectory violate them (SEC-010/011).
2. **Redundancy.** Independent receiver networks see the same sky. A localised forgery is seen
   by one network's antennas but not the other's (SEC-015), and MLAT time-difference-of-arrival
   cannot be faked from a single transmitter.
3. **Self-reported integrity.** NIC/NACp/SIL are how the transponder admits it is unsure;
   GNSS spoofing and jamming degrade them before positions go visibly wrong (SEC-012).
4. **Population statistics.** Ghost floods and jamming change the *number* of aircraft in a
   region faster than real traffic does (SEC-016/017), and unusual kinematics stand out against
   a learned baseline (ML-001).

## Catalog and coverage

The authoritative table is generated from `aero_audit/security/threats.py` into
`docs/generated/THREATS.md` (`aero docs build`) and validated by `tests/test_security.py`.
Summary: 12 threats; 3 covered, 8 partial, 1 gap (toolchain supply chain). The partial
coverage is honest: most attacks are only *confirmed* by corroboration across feeds or by an
analyst following the playbook.

## Measured detection performance (2026-09-09)

`aero evaluate` perturbed 25 genuine aircraft per scenario in two real recordings. The detection
clock is the revisit interval: 20 s for a single OpenSky box, 48 s for the four-hub adsb.lol
round-robin.

| Threat | Scenario | Recall at 20 s | Recall at 48 s | Median time-to-detect |
|---|---|---|---|---|
| T01 / T02 position replacement | teleport 30 nm | 96% | 96% | first perturbed fix (0 s / 43 s) |
| T02 altitude modification | altitude +6,000 ft | 96% | 88% | first perturbed fix |
| T03 velocity falsification | speed halved | 68% | 76% | one revisit |
| T07 replay | old fix re-sent | 100% | 100% | first perturbed fix |
| T04 emergency-code spoofing | squawk 7500 | 100% | 100% | first perturbed fix (unconfirmed), confirmed on the second |
| T09 / GNSS spoofing signature | NIC/NACp/SIL degraded | 100% | 100% | first perturbed fix |
| T02 slow modification | drift 0.2 nm per poll | 12% | 12% | known gap |
| T01 consistent ghost | fabricated aircraft with plausible kinematics | 0% | 0% | known gap |

Precision on untouched traffic (primary feed): SEC-003, SEC-010, SEC-014 at 1.00; SEC-011 0.91;
SEC-018 0.74; ML-001 0.25. The generated matrix in `docs/generated/THREATS.md` carries these
numbers per threat, and the risk register weights evidence by them.

What the numbers say: message-level forgeries that break physics are caught on the first
affected fix; the two gaps are exactly the attacks that keep physics intact, which only
independent receivers (corroboration, MLAT) or receiver-level metadata can expose. Velocity
forgery recall is bounded by the 150 kt mismatch floor, chosen to keep precision above 0.9 on
real traffic; lowering it trades precision for recall, and `aero.toml` makes that an operator
decision.

## Detection gaps and the mitigation roadmap

| Gap | Why it matters | Planned mitigation |
|---|---|---|
| Single-receiver provenance is invisible through aggregator APIs | Cannot tell "seen by 8 receivers" from "seen by 1" | Consume raw feeder data (readsb `--net-api`) or providers exposing receiver counts / RSSI |
| No registry cross-check | Address/registration/type impersonation slips through | Load the FAA registry and OpenSky aircraft database; add SEC-021 |
| Pairwise kinematics only | Slow, plausible modifications evade per-fix checks | Track-level sequence model; flight-plan conformance |
| Replay detection is indirect | Time-shifted replays look like ordinary tracks | Message-level timestamps (needs raw feed), duplicate-track fingerprinting |
| Toolchain integrity | Poisoned dependency or weights = silent false negatives | `uv.lock`, weight checksums, dependency audit in CI, signed releases |

## Measured feed independence (2026-09-09, New York 150 nm)

`aero corroborate` against adsb.lol (primary) and OpenSky (secondary), four rounds 25 s apart:
about 400 aircraft matched per round, median dead-reckoned separation 0.02 nm, 95th percentile
0.10 nm, one disagreement (2.9 nm) in roughly 1,600 comparisons. About 120 aircraft per round
were seen only by OpenSky and about 25 only by adsb.lol, so neither feed is a subset of the other:
a forgery reaching one receiver network would have to reach the other's antennas too to survive
SEC-015. Those `only_*` counts are the number to watch; a feed-wide fault shows up there first.

## Assumptions and residual risk

- Both feeds are assumed to be independent; if they share feeders in a region, SEC-015 is
  weaker there. Check `only_primary` / `only_secondary` counts from `aero corroborate`.
- The tool is passive: it cannot stop an attack, only shorten time-to-detect and prevent bad
  data from driving decisions. Residual risk therefore lives with the consumers of findings.
- Regulatory references are pointers for the auditor, not legal determinations.
