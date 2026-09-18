# Scene classifier card (2026-09-17 13:08:33Z)

- Model: logistic regression over hsv8x8x4+grad8x8x9 features; file `models/scene_classifier.joblib` sha256 `9186072484f04cd4…`
- Data: `data/space/dataset/manifest.json` from nasa-images; classes ['launch', 'orbit', 'station', 'surface']; counts {'launch': 100, 'orbit': 100, 'station': 100, 'surface': 100}
- Split: 314 train / 86 validation by content hash (deterministic)
- Validation accuracy: **64.0%**
- Per class: launch P 0.84 R 0.84 (n=25); orbit P 0.522 R 0.667 (n=18); station P 0.478 R 0.579 (n=19); surface P 0.733 R 0.458 (n=24)

## Intended use
Scene segmentation of launch and spaceflight footage frames; not object detection, not safety-related decisions.

## Limits
Small hand-labelled classes from search queries; NASA library thumbnails; colour-driven features are sensitive to broadcast overlays.
