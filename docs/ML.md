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

- **Detector.** YOLOv8n fine-tuned on a RarePlanes subset (`models/aircraft_yolov8n.pt`, registered
  with a card and a checksum; `aero vision apron` uses it when present, the COCO `yolov8n.pt` otherwise).
- **Tiled inference.** 320-px tiles with 25% overlap and greedy NMS.
- **Measured (1.3.0).** Training data: 500 RarePlanes tiles / 1,697 aircraft, validation 120 tiles /
  442 aircraft (satellite, nadir, CC BY-SA 4.0; `scripts/rareplanes_subset.py`). Frozen backbone,
  rotation and perspective augmentation, 25 epochs, 4 minutes on an Apple GPU
  (`scripts/train_aircraft_detector.py --freeze 10 --degrees 15 --perspective 0.0005 --epochs 25`).

  | Evaluation | COCO baseline | Fine-tuned |
  |---|---|---|
  | RarePlanes validation mAP50 (same distribution) | n/a (no aircraft class) | **0.941** (mAP50-95 0.571, precision 0.926, recall 0.848) |
  | Apron photo, 12 annotated transports, oblique (other domain) | recall 0.167 (2/12), precision 0.40 | recall **0.50** (6/12), precision 0.375 |

  Plain fine-tuning without the frozen backbone reached the same mAP50 but *lost* the apron photo
  (1/12): the satellite domain overwrote the COCO features the oblique view needs. Freezing the
  backbone kept them (3/12), augmentation added the rest (6/12). Every apron report writes the
  recall it measured against annotations, so the number travels with the finding.
- **Per-site few-shot (the operational path).** `scripts/apron_site_finetune.py` trains on crops
  around the six west stands of the same photo and scores only the six east stands it never saw.
  Measured: the registered RarePlanes model already finds 5 of the 6 held-out stands (recall 0.83,
  precision 0.39); 40 epochs on 24 crops of the west stands keep recall at 0.83 and lift precision
  to 0.45. With six approximate labels the gain is in false positives, not misses; a second
  annotated photo is what a real cross-site number needs.
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
