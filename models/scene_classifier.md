# Scene classifier card (2026-09-17 12:22:42Z)

- Model: logistic regression over hsv8x8x4+grad8x8x9 features; file `models/scene_classifier.joblib` sha256 `7e4c4aa6d8319475…`
- Data: `data/space/dataset/manifest.json` from nasa-images; classes ['launch', 'orbit', 'station', 'surface']; counts {'launch': 40, 'orbit': 40, 'station': 40, 'surface': 40}
- Split: 120 train / 40 validation by content hash (deterministic)
- Validation accuracy: **52.5%**
- Per class: launch P 0.643 R 0.692 (n=13); orbit P 0.6 R 0.3 (n=10); station P 0.4 R 0.5 (n=8); surface P 0.455 R 0.556 (n=9)

## Intended use
Scene segmentation of launch and spaceflight footage frames; not object detection, not safety-related decisions.

## Limits
Small hand-labelled classes from search queries; NASA library thumbnails; colour-driven features are sensitive to broadcast overlays.
