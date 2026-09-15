#!/usr/bin/env python3
"""Fine-tune an image classifier (and, with boxes, a detector) on the aero-audit dataset manifest
using ultralytics, when it is installed. Without ultralytics it explains what to install and what
the dataset layout looks like; the scene classifier in aero_audit/space/classifier.py is the
dependency-light fallback.

    scripts/train_detector.py data/space/dataset/manifest.json --epochs 20 --model yolov8n-cls.pt

Runs on CPU (slowly) or on any GPU ultralytics supports. Outputs land under runs/ (git-ignored).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--model", default="yolov8n-cls.pt", help="classification weights (yolov8n-cls.pt) or detection weights with a boxes dataset")
    ap.add_argument("--out", type=Path, default=None, help="layout directory (default next to the manifest)")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from aero_audit.space.dataset import load_manifest, to_classify_layout

    m = load_manifest(args.manifest)
    layout = to_classify_layout(args.manifest, args.out)
    print(f"{len(m['items'])} items, classes {sorted(m['counts'])}; layout at {layout}")
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics is not installed. Install the vision extra (uv pip install -e '.[vision]') and re-run; the layout above is ready.")
        print("Fallback available now: aero space classify-train", args.manifest)
        return 2
    model = YOLO(args.model)
    results = model.train(data=str(layout), epochs=args.epochs, imgsz=args.imgsz, project="runs/scene", name="cls", exist_ok=True)
    print("done; see runs/scene/cls (best.pt, results.csv). Register the weights with a card before use.")
    return 0 if results is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
