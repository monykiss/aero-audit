# Model card: kinematic anomaly model (models/kinematic_iforest.joblib)

Trained 2026-09-09 23:24:53Z with IsolationForest (300 trees, contamination 0.01).

## Intended use
Rank airborne ADS-B tracks by how unusual their pairwise kinematics are for the airspace the model was trained on. Output is an *investigation queue*, never an automatic action; the playbook for ML-001 forbids escalation on the model alone.

## Training data
- Recordings: adsblol_lhr_20260909T195312Z.jsonl, adsblol_nyc+ord+lax+lhr_20260909T220203Z.jsonl, adsblol_nyc_20260909T195300Z.jsonl, adsblol_sfo+dfw+atl+hnd_20260909T225058Z.jsonl, opensky_bbox_20260909T220204Z.jsonl, opensky_bbox_20260909T225059Z.jsonl
- Providers: adsblol, opensky  Regions: atl, bbox, dfw, hnd, lax, lhr, nyc, ord, sfo
- Window: 2026-09-09 19:53Z to 2026-09-09 23:15Z  (294 polls)
- Rows: 150226 airborne feature rows from 6155 aircraft (filters: not on ground, baro altitude >= 1000 ft, both fixes have positions)
- Split by aircraft: 120275 train rows / 29951 holdout rows (1231 unseen aircraft)

## Features
| feature | p05 | p50 | p95 |
|---|---|---|---|
| implied_gs_kt | 76.8 | 335.0 | 496.6 |
| reported_gs_kt | 81.8 | 335.5 | 497.7 |
| gs_mismatch_kt | -16.6 | -0.9 | 11.1 |
| gs_mismatch_ratio | -0.1 | -0.0 | 0.0 |
| accel_kt_s | -0.4 | 0.0 | 0.4 |
| implied_vrate_fpm | -1714.3 | 0.0 | 1821.4 |
| reported_vrate_fpm | -1856.0 | 0.0 | 1920.0 |
| vrate_mismatch_fpm | -442.2 | 0.0 | 513.1 |
| turn_rate_dps | -0.6 | 0.0 | 0.5 |
| window_gs_std_kt | 0.7 | 7.0 | 60.1 |
| baro_alt_ft | 1600.0 | 15175.0 | 39000.0 |
| dt_s | 12.0 | 37.4 | 79.3 |

## Altitude bands
| band | training rows | own pipeline | threshold |
|---|---|---|---|
| terminal | 50913 | yes | -0.5919 |
| enroute | 69362 | yes | -0.5977 |
| all | 120275 | yes | -0.5857 |

## Evaluation (unlabelled here; see `aero evaluate` for injected-scenario recall and precision)
- Threshold, fallback band (score quantile at contamination): -0.5857
- Flag rate on training rows: 1.31%
- Flag rate on holdout (unseen aircraft): 1.17%  (a holdout rate far above the contamination means the model over-fits the training aircraft)

Top holdout anomalies and why:
- a40165 alt 1300 ft, implied 94 kt vs reported 664 kt; drivers [('accel_kt_s', 74.97), ('gs_mismatch_kt', -38.31), ('window_gs_std_kt', 13.62)]
- ad2b43 alt 10050 ft, implied 313 kt vs reported 362 kt; drivers [('vrate_mismatch_fpm', -6.68), ('window_gs_std_kt', 5.92), ('gs_mismatch_kt', -3.74)]
- ad5b90 alt 12450 ft, implied 311 kt vs reported 365 kt; drivers [('window_gs_std_kt', 6.89), ('gs_mismatch_kt', -4.1), ('accel_kt_s', 3.74)]
- a3c60d alt 12200 ft, implied 323 kt vs reported 368 kt; drivers [('vrate_mismatch_fpm', -6.83), ('window_gs_std_kt', 5.96), ('accel_kt_s', 4.32)]
- aa739d alt 11950 ft, implied 315 kt vs reported 357 kt; drivers [('window_gs_std_kt', 5.8), ('accel_kt_s', 4.22), ('gs_mismatch_kt', -3.23)]

## Limitations
- Pairwise features only; no memory of the whole track (a sequence model is on the roadmap).
- Trained on a short window; diurnal and seasonal traffic patterns are not represented.
- Helicopters, survey and aerobatic flights are legitimately anomalous and will recur.
- Feed timestamp jitter dominates at dt < 5 s; such rows are noisy by construction.

## Monitoring
- Track ML-001 precision from analyst review; retrain when flag rate drifts > 2x contamination.
- Regression-test with `tests/test_rules.py` (synthetic anomalies must stay detectable).