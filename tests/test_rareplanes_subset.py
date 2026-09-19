"""The RarePlanes subset builder: location-balanced sampling, YOLO label conversion and the manifest, with the
download stubbed (no network)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rareplanes_subset", ROOT / "scripts/rareplanes_subset.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def _coco(n_locs: int = 3, per_loc: int = 4) -> dict:
    images, anns, iid, aid = [], [], 0, 0
    for loc in range(n_locs):
        for k in range(per_loc):
            iid += 1
            images.append({"id": iid, "file_name": f"{loc}_X_tile_{k}.png", "width": 512, "height": 512})
            for j in range(loc + 1):
                aid += 1
                anns.append({"id": aid, "image_id": iid, "bbox": [10.0 * j, 20.0, 100.0, 50.0], "role": "Small Civil Transport/Utility"})
    images.append({"id": 999, "file_name": "9_empty_tile_0.png", "width": 512, "height": 512})  # no aircraft: never picked
    return {"images": images, "annotations": anns, "categories": []}


def test_pick_balances_locations_and_skips_empty_tiles():
    rows = rp.pick(_coco(), 6, seed=1)
    locs = [r["image"]["file_name"].split("_")[0] for r in rows]
    assert len(rows) == 6 and locs.count("0") == 2 and locs.count("1") == 2 and locs.count("2") == 2 and "9" not in locs
    assert rp.pick(_coco(), 100, seed=1) and len(rp.pick(_coco(), 100, seed=1)) == 12  # every non-empty tile, no duplicates
    assert [r["image"]["id"] for r in rp.pick(_coco(), 5, seed=3)] == [r["image"]["id"] for r in rp.pick(_coco(), 5, seed=3)]  # seeded


def test_write_split_converts_labels_and_manifest_rows(tmp_path, monkeypatch):
    fetched = []

    def fake_fetch(url, dest, retries=3):
        fetched.append(url)
        dest.write_bytes(b"\x89PNG fake")

    monkeypatch.setattr(rp, "fetch", fake_fetch)
    rows = rp.write_split(_coco(), "val", 3, 1, tmp_path, workers=2)
    assert len(rows) == 3 and all(u.startswith(rp.BUCKET + "/real/test/PS-RGB_tiled/") for u in fetched)
    lbl = (tmp_path / "labels/val" / (Path(rows[0]["file"]).stem + ".txt")).read_text().splitlines()
    cls, cx, cy, w, h = lbl[0].split()
    assert cls == "0" and float(w) == round(100 / 512, 6) and float(h) == round(50 / 512, 6) and 0 < float(cx) < 1 and float(cy) == round(45 / 512, 6)
    assert rows[0]["sha256"] and rows[0]["bytes"] == 9 and rows[0]["aircraft"] == len(lbl) and rows[0]["roles"] == ["Small Civil Transport/Utility"]
    assert json.dumps(rows)  # serialisable into the manifest
