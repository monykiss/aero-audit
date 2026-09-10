"""Threshold overrides from an `aero.toml` file, so operators tune without editing code.

Sections map to modules; keys must already exist as UPPER_CASE constants there, so a typo
fails loudly instead of silently doing nothing.

    [rules]
    MAX_PLAUSIBLE_GS_KT = 800.0
    [engine]
    ML_MIN_FLAGS = 3
"""

from __future__ import annotations

import importlib
import os
import tomllib
from pathlib import Path
from typing import Any

SECTIONS: dict[str, str] = {
    "rules": "aero_audit.audit.rules",
    "engine": "aero_audit.audit.engine",
    "policy": "aero_audit.audit.policy",
    "anomaly": "aero_audit.ml.anomaly",
    "corroborate": "aero_audit.security.corroborate",
    "trust": "aero_audit.security.trust",
}
DEFAULT_PATH = Path(os.getenv("AERO_TUNING", "aero.toml"))
_applied: dict[str, dict[str, Any]] = {}


def _plain(v: Any) -> bool:
    """Numbers, or containers of numbers/strings: registries of functions are not tunables."""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float, str)):
        return True
    if isinstance(v, dict):
        return all(_plain(x) for x in v.values())
    if isinstance(v, (tuple, list)):
        return all(_plain(x) for x in v)
    return False


def tunables(section: str) -> dict[str, Any]:
    mod = importlib.import_module(SECTIONS[section])
    return {k: v for k, v in vars(mod).items()
            if k.isupper() and not k.startswith("_") and isinstance(v, (int, float, dict, tuple, list)) and _plain(v)}


def apply(path: str | Path = DEFAULT_PATH) -> dict[str, dict[str, Any]]:
    """Apply overrides; returns {section: {key: value}} that were applied. Missing file = no-op."""
    path = Path(path)
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text())
    applied: dict[str, dict[str, Any]] = {}
    for section, values in data.items():
        if section not in SECTIONS:
            raise KeyError(f"aero.toml: unknown section [{section}]; known: {', '.join(SECTIONS)}")
        mod = importlib.import_module(SECTIONS[section])
        allowed = tunables(section)
        for key, value in values.items():
            if key not in allowed:
                raise KeyError(f"aero.toml: [{section}] has no tunable '{key}'; known: {', '.join(sorted(allowed))}")
            if isinstance(allowed[key], dict) and isinstance(value, dict):
                getattr(mod, key).update(value)
            else:
                setattr(mod, key, type(allowed[key])(value) if isinstance(allowed[key], (int, float)) else value)
            applied.setdefault(section, {})[key] = value
    _applied.clear()
    _applied.update(applied)
    return applied


def effective() -> list[tuple[str, str, Any, bool]]:
    """(section, key, value, overridden) for every tunable."""
    rows = []
    for section in SECTIONS:
        for k, v in sorted(tunables(section).items()):
            rows.append((section, k, v, k in _applied.get(section, {})))
    return rows


def template() -> str:
    lines = ["# aero.toml: threshold overrides. Delete keys you do not change.", ""]
    for section in SECTIONS:
        lines.append(f"[{section}]")
        for k, v in sorted(tunables(section).items()):
            if isinstance(v, (int, float)):
                lines.append(f"# {k} = {v}")
        lines.append("")
    return "\n".join(lines)
