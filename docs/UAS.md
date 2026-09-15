# UAS integration: well-clear metrics, encounters, UTM contracts (private branch)

`aero_audit/uas/` measures, offline and on recorded tracks, the quantities a detect-and-avoid
safety case is built from. It never issues guidance to anything airborne.

## Definitions (DAIDALUS / RTCA DO-365)

Well-clear, Phase 1 parameters: `DTHR` 4,000 ft, `ZTHR` 450 ft, `TTHR` 35 s, `TCOA` 0 s.

- Horizontal: not well clear when range `r <= DTHR`, or when the modified tau
  `tau_mod = (DTHR^2 - r^2) / -(s·v)` lies in `[0, TTHR]` while the projected horizontal miss
  distance `HMD <= DTHR`.
- Vertical: not well clear when `|dz| <= ZTHR` (or converging with time to co-altitude within `TCOA`).
- A violation needs both. Alert levels project the pair forward: preventive (`ZTHR` 700 ft, 55 s),
  corrective (450 ft, 55 s), warning (450 ft, 25 s).

Worked example (`tests/test_uas.py`): two aircraft head-on at 400 kt closure and the same
altitude are still well clear at 5 nm (`tau_mod` 44 s), but the violation is 9 s away, so the
warning level is active; at 8 nm the corrective level; at 12 nm nothing.

## Encounters from recordings

```bash
aero uas wellclear data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz
aero gov run-study ST-07 --recording <recording>      # violations per flight hour, NMAC-proximate, lead time
aero gov run-study ST-08 --recording <recording>      # encounter and NMAC-proximate rates
```

Candidate pairs are airborne aircraft within 10 nm and 3,000 ft in the same batch (a 0.2° cell
grid keeps national batches linear). Each sample is scored; per pair the report keeps minimum
range, vertical separation and HMD, the highest alert level, whether well clear was lost, whether
the pair came within NMAC distances (500 ft / 100 ft), and the lead time between first alert and
violation. Findings: DAA-001 (violation; HIGH when NMAC-proximate) and DAA-002 (lead time under
the warning time). Rates are per flight hour observed in the recording.

Limits that matter: surveillance updates every 10 to 60 s, so lead times are coarse and many
encounters are seen at only a few samples; round-robin recordings only pair aircraft inside one
region per batch; the metrics describe what the feed saw, not what the aircraft's own DAA saw.

## Airspace density classes and the DAA risk ratio

```bash
aero uas risk <recording>          # density class per 0.2° cell and altitude band; observed DAA risk ratio (DAA-003/004)
aero gov run-study ST-16 --recording <recording>
```

Density is aircraft-hours per cell per band, normalised to the cell area and the recording span,
classed sparse / moderate / dense / very dense at programme thresholds (0.05, 0.5, 5 aircraft-hours
per 100 nm² per hour, the MIT-LL air-risk-class idea of density-driven classes). The risk ratio
follows the ASTM F3442 lineage, bounded from observation: NMAC-proximate encounters whose alert
lead time was below the warning time, over all NMAC-proximate encounters. A value of 1.0 on a
surveillance feed with 10 to 60 s revisits is expected and is the point: at that rate the alerting
horizon is shorter than the update interval, which a DAA case must address with better
surveillance, not with a lower threshold. The UAS page in the app shows the bands, the pairs and
the ratio with buttons that run both analyses on any recording.

## Encounter model (Monte Carlo)

```bash
aero uas encounter-model <recording> --n 5000 --horizon-s 25
aero gov run-study ST-19 --recording <recording>
```

`uas/encounter_model.py` follows the MIT-LL encounter-model idea at small scale: it resamples the
empirical initial conditions of a recording's encounters (range, vertical offset, closure rate,
converging share), draws straight-line encounters with a uniform horizontal miss distance,
propagates them through the well-clear definitions and counts NMACs with nobody manoeuvring and
with an alerting horizon (a manoeuvre is assumed to succeed when the violation was projected at
least the horizon before the NMAC). The two probabilities, their ratio and the per-flight-hour
rates sit next to the observed bound from `aero uas risk`; both are stated with their basis in the
report. It is not a certified encounter model: distributions are empirical marginals from one
recording, trajectories are straight, and the manoeuvre model is a horizon, not a dynamics model.

## UTM contract checks

```bash
aero uas utm-check <openapi.json> sample1.json sample2.json --schema Position
aero uas utm-check <openapi.json> response.json --path /positions --method get --status 200
aero gov run-study ST-09 --spec <openapi.json> --sample <exchange.json> --schema <Name>
```

A dependency-free validator for what contracts actually use (type, required, properties, items,
enum, nullable, oneOf/anyOf/allOf, local `$ref`, date-time / uuid / uri formats, bounds). Works
on NASA's utm-apis documents (fetch them from `nasa/utm-apis`; YAML needs PyYAML or a conversion
to JSON) and on this app's own `/api/v1/openapi.json`.
