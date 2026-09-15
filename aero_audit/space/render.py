"""Multi-view renders of 3D models with nothing but numpy: the missing half of the training set.

NASA-3D-Resources ships spacecraft as OBJ / 3DS / LWO; the preview images are one angle each.
A detector needs the same object from many viewpoints, scales and lighting. This module reads
Wavefront OBJ (triangles and polygons, which are fanned), rotates the mesh through a set of
viewpoints, and rasterises a z-buffered, Lambert-shaded silhouette onto a background, writing
PNGs with a manifest that carries the view parameters and the model's SHA-256. It is a software
rasteriser, not a renderer: no textures, no shadows, a single directional light. That is enough
for shape and silhouette, which is what the scene classifier and a detector fine-tune learn from.

OBJ only: the 3DS and LWO models need a converter (Blender or assimp, both outside this tree).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

RENDER_DIR = Path("data/space/renders")
DEFAULT_SIZE = 256


def load_obj(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) and triangle indices (m, 3); polygons with more than three vertices are fanned."""
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    for raw in Path(path).read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                v = tok.split("/")[0]
                if not v:
                    continue
                i = int(v)
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not verts or not faces:
        raise ValueError(f"no geometry in {path}")
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if f.max() >= len(v) or f.min() < 0:
        raise ValueError(f"face index out of range in {path}")
    return v, f


def normalise(v: np.ndarray) -> np.ndarray:
    """Centre on the bounding-box midpoint and scale the longest extent to 1."""
    lo, hi = v.min(axis=0), v.max(axis=0)
    centre = (lo + hi) / 2.0
    extent = float((hi - lo).max()) or 1.0
    return (v - centre) / extent


def rotation(yaw_deg: float, pitch_deg: float, roll_deg: float = 0.0) -> np.ndarray:
    y, p, r = (math.radians(a) for a in (yaw_deg, pitch_deg, roll_deg))
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return rz @ rx @ ry


def viewpoints(n_yaw: int = 12, pitches: tuple[float, ...] = (-30.0, 0.0, 30.0)) -> list[tuple[float, float]]:
    return [(360.0 * i / n_yaw, p) for p in pitches for i in range(n_yaw)]


def rasterise(v: np.ndarray, f: np.ndarray, size: int = DEFAULT_SIZE, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, scale: float = 0.8,
              light: tuple[float, float, float] = (0.3, 0.5, 1.0), background: float = 0.05) -> np.ndarray:
    """Orthographic z-buffer rasteriser; returns a float image in [0, 1] of shape (size, size)."""
    pts = normalise(v) @ rotation(yaw, pitch, roll).T
    xy = (pts[:, :2] * scale + 0.5) * (size - 1)
    z = pts[:, 2]
    img = np.full((size, size), background, dtype=np.float32)
    zbuf = np.full((size, size), -np.inf, dtype=np.float32)
    lt = np.asarray(light, dtype=np.float64)
    lt /= np.linalg.norm(lt)
    tri = pts[f]  # (m, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norms = np.linalg.norm(n, axis=1)
    keep = norms > 1e-12
    n = n[keep] / norms[keep, None]
    shade = 0.15 + 0.85 * np.abs(n @ lt)  # two-sided Lambert
    for (a, b, c), s in zip(f[keep], shade, strict=True):
        p0, p1, p2 = xy[a], xy[b], xy[c]
        x0, x1 = int(max(0, math.floor(min(p0[0], p1[0], p2[0])))), int(min(size - 1, math.ceil(max(p0[0], p1[0], p2[0]))))
        y0, y1 = int(max(0, math.floor(min(p0[1], p1[1], p2[1])))), int(min(size - 1, math.ceil(max(p0[1], p1[1], p2[1]))))
        if x1 < x0 or y1 < y0:
            continue
        det = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
        if abs(det) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        w1 = ((xs - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (ys - p0[1])) / det
        w2 = ((p1[0] - p0[0]) * (ys - p0[1]) - (xs - p0[0]) * (p1[1] - p0[1])) / det
        w0 = 1.0 - w1 - w2
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        depth = w0 * z[a] + w1 * z[b] + w2 * z[c]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (depth > sub)
        sub[upd] = depth[upd]
        img[y0:y1 + 1, x0:x1 + 1][upd] = float(s)
    return img[::-1]  # image rows grow downwards


def render_views(model: str | Path, dest: str | Path = RENDER_DIR, label: str | None = None, size: int = DEFAULT_SIZE, n_yaw: int = 12,
                 pitches: tuple[float, ...] = (-30.0, 0.0, 30.0), scales: tuple[float, ...] = (0.8,), backgrounds: tuple[float, ...] = (0.05,)) -> dict[str, Any]:
    """Render every viewpoint × scale × background to PNG under dest/<label>/ and write a manifest with provenance."""
    try:
        import cv2
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("rendering needs OpenCV to write PNGs: uv pip install -e '.[vision]'") from e
    model = Path(model)
    v, f = load_obj(model)
    label = label or model.stem
    out_dir = Path(dest) / _safe(label)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_sha = hashlib.sha256(model.read_bytes()).hexdigest()
    views = []
    for yaw, pitch in viewpoints(n_yaw, pitches):
        for scale in scales:
            for bg in backgrounds:
                img = rasterise(v, f, size, yaw, pitch, 0.0, scale, background=bg)
                name = f"{_safe(label)}_y{int(yaw):03d}_p{int(pitch):+03d}_s{int(scale * 100):03d}_b{int(bg * 100):02d}.png"
                p = out_dir / name
                cv2.imwrite(str(p), (np.clip(img, 0, 1) * 255).astype(np.uint8))
                views.append({"file": str(p), "yaw": yaw, "pitch": pitch, "scale": scale, "background": bg, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest = {"format": "aero-audit-renders/1", "model": str(model), "model_sha256": model_sha, "label": label, "vertices": len(v), "triangles": len(f),
                "size": size, "rendered_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()), "views": views,
                "method": "numpy orthographic z-buffer, two-sided Lambert, no textures"}
    (out_dir / "renders.manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def dataset_items(manifest: dict[str, Any], label: str | None = None) -> list[dict[str, Any]]:
    """Render manifest entries as dataset items (see dataset.item) so they can join a training manifest."""
    from .dataset import item

    lab = label or manifest["label"]
    return [item(vw["file"], lab, "nasa3d-render", model=manifest["model"], model_sha256=manifest["model_sha256"], yaw=vw["yaw"], pitch=vw["pitch"]) for vw in manifest["views"]]


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:80] or "model"


__all__ = ["DEFAULT_SIZE", "RENDER_DIR", "dataset_items", "load_obj", "normalise", "rasterise", "render_views", "rotation", "viewpoints"]
