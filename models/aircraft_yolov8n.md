# Aircraft detector (YOLOv8n fine-tune on RarePlanes) card (2026-09-19 15:58:45Z)

- Model: `yolov8n.pt` fine-tuned for 25 epoch(s) at 512 px on mps; file `models/aircraft_yolov8n.pt` sha256 `55b42aeb91156c96…`
- Data: RarePlanes real tiled subset, 500 training tiles / 1697 aircraft, 120 validation tiles / 442 aircraft (seed 7); CC BY-SA 4.0 (RarePlanes, CosmiQ Works / In-Q-Tel; Shermeyer, Hossler, Van Etten, Hogan, Lewis, Kim, 'RarePlanes: Synthetic Data Takes Flight', 2020)
- RarePlanes validation (same distribution, satellite nadir): mAP50 **0.941**, mAP50-95 0.571, precision 0.926, recall 0.848
- Apron photo (oblique, other domain), conf 0.15, tiles 320 px: recall **0.5** (6/12), precision 0.375; the COCO baseline scored recall 0.167 (2/12), precision 0.4

## Intended use
Aircraft boxes on overhead and apron imagery for the capacity check (OPS-VIS-001/002); every apron report states the measured recall against annotations.

## Limits
Trained on satellite nadir tiles; the bundled apron photo is oblique and the recall above is the honest cross-domain number. Per-site fine-tuning on the camera's own view is the next step for operational use. Loading is gated by the registry checksum like every model in this tree.
