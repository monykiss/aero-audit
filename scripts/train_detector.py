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
    ap.add_argument("--register", action="store_true", help="copy best.pt to models/, write a card and a registry entry")
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
    save_dir = Path(getattr(results, "save_dir", None) or getattr(model.trainer, "save_dir", "runs/scene/cls"))
    print(f"done; see {save_dir} (best.pt, results.csv).")
    if args.register:
        register(save_dir, args.manifest, m, args.epochs, args.model)
    else:
        print("Register the weights with a card before use: re-run with --register.")
    return 0 if results is not None else 1


def register(save_dir: Path, manifest: Path, m: dict, epochs: int, base: str, out: Path = Path("models/scene_yolo_cls.pt")) -> Path:
    """Copy best.pt beside the other models, write a card, append a registry entry: the same checksum gate as every model here."""
    import csv
    import hashlib
    import json
    import shutil
    import time

    best = save_dir / "weights" / "best.pt"
    if not best.is_file():
        raise SystemExit(f"no weights at {best}")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best, out)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    rows = list(csv.DictReader((save_dir / "results.csv").open())) if (save_dir / "results.csv").is_file() else []
    top1 = max((float(r.get("metrics/accuracy_top1") or 0) for r in rows), default=None)
    classes = sorted(m["counts"])
    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    card = out.with_suffix(".md")
    card.write_text("\n".join([
        f"# Scene classifier (YOLOv8-cls fine-tune) card ({stamp})", "",
        f"- Model: `{base}` fine-tuned for {epochs} epoch(s); file `{out}` sha256 `{sha[:16]}…`",
        f"- Data: `{manifest}` ({len(m['items'])} items; classes {classes}; counts {m['counts']}); split by content hash",
        f"- Validation top-1: **{top1:.1%}**" if top1 is not None else "- Validation: results.csv missing", "",
        "## Intended use", "Scene labels for spaceflight imagery and rendered spacecraft views; not object detection, not safety decisions.", "",
        "## Limits", ("Trained on the classes and renders listed above only; silhouettes from a software rasteriser differ from photographs; "
                      "evaluate on real imagery before relying on it. Loading is gated by the registry checksum like every model in this tree."),
    ]) + "\n")
    reg = Path("models/registry.json")
    try:
        entries = json.loads(reg.read_text())
    except (OSError, ValueError):
        entries = []
    entries.append({"trained_at": stamp, "model_path": str(out), "sha256": sha, "recordings": [str(manifest)], "providers": sorted({it.get("source", "") for it in m["items"]}),
                    "regions": classes, "rows": len(m["items"]), "aircraft": 0, "contamination": 0.0, "features": [f"yolov8-cls:{base}"],
                    "holdout_flag_rate": round(1.0 - top1, 4) if top1 is not None else None, "evaluation": {"accuracy_top1": top1, "epochs": epochs, "run": str(save_dir)}})
    reg.write_text(json.dumps(entries, indent=2))
    print(f"registered {out} (sha256 {sha[:12]}…) with card {card}; top-1 {top1}")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
