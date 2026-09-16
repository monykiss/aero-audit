"""One-page programme status generated from code: domains, rules, controls, studies, traceability, tests, readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def gather(root: str | Path = ".") -> dict[str, Any]:
    import re

    from ..audit.rules import RULE_CATALOG
    from ..domain_rules import SPACE_RULE_CATALOG
    from .controls import CONTROLS
    from .domains import DOMAINS
    from .posture import posture
    from .publish import checks, summary
    from .studies import STUDIES
    from .traceability import coverage

    tests = 0
    for p in Path(root, "tests").glob("test_*.py"):
        tests += len(re.findall(r"^def test_", p.read_text(), re.MULTILINE))
    by_status = {s: sum(1 for c in CONTROLS.values() if c.status == s) for s in ("implemented", "partial", "planned")}
    pub = checks(root)
    return {"domains": [{"key": d.key, "name": d.name, "status": d.status, "rules": len(d.rule_prefixes), "modules": len(d.modules)} for d in DOMAINS.values()],
            "rules": {"air": len(RULE_CATALOG), "space_uas": len(SPACE_RULE_CATALOG)}, "controls": by_status,
            "studies": {"total": len(STUDIES), "runnable": sum(1 for s in STUDIES.values() if s.status == "runnable")},
            "tests": tests, "traceability": coverage(), "posture": posture(None, static=True), "publish": summary(pub), "publish_rows": pub}


def render_markdown(root: str | Path = ".") -> str:
    g = gather(root)
    p = g["posture"]
    headline = (f"Governance index **{p['governance_index']:.0%}** (controls {p['components']['controls_implementation']:.0%}, standards {p['components']['standards_coverage']:.0%}, "
                f"risk share {p['components']['risk_share_low_or_medium']:.0%}); {g['rules']['air']} air rules and {g['rules']['space_uas']} space/UAS rules; "
                f"{g['controls']['implemented']} controls implemented, {g['controls']['partial']} partial, {g['controls']['planned']} planned; "
                f"{g['studies']['runnable']} of {g['studies']['total']} studies runnable; {g['tests']} tests.")
    lines = ["# Programme status (generated)", "", headline, "", "## Domains", "", "| Domain | Status | Rule families | Modules |", "|---|---|---|---|"]
    lines += [f"| {d['name']} | {d['status']} | {d['rules']} | {d['modules']} |" for d in g["domains"]]
    lines += ["", "## Traceability", "", "| Axis | Share |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {v:.0%} |" for k, v in g["traceability"].items()]
    s = g["publish"]
    lines += ["", "## Publication readiness", "", f"{s['passed']} of {s['total']} checks pass; " + ("ready." if s["ready"] else ("only the upstream licence question (P-08) remains." if s["blocking_on_user"] else "failing: " + ", ".join(s["failed"]))), ""]
    lines += [f"- {r['id']} {r['title']}: {'ok' if r['ok'] else 'NO'} ({r['detail']})" for r in g["publish_rows"]]
    return "\n".join(lines) + "\n"


__all__ = ["gather", "render_markdown"]
