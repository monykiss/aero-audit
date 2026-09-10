"""Provenance for every report: which code, data, model, thresholds, and evaluation produced it.

A finding is only as credible as the chain behind it. ``build()`` collects the tool version and git
commit, the input recording and its SHA-256, the model's SHA-256 and registry status, the
evaluation file that weights the ranking, and any ``aero.toml`` overrides in force. ``manifest()``
then hashes the written report files so the bundle can be checked later with ``aero log verify-report``.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__, tuning

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_FILE = Path("models/evaluation.json")


def sha256_file(path: str | Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def git_commit() -> dict[str, Any] | None:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=3, check=False)
        if rev.returncode != 0:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True, timeout=3, check=False)
        return {"commit": rev.stdout.strip(), "dirty": bool(dirty.stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        return None


def describe_source(recording: str | Path | None = None, **live: Any) -> dict[str, Any]:
    """Source block: a recording (with hash) or a live provider/region description."""
    if recording:
        p = Path(recording)
        return {"kind": "recording", "path": str(p), "sha256": sha256_file(p),
                "bytes": p.stat().st_size if p.is_file() else None}
    return {"kind": "live", **live}


def build(engine: Any, source: dict[str, Any] | None = None) -> dict[str, Any]:
    s = engine.summary()
    ml = getattr(engine, "ml_model", None)
    model = None
    if ml is not None:
        model = {"path": getattr(ml, "loaded_from_", None), "sha256": getattr(ml, "sha256_", None),
                 "verified_against_registry": getattr(ml, "verified_", None), "threshold": getattr(ml, "threshold_", None),
                 "rows_trained": getattr(ml, "n_train_", None)}
    overrides = {k: dict(v) for k, v in tuning._applied.items()} if getattr(tuning, "_applied", None) else {}
    return {
        "tool": "aero-audit", "version": __version__, "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0], "platform": platform.platform(), "git": git_commit(),
        "source": source or {"kind": "engine", "provider": s.get("provider"), "region": s.get("region")},
        "window": {"first_ts": s.get("first_ts"), "last_ts": s.get("last_ts"), "batches": s.get("batches"),
                   "state_vectors": s.get("state_vectors"), "unique_aircraft": s.get("unique_aircraft")},
        "model": model,
        "evaluation": {"path": str(EVALUATION_FILE), "sha256": sha256_file(EVALUATION_FILE)} if EVALUATION_FILE.is_file() else None,
        "tuning_overrides": overrides,
        "rules_engaged": sorted(s.get("by_rule", {}).keys()),
    }


def manifest(files: dict[str, Path], provenance: dict[str, Any]) -> dict[str, Any]:
    return {"format": "aero-audit-manifest/1", "generated_at": provenance.get("generated_at"),
            "files": {k: {"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size} for k, p in files.items()},
            "provenance": provenance}


def verify_manifest(path: str | Path) -> dict[str, Any]:
    """Re-hash every file a manifest names; report which still match."""
    mp = Path(path)
    m = json.loads(mp.read_text())
    out: dict[str, Any] = {"manifest": str(mp), "ok": True, "files": {}}
    for k, f in m.get("files", {}).items():
        p = Path(f["path"])
        if not p.is_absolute():
            p = mp.parent / p.name
        actual = sha256_file(p)
        ok = actual is not None and actual == f.get("sha256")
        out["files"][k] = {"path": str(p), "expected": f.get("sha256"), "actual": actual, "ok": ok}
        out["ok"] = out["ok"] and ok
    return out


def render_markdown(p: dict[str, Any]) -> list[str]:
    g = p.get("git") or {}
    src = p.get("source") or {}
    m = p.get("model")
    lines = ["## Provenance", "",
             f"- Tool: aero-audit {p['version']} on Python {p['python']} ({p['platform']})",
             f"- Code: commit `{g.get('commit', 'unknown')[:12]}`{' (uncommitted changes)' if g.get('dirty') else ''}" if g else "- Code: not a git checkout",
             f"- Generated: {p['generated_at']}"]
    if src.get("kind") == "recording":
        lines.append(f"- Input: `{src.get('path')}` sha256 `{(src.get('sha256') or '')[:16]}…` ({src.get('bytes')} bytes)")
    else:
        lines.append("- Input: " + ", ".join(f"{k}={v}" for k, v in src.items() if k != "kind"))
    lines.append(f"- Model: `{m['path']}` sha256 `{(m['sha256'] or '')[:16]}…`, registry match: {m['verified_against_registry']}" if m else "- Model: none (rules only)")
    ev = p.get("evaluation")
    lines.append(f"- Evaluation weighting: `{ev['path']}` sha256 `{(ev['sha256'] or '')[:16]}…`" if ev else "- Evaluation weighting: none on disk (precision floor applies)")
    ov = p.get("tuning_overrides") or {}
    lines.append("- Threshold overrides: " + ("; ".join(f"[{s}] {', '.join(f'{k}={v}' for k, v in kv.items())}" for s, kv in ov.items()) if ov else "none"))
    return lines + [""]


__all__ = ["build", "describe_source", "git_commit", "manifest", "render_markdown", "sha256_file", "verify_manifest"]
