#!/usr/bin/env python3
"""A reproducible subset of RarePlanes (real, tiled) as a YOLO detection dataset, with provenance.

RarePlanes (CosmiQ Works / In-Q-Tel, Shermeyer et al. 2020) is published under CC BY-SA 4.0 in the public
bucket rareplanes-public on S3: 512 px tiles of satellite imagery with per-aircraft boxes. This script takes
the tiled COCO annotations, samples N training tiles and M test tiles that contain aircraft (spread over
locations, seeded), downloads only those tiles over HTTPS (no account, no client), writes YOLO labels with a
single class "aircraft", a data.yaml and a manifest with every file's SHA-256, the licence and the citation.
Re-running is idempotent: existing tiles are not fetched again.

    scripts/rareplanes_subset.py --train 500 --val 120 --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

BUCKET = "https://rareplanes-public.s3.amazonaws.com"
ROOT = Path("data/space/rareplanes")
LICENCE = "CC BY-SA 4.0 (RarePlanes, CosmiQ Works / In-Q-Tel; Shermeyer, Hossler, Van Etten, Hogan, Lewis, Kim, 'RarePlanes: Synthetic Data Takes Flight', 2020)"


def pick(coco: dict, n: int, seed: int) -> list[dict]:
    """Tiles with at least one aircraft, sampled round-robin over locations so one airport does not dominate."""
    by_image: dict[int, list[dict]] = {}
    for a in coco["annotations"]:
        by_image.setdefault(int(a["image_id"]), []).append(a)
    images = {im["id"]: im for im in coco["images"]}
    by_loc: dict[str, list[int]] = {}
    for iid in by_image:
        loc = str(images[iid]["file_name"].split("_")[0])
        by_loc.setdefault(loc, []).append(iid)
    rng = random.Random(seed)
    for ids in by_loc.values():
        rng.shuffle(ids)
    out: list[dict] = []
    locs = sorted(by_loc)
    while len(out) < n and any(by_loc[loc] for loc in locs):
        for loc in locs:
            if by_loc[loc] and len(out) < n:
                iid = by_loc[loc].pop()
                out.append({"image": images[iid], "annotations": by_image[iid]})
    return out


def fetch(url: str, dest: Path, retries: int = 3) -> None:
    if dest.is_file() and dest.stat().st_size > 0:
        return
    for k in range(retries):
        try:
            with urlopen(Request(url, headers={"User-Agent": "aero-audit/1.2 (research; passive)"}), timeout=60) as r:
                dest.write_bytes(r.read())
            return
        except Exception:
            if k == retries - 1:
                raise
            time.sleep(1.5 * (k + 1))


def write_split(coco: dict, split: str, n: int, seed: int, out: Path, workers: int) -> list[dict]:
    rows = pick(coco, n, seed)
    img_dir, lbl_dir = out / "images" / split, out / "labels" / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    src_split = "train" if split == "train" else "test"

    def one(row: dict) -> dict:
        im = row["image"]
        name = im["file_name"]
        dest = img_dir / name
        fetch(f"{BUCKET}/real/{src_split}/PS-RGB_tiled/{name}", dest)
        w, h = float(im["width"]), float(im["height"])
        lines = []
        for a in row["annotations"]:
            x, y, bw, bh = a["bbox"]
            cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
            lines.append(f"0 {min(max(cx, 0), 1):.6f} {min(max(cy, 0), 1):.6f} {min(bw / w, 1):.6f} {min(bh / h, 1):.6f}")
        (lbl_dir / (Path(name).stem + ".txt")).write_text("\n".join(lines) + "\n")
        return {"file": f"images/{split}/{name}", "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "bytes": dest.stat().st_size, "aircraft": len(row["annotations"]),
                "roles": sorted({a.get("role") for a in row["annotations"] if a.get("role")}), "source": f"{BUCKET}/real/{src_split}/PS-RGB_tiled/{name}"}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, rows))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", type=int, default=500)
    ap.add_argument("--val", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=ROOT / "yolo")
    args = ap.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    for f in ("RarePlanes_Train_Coco_Annotations_tiled.json", "RarePlanes_Test_Coco_Annotations_tiled.json"):
        fetch(f"{BUCKET}/real/metadata_annotations/{f}", ROOT / f)
    train = json.loads((ROOT / "RarePlanes_Train_Coco_Annotations_tiled.json").read_text())
    test = json.loads((ROOT / "RarePlanes_Test_Coco_Annotations_tiled.json").read_text())
    t0 = time.time()
    rows_train = write_split(train, "train", args.train, args.seed, args.out, args.workers)
    rows_val = write_split(test, "val", args.val, args.seed, args.out, args.workers)
    (args.out / "data.yaml").write_text(f"path: {args.out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: aircraft\n")
    manifest = {"dataset": "RarePlanes real tiled subset", "licence": LICENCE, "source": BUCKET, "seed": args.seed, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "train": {"tiles": len(rows_train), "aircraft": sum(r["aircraft"] for r in rows_train), "files": rows_train},
                "val": {"tiles": len(rows_val), "aircraft": sum(r["aircraft"] for r in rows_val), "files": rows_val}, "seconds": round(time.time() - t0, 1)}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"train {len(rows_train)} tiles / {manifest['train']['aircraft']} aircraft; val {len(rows_val)} tiles / {manifest['val']['aircraft']} aircraft; {manifest['seconds']} s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
