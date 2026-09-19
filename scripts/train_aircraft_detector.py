#!/usr/bin/env python3
"""Fine-tune a YOLOv8 detector for aircraft on the RarePlanes subset, evaluate it twice, register it honestly.

Two numbers come out, and both go into the card and the registry entry: mAP50 on the RarePlanes validation
tiles (same distribution: satellite, nadir) and recall against the hand annotations of the bundled oblique
apron photo (`data/samples/apron_hohn_truth.json`), which is the number the apron capacity check actually
depends on. The registry entry never carries per-attack `recall`, so the app keeps reporting the anomaly
model on its HOME page; this model is picked up by `aero vision apron` when `models/aircraft_yolov8n.pt` exists.

    scripts/rareplanes_subset.py --train 500 --val 120
    scripts/train_aircraft_detector.py --epochs 10 --device mps      # or cpu; GPU ids work too

Outputs land under runs/aircraft/ (git-ignored); the registered weights, card and registry entry under models/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

DATA = Path("data/space/rareplanes/yolo/data.yaml")
OUT = Path("models/aircraft_yolov8n.pt")
APRON = Path("data/samples/apron_hohn.jpg")
TRUTH = Path("data/samples/apron_hohn_truth.json")


def apron_eval(weights: str, conf: float, tile: int) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from aero_audit.vision import detect_tiled, detections_from_json, evaluate

    dets, _ = detect_tiled(APRON, weights=weights, conf=conf, tile=tile)
    ev = evaluate(dets, detections_from_json(TRUTH))
    return {**ev, "conf": conf, "tile": tile}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--base", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="cpu", help="cpu, mps or a CUDA id")
    ap.add_argument("--conf", type=float, default=0.15, help="confidence for the apron evaluation")
    ap.add_argument("--tile", type=int, default=320, help="tile size for the apron evaluation (0 = whole image)")
    ap.add_argument("--freeze", type=int, default=0, help="freeze the first N layers (10 = the backbone) to keep the COCO features")
    ap.add_argument("--degrees", type=float, default=0.0, help="rotation augmentation (deg)")
    ap.add_argument("--perspective", type=float, default=0.0, help="perspective augmentation (0..0.001)")
    ap.add_argument("--scale", type=float, default=0.5, help="scale augmentation")
    ap.add_argument("--name", default="yolov8n", help="run name under runs/aircraft/")
    ap.add_argument("--no-register", action="store_true")
    args = ap.parse_args()
    if not args.data.is_file():
        print(f"no dataset at {args.data}; run scripts/rareplanes_subset.py first")
        return 2
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics is not installed; install the vision extra")
        return 2
    manifest = json.loads((args.data.parent / "manifest.json").read_text())
    t0 = time.time()
    model = YOLO(args.base)
    results = model.train(data=str(args.data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device, project="runs/aircraft", name=args.name, exist_ok=True, plots=False, verbose=False,
                          freeze=args.freeze or None, degrees=args.degrees, perspective=args.perspective, scale=args.scale)
    save_dir = Path(getattr(results, "save_dir", None) or getattr(model.trainer, "save_dir", f"runs/aircraft/{args.name}"))
    best = save_dir / "weights" / "best.pt"
    metrics = YOLO(str(best)).val(data=str(args.data), imgsz=args.imgsz, device=args.device, plots=False, verbose=False)
    box = metrics.box
    val = {"map50": round(float(box.map50), 4), "map50_95": round(float(box.map), 4), "precision": round(float(box.mp), 4), "recall": round(float(box.mr), 4)}
    baseline = apron_eval(args.base, args.conf, args.tile)
    tuned = apron_eval(str(best), args.conf, args.tile)
    minutes = round((time.time() - t0) / 60, 1)
    print(f"RarePlanes val: {val}")
    print(f"apron photo, baseline {args.base}: recall {baseline['recall']} precision {baseline['precision']} ({baseline['matched']}/{baseline['truth']})")
    print(f"apron photo, fine-tuned:           recall {tuned['recall']} precision {tuned['precision']} ({tuned['matched']}/{tuned['truth']})  [{minutes} min]")
    if args.no_register:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best, OUT)
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    card = OUT.with_suffix(".md")
    card.write_text("\n".join([
        f"# Aircraft detector (YOLOv8n fine-tune on RarePlanes) card ({stamp})", "",
        f"- Model: `{args.base}` fine-tuned for {args.epochs} epoch(s) at {args.imgsz} px on {args.device}; file `{OUT}` sha256 `{sha[:16]}…`",
        (f"- Data: RarePlanes real tiled subset, {manifest['train']['tiles']} training tiles / {manifest['train']['aircraft']} aircraft, "
         f"{manifest['val']['tiles']} validation tiles / {manifest['val']['aircraft']} aircraft (seed {manifest['seed']}); {manifest['licence']}"),
        f"- RarePlanes validation (same distribution, satellite nadir): mAP50 **{val['map50']:.3f}**, mAP50-95 {val['map50_95']:.3f}, precision {val['precision']:.3f}, recall {val['recall']:.3f}",
        (f"- Apron photo (oblique, other domain), conf {args.conf}, tiles {args.tile} px: recall **{tuned['recall']}** ({tuned['matched']}/{tuned['truth']}), precision {tuned['precision']}; "
         f"the COCO baseline scored recall {baseline['recall']} ({baseline['matched']}/{baseline['truth']}), precision {baseline['precision']}"), "",
        "## Intended use", "Aircraft boxes on overhead and apron imagery for the capacity check (OPS-VIS-001/002); every apron report states the measured recall against annotations.", "",
        "## Limits", ("Trained on satellite nadir tiles; the bundled apron photo is oblique and the recall above is the honest cross-domain number. "
                      "Per-site fine-tuning on the camera's own view is the next step for operational use. Loading is gated by the registry checksum like every model in this tree."),
    ]) + "\n")
    reg = Path("models/registry.json")
    try:
        entries = json.loads(reg.read_text())
    except (OSError, ValueError):
        entries = []
    entries.append({"trained_at": stamp, "model_path": str(OUT), "sha256": sha, "recordings": [str(args.data.parent / "manifest.json")], "providers": ["rareplanes-public (CC BY-SA 4.0)"],
                    "regions": ["aircraft"], "rows": manifest["train"]["tiles"], "aircraft": manifest["train"]["aircraft"], "contamination": 0.0, "features": [f"yolov8-detect:{args.base}"],
                    "holdout_flag_rate": None, "evaluation": {"rareplanes_val": val, "apron_hohn": tuned, "apron_hohn_baseline": baseline, "epochs": args.epochs, "imgsz": args.imgsz, "device": args.device, "freeze": args.freeze, "degrees": args.degrees, "perspective": args.perspective, "minutes": minutes, "run": str(save_dir)}})
    reg.write_text(json.dumps(entries, indent=2))
    print(f"registered {OUT} (sha256 {sha[:12]}…) with card {card}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
