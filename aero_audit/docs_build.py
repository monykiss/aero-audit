"""Render the code-owned documents (threat matrix, playbooks, risk register, rule list) to
docs/generated/ so the written docs can link to tables that cannot drift from the code."""

from __future__ import annotations

from pathlib import Path

from .audit.rules import RULE_CATALOG
from .risk import assess
from .risk import render_markdown as render_register
from .security import playbooks, threats


def build(out_dir: str | Path = "docs/generated") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    p = out / "THREATS.md"
    p.write_text("# Threat catalog and detection coverage (generated)\n\n" + threats.render_markdown(threats.load_evaluation()) + "\n\n"
                 + "\n\n".join(
                     f"## {t.id} {t.name}\n\n{t.description}\n\n- Capability required: {t.capability_required}\n"
                     f"- Impact: {t.impact}\n- Mitigations: " + "; ".join(t.mitigations)
                     + (("\n- References: " + "; ".join(t.references)) if t.references else "")
                     for t in threats.THREATS))
    written.append(p)

    p = out / "PLAYBOOKS.md"
    p.write_text("# Response playbooks (generated)\n\n" + playbooks.render_markdown())
    written.append(p)

    p = out / "RISK_REGISTER.md"
    p.write_text(render_register(assess(None), "Risk register (baseline, generated)"))
    written.append(p)

    p = out / "RULES.md"
    lines = ["# Rule ids (generated)", "", "| Rule | Category | Description |", "|---|---|---|"]
    lines += [f"| {rid} | {cat} | {desc} |" for rid, (cat, desc) in RULE_CATALOG.items()]
    p.write_text("\n".join(lines) + "\n")
    written.append(p)
    return written
