# Scene classifier (YOLOv8-cls fine-tune) card (2026-09-17 13:09:50Z)

- Model: `yolov8n-cls.pt` fine-tuned for 10 epoch(s); file `models/scene_yolo_cls.pt` sha256 `10b2612d538ab64a…`
- Data: `data/space/dataset/manifest.json` (400 items; classes ['launch', 'orbit', 'station', 'surface']; counts {'launch': {'train': 75, 'val': 25}, 'orbit': {'train': 82, 'val': 18}, 'station': {'train': 81, 'val': 19}, 'surface': {'train': 76, 'val': 24}}); split by content hash
- Validation top-1: **80.2%**

## Intended use
Scene labels for spaceflight imagery and rendered spacecraft views; not object detection, not safety decisions.

## Limits
Trained on the classes and renders listed above only; silhouettes from a software rasteriser differ from photographs; evaluate on real imagery before relying on it. Loading is gated by the registry checksum like every model in this tree.
