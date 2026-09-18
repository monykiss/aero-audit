"""Reports for analyses that have no rules engine behind them (space, UAS, studies): JSON, Markdown and a manifest
with provenance, so C-22 ("provenance and manifests on every report") holds for every report the tool writes, not
only the ADS-B audits. The JSON shape stays what the pages and studies already read: the payload under its key
("summary", "screen", "assessment"), a "findings" list, and a "provenance" block."""

from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__
from .. import provenance as prov


def build_provenance(inputs: dict[str, str | Path] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ins = {}
    for k, v in (inputs or {}).items():
        if v is None:
            continue
        p = Path(str(v))
        ins[k] = {"path": str(v), "sha256": prov.sha256_file(p) if p.is_file() else None, "bytes": p.stat().st_size if p.is_file() else None}
    return {"tool": "aero-audit", "version": __version__, "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "python": sys.version.split()[0], "platform": platform.platform(), "git": prov.git_commit(), "inputs": ins, **(extra or {})}


def _flat(d: Any, prefix: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(d, dict) and depth < 2:
        for k, v in d.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                out.append((f"{prefix}{k}", v))
            elif isinstance(v, dict):
                out += _flat(v, f"{prefix}{k}.", depth + 1)
            elif isinstance(v, list):
                out.append((f"{prefix}{k}", f"{len(v)} item(s)"))
    return out


def render_markdown(title: str, key: str, payload: Any, findings: list[dict[str, Any]], provenance: dict[str, Any]) -> str:
    lines = [f"# {title}", "", f"Generated {provenance['generated_at']} by aero-audit {provenance['version']}"
             + (f" at commit {provenance['git']['commit'][:12]}{' (dirty)' if provenance['git'].get('dirty') else ''}" if provenance.get("git") else "") + ".", ""]
    if provenance.get("inputs"):
        lines += ["Inputs:", ""] + [f"- `{k}`: {v['path']}" + (f" (sha256 {v['sha256'][:16]}…)" if v.get("sha256") else "") for k, v in provenance["inputs"].items()] + [""]
    lines += [f"## {key.capitalize()}", "", "| Field | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in _flat(payload)[:60]] + [""]
    lines += [f"## Findings ({len(findings)})", ""]
    if findings:
        lines += ["| Rule | Severity | Object | Finding |", "|---|---|---|---|"]
        lines += [f"| {f.get('rule_id')} | {f.get('severity')} | {f.get('callsign') or f.get('icao24') or ''} | {str(f.get('title', '')).replace('|', '/')} |" for f in findings[:200]]
    else:
        lines.append("none")
    return "\n".join(lines) + "\n"


def write_generic(out_dir: str | Path, name: str, key: str, payload: Any, findings: list[Any], inputs: dict[str, str | Path] | None = None,
                  extra: dict[str, Any] | None = None, title: str | None = None) -> dict[str, Path]:
    """Write <name>_<stamp>.json / .md / .manifest.json under out_dir; returns the paths. Findings may be models or dicts."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = out / f"{name}_{stamp}"
    rows = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in findings]
    provenance = build_provenance(inputs, extra)
    json_path = base.with_suffix(".json")
    json_path.write_text(json.dumps({key: payload, "findings": rows, "provenance": provenance}, indent=1, default=str))
    md_path = base.with_suffix(".md")
    md_path.write_text(render_markdown(title or f"aero-audit report: {name}", key, payload, rows, provenance))
    manifest_path = out / f"{base.name}.manifest.json"
    manifest_path.write_text(json.dumps(prov.manifest({"json": json_path, "md": md_path}, provenance), indent=2, default=str))
    return {"json": json_path, "md": md_path, "manifest": manifest_path}


__all__ = ["build_provenance", "render_markdown", "write_generic"]
