"""Markdown + JSON audit reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .. import provenance as prov
from ..security.playbooks import playbook_for
from .engine import AuditEngine


def _fmt_ts(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%SZ") if ts else "-"


def executive_summary(engine: AuditEngine) -> list[str]:
    from ..risk import assess

    s = engine.summary()
    sev = s["by_severity"]
    minutes = ((s["last_ts"] or 0) - (s["first_ts"] or 0)) / 60.0
    top_risks = [r for r in assess(s) if r["rating"] in ("critical", "high")][:3]
    todo = sorted(engine.findings, key=lambda f: f.risk_score, reverse=True)[:3]
    lines = [
        "## Executive summary",
        "",
        f"- Scope: {s['unique_aircraft']} aircraft over {minutes:.0f} min from `{s['provider']}` ({s['region']}).",
        (
            f"- Posture: {s['findings_total']} findings: {sev['critical']} critical, {sev['high']} high, "
            f"{sev['medium']} medium, {sev['low']} low, {sev['info']} info."
        ),
        (f"- ADS-B integrity compliance: {s['adsb_compliance_rate']:.1%} of {s['adsb_airborne_fixes']} airborne fixes."
         if s.get("adsb_compliance_rate") is not None else "- ADS-B integrity compliance: not available from this feed."),
        f"- Aircraft with trust below 0.5: {len(s['low_trust_aircraft'])}.",
        ("- Elevated risks on this evidence: " + "; ".join(f"{r['id']} {r['rating']} (L{r['L']} x I{r['I']})" for r in top_risks)
         if top_risks else "- No register risk rises above medium on this evidence."),
    ]
    if todo:
        lines.append("- Do first:")
        for f in todo:
            pb = playbook_for(f.rule_id)
            step = f" First step: {pb.triage[0]}" if pb else ""
            lines.append(f"  1. [{f.severity.value.upper()}] {f.rule_id} {f.icao24 or '-'} {f.callsign or ''}: {f.title}.{step}")
    return lines + [""]


def render_markdown(engine: AuditEngine, title: str, provenance: dict | None = None) -> str:
    s = engine.summary()
    lines = [
        f"# {title}",
        "",
        *executive_summary(engine),
        *(prov.render_markdown(provenance) if provenance else []),
        f"- Provider: `{s['provider']}`  Region: `{s['region']}`",
        f"- Window: {_fmt_ts(s['first_ts'])} to {_fmt_ts(s['last_ts'])}  ({s['batches']} polls)",
        f"- State vectors: {s['state_vectors']}  Unique aircraft: {s['unique_aircraft']}",
        f"- Findings: **{s['findings_total']}**",
        (
            f"- ADS-B integrity compliance (NIC>=7, NACp>=8, SIL=3) on airborne ADS-B fixes: "
            f"**{s['adsb_compliance_rate']:.1%}** of {s['adsb_airborne_fixes']} fixes"
            if s.get("adsb_compliance_rate") is not None else "- ADS-B integrity compliance: n/a (feed carries no NIC/NACp/SIL)"
        ),
        "",
        "## Findings by severity",
        "",
        "| Severity | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in s["by_severity"].items()],
        "",
        "## Findings by category",
        "",
        "| Category | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in s["by_category"].items()],
        "",
        "## Findings by rule",
        "",
        "| Rule | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in s["by_rule"].items()],
        "",
        "## Top aircraft by cumulative risk",
        "",
        "| ICAO24 | Risk |",
        "|---|---|",
        *[f"| {k} | {v:.1f} |" for k, v in s["top_aircraft_by_risk"]],
        "",
        "## Low-trust aircraft (trust < 0.5)",
        "",
        "| ICAO24 | Trust | Findings |",
        "|---|---|---|",
        *[f"| {k} | {v:.2f} | {n} |" for k, v, n in s["low_trust_aircraft"]],
        "",
        "## Detail (ranked by risk score)",
        "",
    ]
    for f in sorted(engine.findings, key=lambda x: x.risk_score, reverse=True):
        who = f"{f.icao24 or '-'}" + (f" ({f.callsign})" if f.callsign else "")
        lines += [
            f"### [{f.severity.value.upper()}] {f.rule_id} {f.title}",
            (
                f"- Aircraft: `{who}`  Time: {_fmt_ts(f.ts)}  Risk: {f.risk_score:.1f}  "
                f"Occurrences: {f.occurrences}"
            ),
            f"- Evidence: `{json.dumps(f.evidence, default=str)}`",
            f"- Controls: {'; '.join(f.controls) or '-'}",
            f"- Recommendation: {f.recommendation}",
        ]
        pb = playbook_for(f.rule_id)
        if pb:
            lines.append(f"- Playbook: triage within {pb.sla_minutes} min. First step: {pb.triage[0]}")
        lines.append("")
    return "\n".join(lines)


def write_reports(engine: AuditEngine, out_dir: str | Path, name: str, source: dict | None = None) -> tuple[Path, Path, Path]:
    """Write JSON, Markdown, self-contained HTML, and a manifest with the SHA-256 of each file and the
    full provenance block; returns the JSON, Markdown, and HTML paths in that order."""
    from .html_report import render_html

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = out / f"{name}_{stamp}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    provenance = prov.build(engine, source)
    payload = {
        "summary": engine.summary(),
        "provenance": provenance,
        "findings": [f.model_dump() for f in engine.findings],
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    md_path.write_text(render_markdown(engine, f"aero-audit report: {name}", provenance))
    html_path = base.with_suffix(".html")
    html_path.write_text(render_html(engine, f"aero-audit report: {name}", provenance=provenance))
    manifest_path = base.parent / f"{base.name}.manifest.json"
    manifest_path.write_text(json.dumps(prov.manifest({"json": json_path, "md": md_path, "html": html_path}, provenance), indent=2, default=str))
    return json_path, md_path, html_path


def manifest_for(report_path: str | Path) -> Path:
    p = Path(report_path)
    return p.parent / f"{p.stem}.manifest.json"
