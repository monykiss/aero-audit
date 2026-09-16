# Scene classifier (YOLOv8-cls fine-tune) card (2026-09-16 11:29:19Z)

- Model: `yolov8n-cls.pt` fine-tuned for 3 epoch(s); file `models/scene_yolo_cls.pt` sha256 `8e80b1a3f5f1bc0b…`
- Data: `data/space/dataset_renders/manifest.json` (72 items; classes ['carrier', 'satellite']; counts {'satellite': {'train': 23, 'val': 13}, 'carrier': {'train': 28, 'val': 8}}); split by content hash
- Validation top-1: **90.5%**

## Intended use
Scene labels for spaceflight imagery and rendered spacecraft views; not object detection, not safety decisions.

## Limits
Trained on the classes and renders listed above only; silhouettes from a software rasteriser differ from photographs; evaluate on real imagery before relying on it. Loading is gated by the registry checksum like every model in this tree.
