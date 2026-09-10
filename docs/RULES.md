# Rule catalog

Thresholds are module constants at the top of `aero_audit/audit/rules.py` (stream-level ones in
`audit/engine.py`). Every finding carries lat/lon, altitude, speed, position source, feed, and
rule-specific evidence. Severity here is the default; the scoring policy ranks the report.

| Rule | Cat. | Sev. | Trigger | False-positive modes | Controls |
|---|---|---|---|---|---|
| SEC-001 | security | high (confirmed) / medium (single fix) | squawk 7700 | test squawks, mis-dial for one fix | ICAO Doc 4444; FAA AIM 4-1-20 |
| SEC-002 | security | high / medium (single fix) | squawk 7600 | as above | ICAO Doc 4444 |
| SEC-003 | security | critical (confirmed on 2 consecutive fixes) / high (single fix, unconfirmed) | squawk 7500 | spoofed code (T04); one-poll mis-dials seen live (ASA810, 2026-09-09) | ICAO Doc 4444; Annex 17 |
| SEC-004 | security | high | emergency subfield != none | mis-set subfield | DO-260B 2.2.3.2.7.8.1.1 |
| SEC-010 | security (ADS-B) / data-quality (MLAT, TIS-B) | high / critical (> 2x) for ADS-B; medium for MLAT/TIS-B | implied ground speed > 750 kt between fixes, dt >= 4 s, airborne | receiver merge glitches, address collisions; MLAT solver error in sparse coverage (seen on the military feed: 84-96 nm "jumps" at FL400 over Wyoming) | AC 20-165B; Annex 17; DO-260B |
| SEC-011 | security | medium (ADS-B) / low (MLAT, TIS-B) | \|implied - reported GS\| > 150 kt for ADS-B positions; tolerance x2.5 for MLAT, x2 for TIS-B; dt >= 4 s | timestamp jitter at small dt, turns, multilateration jitter | DO-260B |
| SEC-018 | security (ADS-B) / data-quality (MLAT, TIS-B) | high (impossible) / medium (inconsistent); low for relays | implied vertical rate > 8,000 fpm, or \|implied - reported\| > 4,000 fpm, dt >= 10 s | altitude relays lagging on MLAT/TIS-B; encoder garbles | DO-260B; Annex 17 |
| SEC-012 | data-quality | low / medium (SIL 0 or NIC <= 4) | NIC < 7 or NACp < 8 or SIL < 3, ADS-B sources only, airborne | GA aircraft with legacy GPS (compliant outside rule airspace) | 14 CFR 91.227(c); DO-260B |
| SEC-013 | security | low | airborne > 10,000 ft with blank callsign | GA / military without Flight ID | Doc 4444; AC 90-114 |
| SEC-014 | security | high | same ICAO24 at two positions >= 5 nm apart in one batch | transponder misconfiguration after maintenance | Annex 10 Vol III |
| SEC-015 | security | medium / high (> 4x allowance) | cross-feed separation > 1.5 nm + 60 kt x dt after dead reckoning, dt <= 90 s | large dt, turning aircraft | Doc 9924; Annex 17 |
| SEC-016 | security | high | new addresses >= 25 and > 4x rolling mean (8 batches) | receiver coming online, shift-change surges | Doc 9924 |
| SEC-017 | security | high | region count < 50% of rolling mean (baseline >= 20) | provider outage, empty payload | Doc 9924; Annex 10 Vol IV |
| SEC-020 | security | per entry | watchlist match on address / callsign prefix / registration | stale entries | organisation policy |
| OPS-001 | operations | info | position older than 90 s while airborne | edge-of-coverage aircraft | Doc 9924 |
| OPS-002 | operations | low | >= 8 fixes, cumulative heading change >= 300 deg, net displacement <= 8 nm, altitude >= 3,000 ft and speed >= 150 kt | vectoring circles near arrival fixes | Doc 4444; GANP |
| OPS-003 | operations | info | same orbit geometry below 3,000 ft or 150 kt | none (it is normal activity); tracked for density | FAA AC 90-66C |
| OPS-004 | safety | low (gap <= 1,000 ft) / info (larger gap) | level (\|vrate\| <= 300 fpm), \|baro - selected\| > 300 ft above 3,000 ft, persisting >= 3 fixes and >= 60 s | pending clearances, "descend via" waits (the info tier) | level-bust programmes |
| OPS-005 | operations | low | squawk 1200 above 18,000 ft | non-US airspace (VFR code is 7000) | 14 CFR 91.135 |
| SAF-003 | safety | medium | \|vrate\| > 6,000 fpm airborne | military / aerobatic; bad data (check implied rate) | Annex 6; FOQA |
| SAF-004 | safety | medium (< 1.5 nm and < 600 ft) / info | two airborne aircraft above 3,000 ft within 3 nm and 900 ft after dead-reckoning fixes (<= 60 s old) to batch time | formation flights, parallel approaches, stale/MLAT fixes | Doc 4444 separation minima; Annex 11 |
| ML-001 | ml | low / medium (margin > 0.05) | IsolationForest score below trained threshold on >= 2 fixes within 10 min, airborne >= 1,000 ft, dt <= 120 s | helicopters, survey, aerobatics | NIST AI RMF |
| OPS-VIS-001 | operations | medium | detections in zone > capacity | detector false positives (wings, hangars) | Annex 14; A-CDM |
| OPS-VIS-002 | operations | info | zone with zero detections | detector misses | A-CDM KPIs |

## Measured detection performance

`aero evaluate <recording> --model <model>` perturbs a sample of real aircraft with eight attack
scenarios (teleport, velocity forgery, altitude forgery, replay, hijack squawk, integrity
degradation, slow drift, perfect ghost) and reports recall, median time-to-detect, and per-rule
precision against untouched aircraft. Results land in `reports/evaluation_*.md` and
`models/evaluation.json`; the latter is read by the scoring policy and the risk register so a
rule's measured precision changes how much its findings count. Two scenarios are known gaps by
design and are reported as such.

## KPIs computed alongside the rules

- `adsb_compliance_rate`: airborne ADS-B fixes with NIC >= 7, NACp >= 8, SIL = 3 divided by all
  airborne ADS-B fixes that carry integrity fields (TIS-B/MLAT excluded). Feeds without NIC/NACp/SIL
  (OpenSky) report n/a.
- `low_trust_aircraft`: aircraft whose trust ledger score fell below 0.5 during the audit.
- `top_aircraft_by_risk`: cumulative risk score per aircraft (policy-dependent).

## Tuning guidance

- **Kinematics (SEC-010/011):** the 750 kt bound is generous for civil traffic; lower it for a
  GA-only airspace, raise it near military ranges. On the first four-hub audit every SEC-011 hit
  at the default tolerance was an MLAT-tracked military aircraft (multilateration jitter over a
  48 s revisit is ~3 nm), hence the per-source tolerance factors. Keep `MIN_DT_FOR_KINEMATICS_S` >= 4 s: below
  that, feed timestamp rounding produces phantom speeds.
- **Integrity (SEC-012):** the 91.227 minimums apply in US rule airspace; EU 1207/2011 is
  comparable (NIC >= 7 / NACp >= 8 / SIL >= 3 / SDA >= 2 for forward-fit). For non-rule airspace
  lower the thresholds or treat as INFO.
- **Holding (OPS-002):** 300 deg over 8 fixes at 10 s polls is one racetrack; with slower
  polling (multi-region round-robin at ~50 s per revisit) raise `TrackStore(window=...)`. The
  altitude/speed floors came from the first 20-minute OpenSky audit: 154 of 190 orbit detections
  were below 3,000 ft and 136 were slower than 100 kt (training circuits and helicopters), while
  only 3 were jet-speed holds. Those now land in OPS-003 so the impact estimate counts only real holds.
- **Stream checks:** SEC-016/017 need >= 3 batches of history per region and are quiet on
  replays shorter than that.
- **ML persistence:** per-fix contamination of 1% still flags ~20% of aircraft that have 20+ fixes
  if a single flagged fix counts; requiring two flagged fixes within 10 minutes is what keeps ML-001
  reviewable. Tune `ML_MIN_FLAGS` / `ML_FLAG_WINDOW_S` in `audit/engine.py`.
- **Cooldown:** 120 s per (rule, aircraft), except that a finding of *higher* severity for the same
  (rule, aircraft) always passes: a 7500 confirmed on the second fix is never suppressed by the
  unconfirmed one that preceded it. Longer cooldowns produce cleaner reports;
  `occurrences` keeps the count regardless.

## Adding a rule (checklist)

1. Function decorated with `@rule("ID")` (or `@batch_rule`) returning `Finding`s via `_mk`.
2. Entry in `RULE_CATALOG`.
3. Playbook in `security/playbooks.py`.
4. Threat mapping in `security/threats.py` if it detects an attack.
5. Synthetic injection in `synthetic.py` and an assertion in `tests/test_rules.py`.
