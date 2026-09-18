"""Training data with provenance: image datasets assembled from the NASA Image and Video Library
and from the preview renders in NASA-3D-Resources, each item labelled, hashed, attributed, and
split deterministically by content hash so re-runs reproduce the same train/validation sets.

Layouts: ``manifest.json`` (the source of truth) and, on request, the ``train/<label>/`` and
``val/<label>/`` folder layout that image classifiers (ultralytics ``yolo classify``, and our own
scene classifier) consume.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DATASET_DIR = Path("data/space/dataset")
DEFAULT_CLASSES: dict[str, str] = {
    "launch": "rocket launch liftoff pad",
    "orbit": "spacecraft in orbit earth",
    "station": "international space station",
    "surface": "rover surface mars",
}
NASA3D_SUBJECTS: dict[str, str] = {"station": r"Space Station|ISS", "capsule": r"Orion|Dragon|Apollo|Capsule", "rover": r"Rover|Curiosity|Perseverance",
                                   "launcher": r"SLS|Space Launch System|Saturn|Falcon|Rocket|Booster", "probe": r"Voyager|Cassini|Juno|Hubble|Webb|Telescope|Probe"}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_for(sha256: str, val_fraction: float = 0.2) -> str:
    return "val" if int(sha256[:4], 16) / 65536.0 < val_fraction else "train"


def item(path: str | Path, label: str, source: str, **meta: Any) -> dict[str, Any]:
    p = Path(path)
    sha = _sha(p)
    return {"path": str(p), "label": label, "source": source, "sha256": sha, "bytes": p.stat().st_size, "split": split_for(sha), **meta}


async def build_from_library(classes: dict[str, str] | None = None, per_class: int = 30, dest: str | Path = DATASET_DIR, variant: str = "thumb",
                             search_fn: Callable[..., Any] | None = None, download_fn: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Search each class query in the NASA library and fetch one rendition per hit with its provenance."""
    from .nasa_images import download as _download
    from .nasa_images import search as _search

    search_fn = search_fn or _search
    download_fn = download_fn or _download
    dest = Path(dest)
    items: list[dict[str, Any]] = []
    for label, query in (classes or DEFAULT_CLASSES).items():
        hits, _ = await search_fn(query, "image", None, None, per_class)
        for it in hits[:per_class]:
            if it.copyright:
                continue  # only unencumbered items enter a training set
            try:
                p = await download_fn(it, variant, dest / "raw" / label)
            except (FileNotFoundError, PermissionError, ValueError):
                continue
            items.append(item(p, label, "nasa-images", nasa_id=it.nasa_id, title=it.title, date_created=it.date_created, query=query))
    return items


async def add_nasa3d_previews(catalog_path: str | Path, dest: str | Path = DATASET_DIR, subjects: dict[str, str] | None = None, max_bytes: int = 5_000_000,
                              download_fn: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Preview renders of NASA 3D models, labelled by subject family (a free source of clean spacecraft imagery)."""
    from .nasa3d import download as _download
    from .nasa3d import load_catalog

    download_fn = download_fn or _download
    cat = load_catalog(catalog_path)
    items: list[dict[str, Any]] = []
    for label, rx in (subjects or NASA3D_SUBJECTS).items():
        for a in cat.filter(kind="image", category="3D Models", subject=rx, max_bytes=max_bytes):
            try:
                p = await download_fn(a, Path(dest) / "raw" / label, cat.ref)
            except (ValueError, PermissionError):
                continue
            items.append(item(p, label, "nasa-3d-resources", asset=a.path, subject=a.subject, blob_sha1=a.sha))
    return items


def write_manifest(items: list[dict[str, Any]], dest: str | Path = DATASET_DIR, classes: dict[str, str] | None = None) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    counts: dict[str, dict[str, int]] = {}
    for it in items:
        counts.setdefault(it["label"], {"train": 0, "val": 0})[it["split"]] += 1
    m = {"format": "aero-audit-dataset/1", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "classes": classes or {},
         "counts": counts, "items": items, "terms": "NASA imagery is generally public domain; items with a copyright field are excluded; "
         "NASA-3D-Resources previews under the NASA Open Source Agreement; see data/samples/ATTRIBUTION.md"}
    p = dest / "manifest.json"
    p.write_text(json.dumps(m, indent=1))
    return p


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def to_classify_layout(manifest_path: str | Path, out: str | Path | None = None) -> Path:
    """train/<label>/file and val/<label>/file copies for image-classification trainers."""
    m = load_manifest(manifest_path)
    out = Path(out) if out else Path(manifest_path).parent / "classify"
    for it in m["items"]:
        src = Path(it["path"])
        if not src.is_file():
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", it["label"])
        d = out / it["split"] / safe
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, d / (it["sha256"][:12] + src.suffix.lower()))
    (out / "dataset.yaml").write_text(f"path: {out.resolve()}\ntrain: train\nval: val\nnames: {sorted({it['label'] for it in m['items']})}\n")
    return out


def verify_manifest(manifest_path: str | Path) -> dict[str, Any]:
    m = load_manifest(manifest_path)
    bad = [it["path"] for it in m["items"] if not Path(it["path"]).is_file() or _sha(Path(it["path"])) != it["sha256"]]
    return {"items": len(m["items"]), "bad": bad, "ok": not bad}


__all__ = ["DATASET_DIR", "DEFAULT_CLASSES", "NASA3D_SUBJECTS", "add_nasa3d_previews", "build_from_library", "item", "load_manifest", "split_for",
           "to_classify_layout", "verify_manifest", "write_manifest"]
