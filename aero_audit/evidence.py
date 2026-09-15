"""Evidence bundles: everything an auditor needs, in one zip, with a manifest that proves it was
not altered afterwards.

A bundle holds the hash-chained audit log and its verification result, every report with its
manifest (optionally only those newer than N days), the model card, registry and evaluation file,
the effective thresholds, generated documentation, app settings with the alert webhook redacted
(a webhook URL is a credential), and ``BUNDLE.json``: tool version, git commit, creation time,
and the SHA-256 and size of every file in the zip. ``verify_bundle`` re-hashes the members.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__, provenance

DEFAULT_MEMBERS = ("data/app/audit.jsonl", "models/evaluation.json", "models/registry.json", "models/kinematic_iforest.md", "aero.toml",
                   "data/samples/ATTRIBUTION.md", "SECURITY.md", "CHANGELOG.md")
REDACT_KEYS = ("alert_webhook",)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(since_days: float | None = None, reports_dir: str | Path = "reports", docs_dir: str | Path = "docs/generated") -> list[Path]:
    cutoff = time.time() - since_days * 86400 if since_days else None
    files: list[Path] = [Path(p) for p in DEFAULT_MEMBERS if Path(p).is_file()]
    for p in sorted(Path(reports_dir).glob("*")):
        if p.suffix in (".json", ".md", ".html") and p.is_file() and (cutoff is None or p.stat().st_mtime >= cutoff):
            files.append(p)
    for p in sorted(Path(reports_dir, "studies").glob("*")) if Path(reports_dir, "studies").is_dir() else []:
        if p.is_file() and (cutoff is None or p.stat().st_mtime >= cutoff):
            files.append(p)
    files += [p for p in sorted(Path(docs_dir).glob("*.md")) if p.is_file()]
    return files


def _settings_redacted() -> bytes | None:
    p = Path("data/app/settings.json")
    if not p.is_file():
        return None
    try:
        s = json.loads(p.read_text())
    except ValueError:
        return None
    for k in REDACT_KEYS:
        if s.get(k):
            s[k] = "<redacted>"
    return json.dumps(s, indent=2).encode()


def build_bundle(out: str | Path | None = None, since_days: float | None = None, extra: list[str | Path] | None = None) -> Path:
    from .web.audit import AUDIT_FILE, verify_file

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = Path(out) if out else Path("reports") / f"evidence_{stamp}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = collect(since_days) + [Path(e) for e in (extra or []) if Path(e).is_file()]
    seen: set[str] = set()
    entries: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            arc = f.as_posix()
            if arc in seen or arc.endswith(".zip"):
                continue
            seen.add(arc)
            data = f.read_bytes()
            z.writestr(arc, data)
            entries[arc] = {"sha256": _sha(data), "bytes": len(data), "mtime": f.stat().st_mtime}
        red = _settings_redacted()
        if red is not None:
            z.writestr("data/app/settings.redacted.json", red)
            entries["data/app/settings.redacted.json"] = {"sha256": _sha(red), "bytes": len(red), "redacted": list(REDACT_KEYS)}
        chain = verify_file(AUDIT_FILE) if AUDIT_FILE.is_file() else {"ok": None, "error": "no audit log"}
        manifest = {"format": "aero-audit-evidence/1", "created_at": stamp, "tool": "aero-audit", "version": __version__,
                    "git": provenance.git_commit(), "since_days": since_days, "audit_chain": chain, "files": entries,
                    "count": len(entries), "bytes": sum(e["bytes"] for e in entries.values())}
        body = json.dumps(manifest, indent=1, default=str).encode()
        manifest["manifest_sha256"] = _sha(body)
        z.writestr("BUNDLE.json", json.dumps(manifest, indent=1, default=str))
    return out_path


def verify_bundle(path: str | Path) -> dict[str, Any]:
    out: dict[str, Any] = {"bundle": str(path), "ok": True, "checked": 0, "bad": [], "missing": [], "extra": []}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "BUNDLE.json" not in names:
            return {**out, "ok": False, "error": "no BUNDLE.json"}
        manifest = json.loads(z.read("BUNDLE.json"))
        for arc, e in manifest.get("files", {}).items():
            if arc not in names:
                out["missing"].append(arc)
                out["ok"] = False
                continue
            out["checked"] += 1
            if _sha(z.read(arc)) != e["sha256"]:
                out["bad"].append(arc)
                out["ok"] = False
        out["extra"] = sorted(names - set(manifest.get("files", {})) - {"BUNDLE.json"})
        if out["extra"]:
            out["ok"] = False
        out["created_at"] = manifest.get("created_at")
        out["version"] = manifest.get("version")
        out["audit_chain"] = manifest.get("audit_chain")
    return out


__all__ = ["DEFAULT_MEMBERS", "build_bundle", "collect", "verify_bundle"]
