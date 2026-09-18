"""Traceability: every control traced to the standards it serves, the modules that implement it, the
rules that fire, the tests that prove it and the studies that measure it; every rule and module
traced back. NPR 7150.2's bidirectional traceability requirement, applied to this tree.

Gaps are the point: a control with no test, a rule no control claims, a module no control cites,
a study nothing references. `render_markdown()` goes to docs/generated/TRACEABILITY.md through
`aero docs-build`; `gaps()` feeds the assurance checklist and the tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .controls import CONTROLS, SPACE_RULES
from .standards import STANDARDS
from .studies import STUDIES

KINDS = ("rule", "module", "test", "command", "study", "artefact", "doc", "workflow", "scenario")


def matrix() -> list[dict[str, Any]]:
    rows = []
    for c in CONTROLS.values():
        by: dict[str, list[str]] = {k: [] for k in KINDS}
        for e in c.evidence:
            kind, _, ref = e.partition(":")
            by.setdefault(kind, []).append(ref)
        rows.append({"id": c.id, "title": c.title, "pillar": c.pillar, "status": c.status, "domains": list(c.domains), "standards": list(c.standards), **by,
                     "tests_exist": all(Path(t).is_file() for t in by["test"]) if by["test"] else False,
                     "modules_exist": all(Path(m).exists() for m in by["module"]) if by["module"] else False})
    return rows


def reverse() -> dict[str, dict[str, list[str]]]:
    """rule -> controls, module -> controls, study -> controls, standard -> controls."""
    out: dict[str, dict[str, list[str]]] = {"rule": {}, "module": {}, "study": {}, "standard": {}, "test": {}}
    for c in CONTROLS.values():
        for e in c.evidence:
            kind, _, ref = e.partition(":")
            if kind in out:
                out[kind].setdefault(ref, []).append(c.id)
        for s in c.standards:
            out["standard"].setdefault(s, []).append(c.id)
    return out


def _all_rules() -> set[str]:
    from ..audit.rules import RULE_CATALOG

    return set(RULE_CATALOG) | set(SPACE_RULES)


def _modules_in_tree() -> set[str]:
    return {str(p) for p in Path("aero_audit").rglob("*.py") if "__pycache__" not in p.parts and p.name != "__init__.py"}


def gaps() -> dict[str, list[str]]:
    rev = reverse()
    rows = matrix()
    untested = sorted(r["id"] for r in rows if r["status"] != "planned" and not r["test"])
    unimplemented_claim = sorted(r["id"] for r in rows if r["status"] == "implemented" and not r["module"] and not r["workflow"] and not r["command"])
    orphan_rules = sorted(_all_rules() - set(rev["rule"]))
    cited_modules = set(rev["module"])
    domain_pfx = ("aero_audit/audit/", "aero_audit/features/", "aero_audit/ml/", "aero_audit/security/", "aero_audit/risk/", "aero_audit/space/", "aero_audit/uas/", "aero_audit/vision/")
    infra = ("aero_audit/audit/findings.py", "aero_audit/audit/report.py", "aero_audit/audit/html_report.py", "aero_audit/audit/summary.py")  # data model and rendering, not controls
    uncited_modules = sorted(m for m in _modules_in_tree() if m not in cited_modules and m.startswith(domain_pfx) and m not in infra)
    unreferenced_studies = sorted(s.id for s in STUDIES.values() if s.id not in rev["study"])
    unused_standards = sorted(s.id for s in STANDARDS.values() if s.id not in rev["standard"])
    missing_tests = sorted({t for r in rows for t in r["test"] if not Path(t).is_file()})
    return {"controls_without_tests": untested, "implemented_without_module_or_command": unimplemented_claim, "rules_without_control": orphan_rules,
            "modules_without_control": uncited_modules, "studies_without_control": unreferenced_studies, "standards_without_control": unused_standards,
            "test_files_missing": missing_tests}


def coverage() -> dict[str, float]:
    rows = matrix()
    active = [r for r in rows if r["status"] != "planned"]
    rules = _all_rules()
    rev = reverse()
    return {"controls_with_tests": round(sum(1 for r in active if r["test"]) / max(len(active), 1), 3),
            "rules_traced": round(sum(1 for r in rules if r in rev["rule"]) / max(len(rules), 1), 3),
            "studies_traced": round(sum(1 for s in STUDIES if s in rev["study"]) / max(len(STUDIES), 1), 3),
            "standards_traced": round(sum(1 for s in STANDARDS if s in rev["standard"]) / max(len(STANDARDS), 1), 3)}


def render_markdown() -> str:
    rows = matrix()
    g = gaps()
    cov = coverage()
    intro = ("Bidirectional traceability (NPR 7150.2 SWE-052 lineage): controls to standards, modules, rules, tests and studies; and back. "
             "Gaps are listed first because they are the actionable part.")
    lines = ["# Traceability matrix (generated)", "", intro, "", "| Coverage | Share |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {v:.0%} |" for k, v in cov.items()] + ["", "## Gaps", ""]
    for k, v in g.items():
        lines.append(f"- **{k.replace('_', ' ')}**: {', '.join(v) if v else 'none'}")
    lines += ["", "## Controls", "", "| Control | Status | Standards | Rules | Modules | Tests | Studies |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} {r['title']} | {r['status']} | {', '.join(r['standards'])} | {', '.join(r['rule'])} | {', '.join(Path(m).name for m in r['module'])} | "
                     f"{', '.join(Path(t).name for t in r['test'])} | {', '.join(r['study'])} |")
    rev = reverse()
    lines += ["", "## Rules to controls", "", "| Rule | Controls |", "|---|---|"] + [f"| {k} | {', '.join(v)} |" for k, v in sorted(rev["rule"].items())]
    lines += ["", "## Studies to controls", "", "| Study | Controls |", "|---|---|"] + [f"| {k} | {', '.join(v)} |" for k, v in sorted(rev["study"].items())]
    return "\n".join(lines) + "\n"


__all__ = ["KINDS", "coverage", "gaps", "matrix", "render_markdown", "reverse"]
