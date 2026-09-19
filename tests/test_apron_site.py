"""The per-site few-shot script's crop sampler: windows land inside the image, keep only the boxes they contain, and
express them in window coordinates (offline, synthetic image)."""

import importlib.util
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIL = pytest.importorskip("PIL.Image")
spec = importlib.util.spec_from_file_location("apron_site_finetune", ROOT / "scripts/apron_site_finetune.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_crops_keep_contained_boxes_in_window_coordinates():
    img = PIL.new("RGB", (1000, 800), (30, 30, 30))
    boxes = [(0.30, 0.45, 0.06, 0.05), (0.40, 0.50, 0.06, 0.05), (0.90, 0.50, 0.06, 0.05)]  # two west stands, one east
    out = mod.crops(img, boxes, side=320, n=10, rng=random.Random(3), xmin=0.25, xmax=0.49)
    assert out and all(c.size == (320, 320) for c, _ in out)
    for _crop, inside in out:
        assert inside and all(0 <= cx <= 1 and 0 <= cy <= 1 for cx, cy, _w, _h in inside)
        assert all(abs(w - 0.06 * 1000 / 320) < 1e-9 for _cx, _cy, w, _h in inside)  # widths rescaled to the window
        assert len(inside) <= 2  # the east stand is never inside a west window
    assert mod.crops(img, [(0.90, 0.50, 0.06, 0.05)], 320, 5, random.Random(1), 0.0, 0.2) == []  # no box in that band: no windows
