"""Dataset manifests with deterministic splits, the scene classifier with its registry gate, and injectable library fetches."""

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from aero_audit.space import classifier, dataset


def _images(root: Path, n: int = 14):
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(1)
    items = []
    for label, base, pattern in (("red", (0, 0, 200), "stripes"), ("green", (0, 200, 0), "checker"), ("blue", (200, 0, 0), "plain")):
        d = root / "raw" / label
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            img = np.zeros((64, 64, 3), dtype=np.uint8)
            img[:] = base
            if pattern == "stripes":
                img[::8, :, :] = 255
            elif pattern == "checker":
                img[(np.indices((64, 64)).sum(axis=0) // 8) % 2 == 0] = (255, 255, 255)
            img = np.clip(img.astype(int) + rng.integers(-25, 25, img.shape), 0, 255).astype(np.uint8)
            p = d / f"{label}_{i}.png"
            cv2.imwrite(str(p), img)
            items.append(dataset.item(p, label, "synthetic", index=i))
    return items


def test_manifest_splits_layout_and_verification(tmp_path):
    items = _images(tmp_path, 12)
    mp = dataset.write_manifest(items, tmp_path, {"red": "q1", "green": "q2", "blue": "q3"})
    m = dataset.load_manifest(mp)
    assert m["format"] == "aero-audit-dataset/1" and set(m["counts"]) == {"red", "green", "blue"}
    assert all(dataset.split_for(it["sha256"]) == it["split"] for it in m["items"])
    assert 0 < sum(1 for it in m["items"] if it["split"] == "val") < len(m["items"])
    layout = dataset.to_classify_layout(mp)
    assert (layout / "dataset.yaml").is_file() and any((layout / "train").iterdir()) and any((layout / "val").iterdir())
    assert dataset.verify_manifest(mp)["ok"]
    Path(m["items"][0]["path"]).write_bytes(b"corrupt")
    assert not dataset.verify_manifest(mp)["ok"]


def test_scene_classifier_trains_evaluates_and_is_registry_gated(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    monkeypatch.chdir(tmp_path)
    items = _images(tmp_path, 16)
    mp = dataset.write_manifest(items, tmp_path)
    out = tmp_path / "models" / "scene_classifier.joblib"
    stats = classifier.train(mp, out)
    assert stats["accuracy"] >= 0.9 and set(stats["classes"]) == {"red", "green", "blue"} and out.with_suffix(".md").is_file()
    reg = json.loads((out.parent / "registry.json").read_text())
    assert reg[-1]["sha256"] == stats["sha256"] and reg[-1]["evaluation"]["accuracy"] == stats["accuracy"]
    model = classifier.load(out)
    assert model["verified_"] and model["classes"] == stats["classes"]
    preds = classifier.predict(model, [items[0]["path"], items[-1]["path"]])
    assert preds[0]["label"] == "red" and preds[1]["label"] == "blue" and 0 < preds[0]["proba"] <= 1
    frames = {"frames": [{"file": items[0]["path"], "t_s": 0.0}, {"file": items[20]["path"], "t_s": 1.0}]}
    cf = classifier.classify_frames(frames, model)
    assert cf[0]["label"] == "red" and cf[1]["label"] == "green" and cf[1]["t_s"] == 1.0
    data = bytearray(out.read_bytes())
    data[len(data) // 3] ^= 0x55
    out.write_bytes(bytes(data))
    with pytest.raises(classifier.ModelIntegrityError):
        classifier.load(out)
    with pytest.raises(ValueError):
        classifier.train(dataset.write_manifest(items[:3], tmp_path / "thin"), tmp_path / "models" / "x.joblib")


def test_build_from_library_with_injected_fetchers(tmp_path):
    pytest.importorskip("cv2")
    cv2 = __import__("cv2")

    class Item:
        def __init__(self, nid, copyright=None):
            self.nasa_id, self.title, self.date_created, self.copyright = nid, f"t {nid}", "2026-01-01", copyright

    async def fake_search(q, media, y0, y1, n):
        return [Item(f"{q[:3]}-{i}") for i in range(n)] + [Item("copyrighted", "someone")], n + 1

    async def fake_download(it, variant, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        p = Path(dest) / f"{it.nasa_id}.png"
        cv2.imwrite(str(p), np.full((32, 32, 3), 100, dtype=np.uint8))
        return p

    items = asyncio.run(dataset.build_from_library({"a": "alpha q", "b": "beta q"}, 3, tmp_path, search_fn=fake_search, download_fn=fake_download))
    assert len(items) == 6 and all(it["source"] == "nasa-images" for it in items) and not any(it["nasa_id"] == "copyrighted" for it in items)
