"""Scene classifier for space imagery and footage frames: an honest, dependency-light baseline
(colour histogram + HOG features, logistic regression) trained from a dataset manifest, evaluated
on the manifest's validation split, saved with a model card and a registry entry so the same
checksum gate that protects the anomaly model protects this one.

It answers "what kind of scene is this frame" (launch, orbit, station, surface, ...), which is
what the footage pipeline needs to segment a broadcast; object detection of rockets and
spacecraft still needs a fine-tuned detector (scripts/train_detector.py).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..ml.registry import ALLOW_ENV, ModelIntegrityError, verify_model
from .dataset import load_manifest

FEATURE_VERSION = "hsv8x8x4+grad8x8x9"
MODEL_PATH = Path("models/scene_classifier.joblib")


def _cv2():
    try:
        import cv2
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("the scene classifier needs OpenCV: uv pip install -e '.[vision]'") from e
    return cv2


def features(path: str | Path) -> np.ndarray:
    cv2 = _cv2()
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"cannot read image {path}")
    img = cv2.resize(img, (128, 128), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 4], [0, 180, 0, 256, 0, 256]).flatten()
    hist = hist / max(hist.sum(), 1.0)
    gray = cv2.cvtColor(cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    return np.concatenate([hist.astype(np.float32), gradient_histogram(gray, cv2)])


def gradient_histogram(gray: np.ndarray, cv2: Any, cells: int = 8, bins: int = 9) -> np.ndarray:
    """HOG-like descriptor without cv2.HOGDescriptor (absent from some OpenCV builds): per-cell histograms of
    gradient orientation weighted by magnitude, L2-normalised per cell."""
    gray = cv2.GaussianBlur(gray, (5, 5), 0)  # thumbnails and broadcast frames carry pixel noise; gradients should describe structure
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) % np.pi) / np.pi * bins  # unsigned orientation in [0, bins)
    h, w = gray.shape
    ch, cw = h // cells, w // cells
    out = np.zeros((cells, cells, bins), dtype=np.float32)
    for i in range(cells):
        for j in range(cells):
            a = ang[i * ch:(i + 1) * ch, j * cw:(j + 1) * cw].ravel()
            m = mag[i * ch:(i + 1) * ch, j * cw:(j + 1) * cw].ravel()
            hist_c, _ = np.histogram(a, bins=bins, range=(0, bins), weights=m)
            out[i, j] = hist_c / (np.linalg.norm(hist_c) + 1e-6)
    return out.ravel().astype(np.float32)


def _register(out: Path, stats: dict[str, Any]) -> None:
    reg = out.parent / "registry.json"
    try:
        entries = json.loads(reg.read_text())
    except (OSError, ValueError):
        entries = []
    entries.append({"trained_at": stats["trained_at"], "model_path": str(out), "sha256": stats["sha256"], "recordings": [stats["manifest"]],
                    "providers": stats["sources"], "regions": stats["classes"], "rows": stats["n_train"], "aircraft": 0, "contamination": 0.0,
                    "features": [FEATURE_VERSION], "holdout_flag_rate": round(1.0 - stats["accuracy"], 4), "evaluation": {"accuracy": stats["accuracy"], "per_class": stats["per_class"]}})
    reg.write_text(json.dumps(entries, indent=2))


def train(manifest_path: str | Path, out: str | Path = MODEL_PATH, min_per_class: int = 4) -> dict[str, Any]:
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    m = load_manifest(manifest_path)
    items = [it for it in m["items"] if Path(it["path"]).is_file()]
    labels = sorted({it["label"] for it in items})
    counts = {lab: sum(1 for it in items if it["label"] == lab) for lab in labels}
    thin = [lab for lab, n in counts.items() if n < min_per_class]
    if thin or len(labels) < 2:
        raise ValueError(f"need at least 2 classes with >= {min_per_class} images each; counts {counts}")
    X_tr, y_tr, X_va, y_va = [], [], [], []
    for it in items:
        f = features(it["path"])
        (X_tr if it["split"] == "train" else X_va).append(f)
        (y_tr if it["split"] == "train" else y_va).append(it["label"])
    if not X_va:
        raise ValueError("the manifest has no validation split; every class needs held-out images")
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.2))
    pipe.fit(np.array(X_tr), y_tr)
    pred = pipe.predict(np.array(X_va))
    acc = float(np.mean([p == t for p, t in zip(pred, y_va, strict=True)]))
    per_class: dict[str, dict[str, float]] = {}
    for lab in labels:
        tp = sum(1 for p, t in zip(pred, y_va, strict=True) if p == lab and t == lab)
        fp = sum(1 for p, t in zip(pred, y_va, strict=True) if p == lab and t != lab)
        fn = sum(1 for p, t in zip(pred, y_va, strict=True) if p != lab and t == lab)
        per_class[lab] = {"precision": round(tp / (tp + fp), 3) if tp + fp else 0.0, "recall": round(tp / (tp + fn), 3) if tp + fn else 0.0, "support": tp + fn}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipe, "classes": labels, "feature_version": FEATURE_VERSION, "trained_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())}, out)
    stats = {"trained_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()), "manifest": str(manifest_path), "model_path": str(out),
             "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "classes": labels, "counts": counts, "n_train": len(X_tr), "n_val": len(X_va),
             "accuracy": round(acc, 4), "per_class": per_class, "sources": sorted({it["source"] for it in items}), "feature_version": FEATURE_VERSION}
    card = out.with_suffix(".md")
    card.write_text("\n".join([
        f"# Scene classifier card ({stats['trained_at']})", "",
        f"- Model: logistic regression over {FEATURE_VERSION} features; file `{out}` sha256 `{stats['sha256'][:16]}…`",
        f"- Data: `{manifest_path}` from {', '.join(stats['sources'])}; classes {labels}; counts {counts}",
        f"- Split: {len(X_tr)} train / {len(X_va)} validation by content hash (deterministic)",
        f"- Validation accuracy: **{acc:.1%}**", "- Per class: " + "; ".join(f"{k} P {v['precision']} R {v['recall']} (n={v['support']})" for k, v in per_class.items()), "",
        "## Intended use", "Scene segmentation of launch and spaceflight footage frames; not object detection, not safety-related decisions.", "",
        "## Limits", "Small hand-labelled classes from search queries; NASA library thumbnails; colour-driven features are sensitive to broadcast overlays.",
    ]) + "\n")
    _register(out, stats)
    return stats


def load(path: str | Path = MODEL_PATH, allow_unverified: bool = False) -> dict[str, Any]:
    import os

    import joblib

    info = verify_model(path)
    if not info["exists"]:
        raise FileNotFoundError(path)
    if not info["match"] and not (allow_unverified or os.getenv(ALLOW_ENV) == "1"):
        raise ModelIntegrityError(f"refusing to load {path}: no matching registry entry (set {ALLOW_ENV}=1 to override)")
    model = joblib.load(path)
    model["verified_"] = bool(info["match"])
    model["sha256_"] = info["sha256"]
    return model


def predict(model: dict[str, Any], paths: list[str | Path]) -> list[dict[str, Any]]:
    X = np.array([features(p) for p in paths])
    proba = model["pipeline"].predict_proba(X)
    classes = list(model["pipeline"].classes_)
    out = []
    for p, row in zip(paths, proba, strict=True):
        i = int(np.argmax(row))
        out.append({"path": str(p), "label": classes[i], "proba": round(float(row[i]), 4), "scores": {c: round(float(v), 4) for c, v in zip(classes, row, strict=True)}})
    return out


YOLO_PATH = Path("models/scene_yolo_cls.pt")


def load_yolo(path: str | Path = YOLO_PATH, allow_unverified: bool = False) -> dict[str, Any]:
    """The fine-tuned YOLO classification weights behind the same registry gate; returns the same dict shape as load()."""
    import os

    info = verify_model(path)
    if not info["exists"]:
        raise FileNotFoundError(path)
    if not info["match"] and not (allow_unverified or os.getenv(ALLOW_ENV) == "1"):
        raise ModelIntegrityError(f"refusing to load {path}: no matching registry entry (set {ALLOW_ENV}=1 to override)")
    try:
        from ultralytics import YOLO
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("the YOLO classifier needs ultralytics: uv pip install -e '.[vision]'") from e
    y = YOLO(str(path))
    names = y.names if isinstance(y.names, dict) else dict(enumerate(y.names))
    return {"yolo": y, "classes": [names[k] for k in sorted(names)], "feature_version": "yolov8-cls", "verified_": bool(info["match"]), "sha256_": info["sha256"]}


def predict_any(model: dict[str, Any], paths: list[str | Path]) -> list[dict[str, Any]]:
    """predict() for the histogram model, or the YOLO classifier when the dict carries one."""
    if "yolo" not in model:
        return predict(model, paths)
    out = []
    for p, r in zip(paths, model["yolo"].predict([str(x) for x in paths], verbose=False, imgsz=224), strict=True):
        probs = r.probs
        classes = model["classes"]
        scores = {classes[i]: round(float(probs.data[i]), 4) for i in range(len(classes))}
        i = int(probs.top1)
        out.append({"path": str(p), "label": classes[i], "proba": round(float(probs.top1conf), 4), "scores": scores})
    return out


def evaluate(manifest_path: str | Path, model: dict[str, Any], split: str | None = "val") -> dict[str, Any]:
    """Accuracy and per-class precision/recall of any loaded model on a manifest (a hold-out built from other queries
    is the honest test: same labels, different images)."""
    m = load_manifest(manifest_path)
    items = [it for it in m["items"] if Path(it["path"]).is_file() and (split is None or it["split"] == split)]
    if not items:
        raise ValueError("no items to evaluate")
    preds = predict_any(model, [it["path"] for it in items])
    labels = sorted({it["label"] for it in items} | set(model["classes"]))
    y_true = [it["label"] for it in items]
    y_pred = [p["label"] for p in preds]
    acc = float(np.mean([a == b for a, b in zip(y_true, y_pred, strict=True)]))
    per: dict[str, dict[str, float]] = {}
    for lab in labels:
        tp = sum(1 for p, t in zip(y_pred, y_true, strict=True) if p == lab and t == lab)
        fp = sum(1 for p, t in zip(y_pred, y_true, strict=True) if p == lab and t != lab)
        fn = sum(1 for p, t in zip(y_pred, y_true, strict=True) if p != lab and t == lab)
        if tp + fn == 0 and tp + fp == 0:
            continue
        per[lab] = {"precision": round(tp / (tp + fp), 3) if tp + fp else 0.0, "recall": round(tp / (tp + fn), 3) if tp + fn else 0.0, "support": tp + fn}
    confusion = {}
    for t, p in zip(y_true, y_pred, strict=True):
        confusion[f"{t}->{p}"] = confusion.get(f"{t}->{p}", 0) + 1
    return {"manifest": str(manifest_path), "split": split, "n": len(items), "accuracy": round(acc, 4), "per_class": per, "confusion": confusion,
            "model_feature_version": model.get("feature_version"), "model_sha256": model.get("sha256_"), "verified": model.get("verified_")}


def classify_frames(frame_manifest: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    frames = frame_manifest["frames"]
    preds = predict_any(model, [f["file"] for f in frames]) if frames else []
    return [{"t_s": f["t_s"], **p} for f, p in zip(frames, preds, strict=True)]


__all__ = ["FEATURE_VERSION", "MODEL_PATH", "YOLO_PATH", "classify_frames", "evaluate", "features", "load", "load_yolo", "predict", "predict_any", "train"]
