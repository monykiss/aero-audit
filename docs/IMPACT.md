# Real-world impact

## Who would use this and for what decision

| Stakeholder | Decision it informs | Findings used |
|---|---|---|
| Air navigation service providers (ATC) | Is the surveillance picture trustworthy right now? Which sectors have coverage holes? | SEC-010/015/016/017, OPS-001 |
| Airport operators / A-CDM cells | Arrival-rate and stand-allocation tuning; where delay is being absorbed | OPS-002, OPS-VIS-001/002, METAR context |
| Airline operations and safety (FOQA/FDM adjacent) | Fleet ADS-B compliance, level-bust and vertical-rate review, holding fuel | SEC-012, OPS-004, SAF-003, OPS-002 |
| Aviation security / duty officers | Is a 7500 real? Is a track a ghost? | SEC-001..004 with corroboration, playbooks |
| Regulators (FAA, EASA, national CAAs) | ADS-B Out compliance rates by operator, spoofing incident evidence | SEC-012 statistics, recordings |
| Feed operators (OpenSky, adsb.lol, receivers) | Feeder quality, mis-merges, poisoned feeders | SEC-014/015/017 |
| Insurers, researchers, journalists | Independent evidence of incidents and trends | Replayable recordings, JSON findings |

## Why now

- **GNSS interference at scale.** Since 2023 civil aviation has experienced sustained GPS
  jamming and spoofing in the Baltic, Black Sea, and Middle East regions; OPSGROUP's spoofing
  workgroup described on the order of a thousand flights a day affected at the 2024 peak
  (figures vary by month and source). Spoofed GNSS shows up in ADS-B exactly as SEC-010
  position jumps and SEC-012 integrity degradation, so an ADS-B auditor is a cheap,
  independent detector of the phenomenon.
- **ADS-B is mandatory and unauthenticated.** The US rule airspace mandate (2020) and EU
  1207/2011 made ADS-B the primary surveillance source while the protocol still has no
  message authentication. Costin & Francillon (2012) demonstrated injection with commodity
  hardware; Strohmeier et al. (2015) surveyed the countermeasures. The gap has not closed.
- **Open data made independent auditing possible.** Community feeds give anyone the same
  picture the professionals see, which means claims can be verified by third parties.

## Quantifying operational impact (what the toolkit can measure)

Holding is the clearest example, and `aero impact` computes it from OPS-002 evidence.
Default parameters, all adjustable on the command line:

| Parameter | Default | Basis |
|---|---|---|
| Fuel burn in the hold | 40 kg/min | Narrow-body (A320/737 family) holding burn ~2,400 kg/h; wide-bodies are 2-3x |
| CO2 per kg jet fuel | 3.16 kg | Standard combustion factor (ICAO carbon calculator) |
| Delay cost | 100 EUR/min | Order of magnitude from University of Westminster / EUROCONTROL cost-of-delay studies (tactical, network level) |
| Fuel price | 0.85 EUR/kg | Jet A-1 order of magnitude, 2024-2026; adjust to the day |

So one observed 12-minute racetrack hold costs roughly 480 kg fuel, 1.5 t CO2, and ~1,200 EUR
before passenger impact. Across the session's six civil recordings (about 100 minutes of
coverage over eight hubs and two regional boxes) the toolkit observed 30 airline holds totalling
267 minutes: about 10.7 t fuel, 33.7 t CO2, and 26,700 EUR at the default assumptions. Ten such holds per hour at a hub, sustained over an evening bank, is
the scale at which arrival-rate management changes become worth the effort. The toolkit
measures the *observed* portion of holds (limited by capture window and polling rate), so
treat its totals as a floor.

Other measurable quantities with the current rules:

- **ADS-B compliance rate**: share of airborne ADS-B fixes meeting 91.227 minimums, printed in
  every audit summary and report (`adsb_compliance_rate`). Measured: 98.9% of 44,377 fixes over NYC/ORD/LAX/LHR versus 95.4% of 34,217 over
  SFO/DFW/ATL/HND, and 95.9% on the global military feed. Useful for regulators and maintenance planning; split by operator/type next.
- **Coverage gaps** (OPS-001) mapped by sector over a day: where to place a receiver.
- **Surveillance integrity index**: fraction of aircraft corroborated across feeds within
  tolerance (from `aero corroborate`). First measurement over New York: ~400 matched per round,
  median separation 0.02 nm, one disagreement in ~1,600 comparisons. A drop is an early warning
  of feed or RF problems.
- **Apron utilisation**: occupancy per zone over time from imagery (OPS-VIS), feeding stand
  allocation.

## Security impact

- **Time-to-detect.** Measured with injected scenarios on real traffic: position replacement,
  altitude forgery, replay, hijack squawk, and integrity degradation are flagged on the first
  affected fix (0 s at 20 s polling, one revisit at 48 s) with 96-100% recall; a 7500 is reported
  unconfirmed on one fix and escalated on the second, with a playbook that mandates voice/ACARS
  corroboration before response. See docs/THREAT_MODEL.md for the full table and the two known gaps. The cost of *not* detecting is a scrambled response or a missed real emergency.
- **Decision hygiene.** The trust ledger prevents low-integrity or suspect tracks from silently
  driving KPIs and analytics; every downstream consumer can weight positions by trust.
- **Evidence.** Recordings plus JSON findings give incident responders and regulators a
  replayable record with the exact thresholds used.

## Limits of the claims

- Public feeds are best-effort; absence from a feed is weak evidence.
- Findings are signals for review, not determinations. Base rates matter: on the first live
  run, most SEC-012 hits were general-aviation aircraft with legacy equipment, not attacks.
- Cost figures are order-of-magnitude defaults for illustration; replace them with the
  operator's own numbers before quoting a business case.

## References

- Costin, A. & Francillon, A. (2012). Ghost in the Air(Traffic): On insecurity of ADS-B
  protocol and practical attacks on ADS-B devices. Black Hat USA.
- Strohmeier, M., Lenders, V. & Martinovic, I. (2015). On the Security of the Automatic
  Dependent Surveillance-Broadcast Protocol. IEEE Communications Surveys & Tutorials.
- RTCA DO-260B, Minimum Operational Performance Standards for 1090 MHz ES ADS-B and TIS-B.
- 14 CFR 91.225 / 91.227; EU Implementing Regulation 1207/2011 (as amended).
- University of Westminster for EUROCONTROL, European airline delay cost reference values.
- ICAO Carbon Emissions Calculator methodology (CO2 factor 3.16).
