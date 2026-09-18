"""Render the code-owned documents (threat matrix, playbooks, risk register, rule list) to
docs/generated/ so the written docs can link to tables that cannot drift from the code."""

from __future__ import annotations

from pathlib import Path

from .audit.rules import RULE_CATALOG
from .risk import assess
from .risk import render_markdown as render_register
from .security import playbooks, threats


def build(out_dir: str | Path = "docs/generated", status: bool = True) -> list[Path]:
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

    from .governance.controls import render_markdown as render_controls
    from .governance.posture import posture as build_posture
    from .governance.posture import render_markdown as render_posture
    from .governance.studies import render_markdown as render_studies

    p = out / "CONTROLS.md"
    p.write_text(render_controls())
    written.append(p)
    p = out / "STUDIES.md"
    p.write_text(render_studies())
    written.append(p)
    p = out / "POSTURE.md"
    p.write_text(render_posture(build_posture(static=True), "Governance posture (baseline, generated)"))
    written.append(p)

    from .governance.assurance import render_markdown as render_assurance
    from .web.app import router as api_router
    from .web.openapi import build_spec
    from .web.openapi import render_markdown as render_api

    p = out / "ASSURANCE.md"
    p.write_text(render_assurance("."))
    written.append(p)
    from .governance.reviews import render_markdown as render_reviews

    p = out / "REVIEWS.md"
    p.write_text(render_reviews(root="."))
    written.append(p)

    from .governance.traceability import render_markdown as render_traceability

    p = out / "TRACEABILITY.md"
    p.write_text(render_traceability())
    written.append(p)
    if status:  # the status page runs the readiness checks, whose drift check rebuilds everything else: never itself
        from .governance.status import render_markdown as render_status

        p = out / "STATUS.md"
        p.write_text(render_status("."))
        written.append(p)
    p = out / "API.md"
    p.write_text(render_api(build_spec(api_router)))
    written.append(p)

    p = out / "RULES.md"
    lines = ["# Rule ids (generated)", "", "| Rule | Category | Description |", "|---|---|---|"]
    from .domain_rules import SPACE_RULE_CATALOG

    lines += [f"| {rid} | {cat} | {desc} |" for rid, (cat, desc) in {**RULE_CATALOG, **SPACE_RULE_CATALOG}.items()]
    p.write_text("\n".join(lines) + "\n")
    written.append(p)
    return written
