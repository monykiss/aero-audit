# Scene classifier (YOLOv8-cls fine-tune) card (2026-09-17 12:23:08Z)

- Model: `yolov8n-cls.pt` fine-tuned for 8 epoch(s); file `models/scene_yolo_cls.pt` sha256 `53586f55f3786453…`
- Data: `data/space/dataset/manifest.json` (160 items; classes ['launch', 'orbit', 'station', 'surface']; counts {'launch': {'train': 27, 'val': 13}, 'orbit': {'train': 30, 'val': 10}, 'station': {'train': 32, 'val': 8}, 'surface': {'train': 31, 'val': 9}}); split by content hash
- Validation top-1: **77.5%**

## Intended use
Scene labels for spaceflight imagery and rendered spacecraft views; not object detection, not safety decisions.

## Limits
Trained on the classes and renders listed above only; silhouettes from a software rasteriser differ from photographs; evaluate on real imagery before relying on it. Loading is gated by the registry checksum like every model in this tree.
