"""Multi-view renders of 3D models with nothing but numpy: the missing half of the training set.

NASA-3D-Resources ships spacecraft as OBJ / 3DS / LWO; the preview images are one angle each.
A detector needs the same object from many viewpoints, scales and lighting. This module reads
Wavefront OBJ (triangles and polygons, which are fanned), rotates the mesh through a set of
viewpoints, and rasterises a z-buffered, Lambert-shaded silhouette onto a background, writing
PNGs with a manifest that carries the view parameters and the model's SHA-256. It is a software
rasteriser, not a renderer: no textures, no shadows, a single directional light. That is enough
for shape and silhouette, which is what the scene classifier and a detector fine-tune learn from.

Formats: OBJ here; STL, GLB, 3DS and LightWave through space/mesh.py (no converter needed).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from .mesh import load_mesh, load_obj

RENDER_DIR = Path("data/space/renders")
DEFAULT_SIZE = 256




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


def _project(v: np.ndarray, f: np.ndarray, size: int, yaw: float, pitch: float, roll: float, scale: float, light: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pts = normalise(v) @ rotation(yaw, pitch, roll).T
    xy = (pts[:, :2] * scale + 0.5) * (size - 1)
    z = pts[:, 2]
    lt = np.asarray(light, dtype=np.float64)
    lt /= np.linalg.norm(lt)
    tri = pts[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norms = np.linalg.norm(n, axis=1)
    keep = norms > 1e-12
    shade = 0.15 + 0.85 * np.abs((n[keep] / norms[keep, None]) @ lt)  # two-sided Lambert
    return xy, z, f[keep], shade.astype(np.float32)


def rasterise(v: np.ndarray, f: np.ndarray, size: int = DEFAULT_SIZE, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, scale: float = 0.8,
              light: tuple[float, float, float] = (0.3, 0.5, 1.0), background: float = 0.05, chunk_px: int = 4_000_000) -> np.ndarray:
    """Orthographic z-buffer rasteriser; returns a float image in [0, 1] of shape (size, size).

    Vectorised over triangles: every (triangle, bounding-box pixel) pair is generated with a repeat/cumsum trick,
    barycentrics and depth are computed in one shot, and ``np.maximum.at`` resolves the z-buffer. Chunks bound
    memory to about ``chunk_px`` candidate pixels. Equivalent to ``_rasterise_reference`` (tested)."""
    xy, z, f, shade = _project(v, f, size, yaw, pitch, roll, scale, light)
    img = np.full(size * size, background, dtype=np.float32)
    zbuf = np.full(size * size, -np.inf, dtype=np.float32)
    if len(f) == 0:
        return img.reshape(size, size)[::-1]
    p0, p1, p2 = xy[f[:, 0]], xy[f[:, 1]], xy[f[:, 2]]
    z0, z1, z2 = z[f[:, 0]], z[f[:, 1]], z[f[:, 2]]
    det = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1])
    x0 = np.maximum(0, np.floor(np.minimum.reduce([p0[:, 0], p1[:, 0], p2[:, 0]]))).astype(np.int64)
    x1 = np.minimum(size - 1, np.ceil(np.maximum.reduce([p0[:, 0], p1[:, 0], p2[:, 0]]))).astype(np.int64)
    y0 = np.maximum(0, np.floor(np.minimum.reduce([p0[:, 1], p1[:, 1], p2[:, 1]]))).astype(np.int64)
    y1 = np.minimum(size - 1, np.ceil(np.maximum.reduce([p0[:, 1], p1[:, 1], p2[:, 1]]))).astype(np.int64)
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    ok = (w > 0) & (h > 0) & (np.abs(det) >= 1e-12)
    area = np.where(ok, w * h, 0)
    order = np.flatnonzero(ok)
    cum = np.cumsum(area[order])
    bounds = [0]
    while bounds[-1] < len(order):
        nxt = int(np.searchsorted(cum, cum[bounds[-1] - 1] + chunk_px if bounds[-1] else chunk_px, side="right"))
        bounds.append(max(nxt, bounds[-1] + 1))
    for lo, hi in pairwise(bounds):
        c = order[lo:hi]
        counts = area[c]
        total = int(counts.sum())
        if total == 0:
            continue
        tri = np.repeat(np.arange(len(c)), counts)
        starts = np.repeat(np.cumsum(counts) - counts, counts)
        k = np.arange(total) - starts
        wc = w[c][tri]
        px = x0[c][tri] + k % wc
        py = y0[c][tri] + k // wc
        a0, a1, a2 = p0[c][tri], p1[c][tri], p2[c][tri]
        dt = det[c][tri]
        w1 = ((px - a0[:, 0]) * (a2[:, 1] - a0[:, 1]) - (a2[:, 0] - a0[:, 0]) * (py - a0[:, 1])) / dt
        w2 = ((a1[:, 0] - a0[:, 0]) * (py - a0[:, 1]) - (px - a0[:, 0]) * (a1[:, 1] - a0[:, 1])) / dt
        w0 = 1.0 - w1 - w2
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        depth = (w0 * z0[c][tri] + w1 * z1[c][tri] + w2 * z2[c][tri])[inside].astype(np.float32)
        pix = (py * size + px)[inside]
        sh = shade[c][tri][inside]
        np.maximum.at(zbuf, pix, depth)
        win = depth >= zbuf[pix]
        img[pix[win]] = sh[win]
    return img.reshape(size, size)[::-1]  # image rows grow downwards


def _rasterise_reference(v: np.ndarray, f: np.ndarray, size: int = DEFAULT_SIZE, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, scale: float = 0.8,
              light: tuple[float, float, float] = (0.3, 0.5, 1.0), background: float = 0.05) -> np.ndarray:
    """Reference per-triangle loop kept for the equivalence test; ``rasterise`` is the vectorised version."""
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
    v, f = load_mesh(model)  # obj, 3ds, lwo, stl, glb
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
