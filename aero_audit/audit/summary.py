"""Executive summary lines shared by the Markdown and HTML report renderers."""

from __future__ import annotations

from datetime import UTC, datetime

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


__all__ = ["_fmt_ts", "executive_summary"]
