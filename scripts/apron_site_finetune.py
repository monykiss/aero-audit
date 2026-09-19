#!/usr/bin/env python3
"""Per-site few-shot fine-tune with a spatial hold-out: the operational path for an apron camera.

A fixed apron camera sees the same stands in the same light every day, so the honest question for
operations is not "does a satellite-trained detector generalise to this photo" but "how few labelled
stands does this camera need". This script answers it on the bundled photo: it crops training
windows around the aircraft in one part of the image (the west stands), trains a detector for a few
epochs, and evaluates recall only on the other part (the east stands), which the detector never saw.
Annotations are the approximate centres in `data/samples/apron_hohn_truth.json` with a fixed box
size, so the boxes are loose; the recall on the held-out half is still a fair number because the
matching uses centres.

    scripts/apron_site_finetune.py --base models/aircraft_yolov8n.pt --epochs 40 --device mps
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

IMAGE = Path("data/samples/apron_hohn.jpg")
TRUTH = Path("data/samples/apron_hohn_truth.json")
OUT = Path("data/space/apron_site")


def crops(img, boxes: list[tuple[float, float, float, float]], side: int, n: int, rng: random.Random, xmin: float, xmax: float) -> list[tuple[object, list[tuple[float, float, float, float]]]]:
    """Random windows of `side` px whose centres fall in [xmin, xmax] of the image width, with the boxes inside them."""
    W, H = img.size
    out = []
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        cx = rng.uniform(xmin * W, xmax * W)
        cy = rng.uniform(0.30 * H, 0.62 * H)
        x0, y0 = int(min(max(cx - side / 2, 0), W - side)), int(min(max(cy - side / 2, 0), H - side))
        inside = []
        for bx, by, bw, bh in boxes:
            px, py = bx * W, by * H
            if x0 + 8 <= px <= x0 + side - 8 and y0 + 8 <= py <= y0 + side - 8:
                inside.append(((px - x0) / side, (py - y0) / side, bw * W / side, bh * H / side))
        if inside:
            out.append((img.crop((x0, y0, x0 + side, y0 + side)), inside))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--side", type=int, default=320)
    ap.add_argument("--train-crops", type=int, default=24)
    ap.add_argument("--val-crops", type=int, default=8)
    ap.add_argument("--split-x", type=float, default=0.49, help="stands left of this fraction train, right of it are held out")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image

    from aero_audit.vision import Detection, detect_tiled, detections_from_json, evaluate

    img = Image.open(IMAGE).convert("RGB")
    truth = detections_from_json(TRUTH)
    boxes = [(d.cx, d.cy, (d.x2 - d.x1) / img.size[0], (d.y2 - d.y1) / img.size[1]) for d in truth]
    west = [b for b in boxes if b[0] < args.split_x]
    east = [b for b in boxes if b[0] >= args.split_x]
    rng = random.Random(args.seed)
    for split, n, xr in (("train", args.train_crops, (0.25, args.split_x)), ("val", args.val_crops, (args.split_x, 0.75))):
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i, (crop, inside) in enumerate(crops(img, west if split == "train" else east, args.side, n, rng, *xr)):
            crop.save(OUT / "images" / split / f"{split}_{i:03d}.png")
            (OUT / "labels" / split / f"{split}_{i:03d}.txt").write_text("".join(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for cx, cy, w, h in inside))
    (OUT / "data.yaml").write_text(f"path: {OUT.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: aircraft\n")
    from ultralytics import YOLO

    t0 = time.time()
    model = YOLO(args.base)
    results = model.train(data=str(OUT / "data.yaml"), epochs=args.epochs, imgsz=args.side, batch=8, device=args.device, project="runs/aircraft", name="apron_site", exist_ok=True, plots=False, verbose=False, degrees=5.0, scale=0.3)
    best = Path(getattr(results, "save_dir", "runs/aircraft/apron_site")) / "weights" / "best.pt"
    # evaluate on the whole photo but score only the held-out (east) stands: detections west of the split are ignored
    dets, _ = detect_tiled(IMAGE, weights=str(best), conf=0.15, tile=args.side)
    east_dets = [d for d in dets if d.cx >= args.split_x]
    east_truth = [d for d in truth if d.cx >= args.split_x]
    ev = evaluate(east_dets, east_truth)
    base_dets, _ = detect_tiled(IMAGE, weights=args.base, conf=0.15, tile=args.side)
    ev_base = evaluate([d for d in base_dets if d.cx >= args.split_x], east_truth)
    res = {"base": args.base, "epochs": args.epochs, "train_stands": len(west), "held_out_stands": len(east), "train_crops": args.train_crops, "split_x": args.split_x,
           "held_out_recall": ev["recall"], "held_out_precision": ev["precision"], "matched": ev["matched"], "base_held_out_recall": ev_base["recall"], "base_held_out_precision": ev_base["precision"],
           "minutes": round((time.time() - t0) / 60, 1), "weights": str(best), "note": "per-site few-shot with a spatial hold-out on one photo; approximate centre annotations; not a generalisation claim"}
    (OUT / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    _ = Detection  # imported for type parity with the vision package
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
