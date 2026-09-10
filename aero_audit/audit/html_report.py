"""Self-contained HTML rendering of an audit report (no external assets, safe to email)."""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from ..security.playbooks import playbook_for
from .engine import AuditEngine
from .findings import SEVERITY_ORDER

_CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1c1f24}
main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid #d9dde3;padding-bottom:4px}
.meta{color:#5a6270;font-size:13px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:#fff;border:1px solid #e1e5ea;border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:22px}.tile span{font-size:12px;color:#5a6270}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}th,td{border:1px solid #e1e5ea;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#eef1f5}.sev-critical{color:#b00020;font-weight:600}.sev-high{color:#c62828;font-weight:600}.sev-medium{color:#b26a00}.sev-low{color:#2e6da4}.sev-info{color:#6b7280}
.bar{fill:#4a76a8}.lbl{font-size:11px;fill:#1c1f24}.ev{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#3b4250;word-break:break-all}
ul.exec li{margin:3px 0}.note{font-size:12px;color:#5a6270}
"""


def _fmt_ts(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%SZ") if ts else "-"


def _bars(items: list[tuple[str, int]], width: int = 520) -> str:
    if not items:
        return "<p class='note'>none</p>"
    mx = max(v for _, v in items) or 1
    row_h, label_w = 18, 110
    h = row_h * len(items) + 4
    out = [f"<svg width='{width}' height='{h}' role='img'>"]
    for i, (k, v) in enumerate(items):
        y = i * row_h + 2
        w = int((width - label_w - 50) * v / mx)
        out.append(f"<text class='lbl' x='0' y='{y + 13}'>{html.escape(k)}</text>"
                   f"<rect class='bar' x='{label_w}' y='{y + 2}' width='{max(w, 1)}' height='{row_h - 6}'/>"
                   f"<text class='lbl' x='{label_w + w + 4}' y='{y + 13}'>{v}</text>")
    out.append("</svg>")
    return "".join(out)


def render_html(engine: AuditEngine, title: str, max_findings: int = 150) -> str:
    from .report import executive_summary

    s = engine.summary()
    exec_lines = [ln.strip() for ln in executive_summary(engine) if ln.strip() and not ln.startswith("## ")]
    exec_html = "".join(
        f"<li>{html.escape(ln.lstrip('- ').lstrip('1. '))}</li>" for ln in exec_lines
    )
    sev_items = [(sv.value, s["by_severity"][sv.value]) for sv in SEVERITY_ORDER]
    rule_items = sorted(s["by_rule"].items(), key=lambda kv: -kv[1])
    comp = f"{s['adsb_compliance_rate']:.1%}" if s.get("adsb_compliance_rate") is not None else "n/a"
    tiles = [
        (str(s["unique_aircraft"]), "aircraft"), (str(s["findings_total"]), "findings"),
        (str(s["by_severity"]["critical"] + s["by_severity"]["high"]), "critical + high"),
        (comp, "ADS-B integrity compliance"), (str(len(s["low_trust_aircraft"])), "low-trust aircraft"),
        (str(s["batches"]), "polls"),
    ]
    rows = []
    for f in sorted(engine.findings, key=lambda x: x.risk_score, reverse=True)[:max_findings]:
        pb = playbook_for(f.rule_id)
        ev = {k: v for k, v in f.evidence.items() if k not in ("feed",)}
        rows.append(
            f"<tr><td class='sev-{f.severity.value}'>{f.severity.value}</td><td>{html.escape(f.rule_id)}</td>"
            f"<td>{html.escape(f.icao24 or '-')}<br><span class='note'>{html.escape(f.callsign or '')}</span></td>"
            f"<td>{_fmt_ts(f.ts)}</td><td>{f.risk_score:.1f}</td><td>{f.occurrences}</td>"
            f"<td>{html.escape(f.title)}<br><span class='note'>{html.escape(pb.triage[0]) if pb else ''}</span></td>"
            f"<td class='ev'>{html.escape(json.dumps(ev, default=str))[:400]}</td></tr>"
        )
    top = "".join(f"<tr><td>{html.escape(k)}</td><td>{v:.1f}</td></tr>" for k, v in s["top_aircraft_by_risk"])
    low = "".join(f"<tr><td>{html.escape(k)}</td><td>{v:.2f}</td><td>{n}</td></tr>" for k, v, n in s["low_trust_aircraft"])
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<div class='meta'>Provider {html.escape(str(s['provider']))} · region {html.escape(str(s['region']))} · {_fmt_ts(s['first_ts'])} to {_fmt_ts(s['last_ts'])} · generated {datetime.now(UTC):%Y-%m-%d %H:%M:%SZ} by aero-audit</div>
<div class='tiles'>{"".join(f"<div class='tile'><b>{html.escape(v)}</b><span>{html.escape(l)}</span></div>" for v, l in tiles)}</div>
<h2>Executive summary</h2><ul class='exec'>{exec_html}</ul>
<h2>Findings by severity</h2>{_bars(sev_items)}
<h2>Findings by rule</h2>{_bars(rule_items)}
<h2>Top aircraft by cumulative risk</h2><table><tr><th>ICAO24</th><th>Risk</th></tr>{top or "<tr><td colspan='2'>none</td></tr>"}</table>
<h2>Low-trust aircraft (trust &lt; 0.5)</h2><table><tr><th>ICAO24</th><th>Trust</th><th>Findings</th></tr>{low or "<tr><td colspan='3'>none</td></tr>"}</table>
<h2>Findings (top {min(max_findings, len(engine.findings))} by risk score)</h2>
<table><tr><th>Severity</th><th>Rule</th><th>Aircraft</th><th>Time</th><th>Risk</th><th>Occ.</th><th>Finding / first playbook step</th><th>Evidence</th></tr>{"".join(rows)}</table>
<p class='note'>Findings are signals for review, not determinations. Playbooks: <code>aero security playbook &lt;RULE&gt;</code>. Full detail in the JSON report.</p>
</main></body></html>"""
