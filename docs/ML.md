# Machine learning components

## Kinematic anomaly model (ML-001)

- **Task.** Unsupervised outlier detection over per-fix kinematic features, airborne >= 1,000 ft,
  consecutive fixes <= 120 s apart (longer gaps make the features describe the gap, not the flight).
- **Features (12).** implied and reported ground speed, their mismatch and mismatch ratio, speed
  change per second, implied and reported vertical rate and their mismatch, turn rate, speed
  variability across the window, barometric altitude, time between fixes.
- **Altitude bands.** Separate pipelines and thresholds for terminal (< 10,000 ft) and en-route
  traffic, with an "all" pipeline as fallback when a band has fewer than 300 rows. Scores are
  calibrated to percentiles of the band's training distribution (`anomaly_percentile` in the
  evidence), so "1st percentile" means the same thing across bands and model versions.
- **Model.** `SimpleImputer(median) -> StandardScaler -> IsolationForest(300 trees)`; threshold
  is the score quantile at the chosen contamination (default 1% per fix) on the training set.
  The engine only emits ML-001 when an aircraft has >= 2 flagged fixes within 10 minutes.
- **Explainability.** Each finding lists the three largest standardized feature deviations
  (z-scores), which is what an analyst reads first.
- **Evaluation.** Two layers. (1) Grouped holdout by aircraft: the holdout flag rate should sit
  near contamination, otherwise the model memorised its training aircraft; the model card records
  it. (2) `aero evaluate`: injected attack scenarios on real background traffic give recall,
  time-to-detect, and per-rule precision (see docs/RULES.md). Precision feeds the scoring policy.
- **Provenance.** Every `aero train` appends to `models/registry.json` (data files, rows,
  aircraft, features, contamination, sha256 of the model, holdout rate) and `aero evaluate`
  attaches its metrics to the matching entry.
- **Failure modes.** Helicopters, survey and aerobatic flights, feed timestamp jitter at dt < 5 s,
  and any traffic pattern absent from the training window. The playbook forbids escalation on
  ML-001 alone.

## Computer vision (OPS-VIS)

- **Detector.** YOLOv8n pretrained on COCO (class `airplane`), imported lazily.
- **Tiled inference.** 320-px tiles with 25% overlap and greedy NMS; on the bundled aerial apron
  photo (12 parked transports) whole-image inference found none, tiling finds 4 with a few false
  positives on the photographer's wing. This is the honest baseline and the reason fine-tuning
  on DOTA / iSAID / RarePlanes is the next ML task.
- **Zones.** Polygons in normalised coordinates with a capacity; occupancy over capacity is
  OPS-VIS-001, zero occupancy is OPS-VIS-002.

## Training data strategy

- Maximise aircraft per request: adsb.lol at 250 nm returns ~950 aircraft around New York
  versus ~290 at 60 nm. Round-robin four hubs with one client at 12 s.
- Add an independent feed (OpenSky bbox) for corroboration and diversity.
- Keep synthetic recordings as regression fixtures, never as training data.
- Split by aircraft, not by row.

## Roadmap

1. Sequence model over whole tracks (GRU / small Transformer) for slow, plausible manipulations.
2. Surface-movement model (taxi, runway occupancy) using airport geometry.
3. Fine-tuned aerial detector; multi-frame apron tracking for turnaround times.
4. Active-learning loop: analyst labels from playbook outcomes feed contamination and retraining.
