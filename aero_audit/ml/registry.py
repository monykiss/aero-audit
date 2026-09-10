"""Model integrity: a trained model is a pickle, and a pickle is code. Before one is loaded it must
match an entry in the registry that ``aero train`` wrote next to it (``models/registry.json``),
by file name and SHA-256. A model nobody registered, or whose bytes changed since registration,
is refused unless the operator says otherwise (``AERO_ALLOW_UNVERIFIED_MODEL=1`` or the CLI flag).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .anomaly import KinematicAnomalyModel

ALLOW_ENV = "AERO_ALLOW_UNVERIFIED_MODEL"


class ModelIntegrityError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def registry_path(model_path: str | Path) -> Path:
    return Path(model_path).parent / "registry.json"


def verify_model(model_path: str | Path) -> dict[str, Any]:
    """Compare the file on disk with the registry. Never loads the pickle."""
    p = Path(model_path)
    info: dict[str, Any] = {"path": str(p), "exists": p.is_file(), "sha256": None, "registered": False, "match": False,
                            "entry": None, "registry": str(registry_path(p))}
    if not p.is_file():
        return info
    info["sha256"] = sha256_file(p)
    try:
        entries = json.loads(registry_path(p).read_text())
    except (OSError, ValueError):
        return info
    same_name = [e for e in entries if Path(e.get("model_path", "")).name == p.name]
    info["registered"] = bool(same_name)
    hit = next((e for e in reversed(same_name) if e.get("sha256") == info["sha256"]), None)
    if hit:
        info["match"] = True
        info["entry"] = {k: hit.get(k) for k in ("trained_at", "rows", "aircraft", "holdout_flag_rate", "recordings", "providers")}
    return info


def load_verified(model_path: str | Path, allow_unverified: bool = False) -> KinematicAnomalyModel:
    info = verify_model(model_path)
    if not info["exists"]:
        raise FileNotFoundError(f"model not found: {model_path}")
    allowed = allow_unverified or os.getenv(ALLOW_ENV) == "1"
    if not info["match"] and not allowed:
        why = ("its bytes differ from every registry entry with that name (retrained elsewhere, or tampered with)"
               if info["registered"] else f"no entry in {info['registry']} (not produced by `aero train` here)")
        raise ModelIntegrityError(
            f"refusing to load {model_path}: {why}. Retrain with `aero train`, or set {ALLOW_ENV}=1 to override.")
    model = KinematicAnomalyModel.load(model_path)
    model.loaded_from_ = str(model_path)
    model.sha256_ = info["sha256"]
    model.verified_ = bool(info["match"])
    return model


__all__ = ["ALLOW_ENV", "ModelIntegrityError", "load_verified", "registry_path", "sha256_file", "verify_model"]
