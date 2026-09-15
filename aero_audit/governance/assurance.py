"""Software assurance posture: NPR 7150.2 classification of every component, the assurance
activities that class implies, a NASA-AMMOS SLIM-style repository checklist evaluated against the
tree, and the space-data-link security expectations any spacecraft telemetry ingest must meet.

Classification rationale (NPR 7150.2 Appendix D, paraphrased): Class A human-rated space
software; B non-human space-rated or large-scale aeronautics; C mission support, safety-related
ground software; D basic science and engineering analysis, research tools; E design concept and
exploratory code. aero-audit is an analysis and audit tool: nothing here commands a vehicle, so
the highest class is D, with the app and audit chain called out as C-like in rigour because
people act on what they show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Component:
    name: str
    path: str
    nasa_class: str  # A..E
    safety_related: bool
    rationale: str


COMPONENTS: tuple[Component, ...] = (
    Component("Rules engine and scoring", "aero_audit/audit", "D", True, "Analysis producing safety and security findings people act on; no vehicle interaction."),
    Component("Feed ingest and recording", "aero_audit/ingest, aero_audit/stream", "D", False, "Data acquisition from public feeds; replayable evidence."),
    Component("Anomaly model and evaluation", "aero_audit/ml", "D", True, "Model whose output ranks findings; gated by registry checksum and evaluation."),
    Component("Local app and API", "aero_audit/web", "D", True, "Operator-facing; hardened guard, hash-chained audit log, provenance on reports."),
    Component("Space assets and footage", "aero_audit/space (nasa3d, nasa_images, footage, dataset, classifier)", "E", False, "Exploratory intake and scene classification; no operational decisions."),
    Component("Launch telemetry and orbital analysis", "aero_audit/space (telemetry, orbital, cdm, cdm_inbox, debris)", "D", True, "Physics checks and conjunction assessment on supplied data; advisory to operators."),
    Component("UAS well-clear metrics", "aero_audit/uas", "D", True, "Offline DO-365 metrics on recordings; never real-time guidance."),
    Component("Governance layer", "aero_audit/governance", "E", False, "Registry of controls, risks, studies and posture; documentation-grade."),
)

ACTIVITIES_BY_CLASS: dict[str, tuple[str, ...]] = {
    "A": ("all of B plus IV&V", "formal inspections of requirements/design/code", "software safety analysis with hazard tracking"),
    "B": ("all of C plus independent test", "bidirectional requirements traceability", "software safety analysis"),
    "C": ("all of D plus peer reviews of code and tests", "configuration management with baselines", "defect tracking with root cause", "assurance plan"),
    "D": ("version control", "documented requirements and design", "unit and regression tests run in CI", "release records with provenance", "coding standard checks"),
    "E": ("version control", "a README stating purpose and limits"),
}

# (id, title, how it is checked)
SLIM_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("SLIM-01", "README with purpose, quick start and licence", "file:README.md"),
    ("SLIM-02", "OSI licence file", "file:LICENSE"),
    ("SLIM-03", "Contributing guide", "file:CONTRIBUTING.md"),
    ("SLIM-04", "Code of conduct", "file:CODE_OF_CONDUCT.md"),
    ("SLIM-05", "Security policy and reporting path", "file:SECURITY.md"),
    ("SLIM-06", "Changelog", "file:CHANGELOG.md"),
    ("SLIM-07", "Code owners", "file:.github/CODEOWNERS"),
    ("SLIM-08", "Issue templates", "glob:.github/ISSUE_TEMPLATE/*.md"),
    ("SLIM-09", "Pull request template", "file:.github/PULL_REQUEST_TEMPLATE.md"),
    ("SLIM-10", "Continuous integration with tests", "regex:.github/workflows/ci.yml:pytest"),
    ("SLIM-11", "Static analysis (CodeQL)", "file:.github/workflows/codeql.yml"),
    ("SLIM-12", "Dependency updates (Dependabot)", "file:.github/dependabot.yml"),
    ("SLIM-13", "Secret scanning in CI", "regex:.github/workflows/ci.yml:gitleaks"),
    ("SLIM-14", "Pinned dependencies with hashes", "regex:requirements.lock.txt:--hash=sha256"),
    ("SLIM-15", "GitHub Actions pinned to commit SHAs", "regex:.github/workflows/ci.yml:uses: [^@\\n]+@[0-9a-f]{40}"),
    ("SLIM-16", "SBOM produced at release", "regex:.github/workflows/release.yml:cyclonedx"),
    ("SLIM-17", "Release artifacts signed", "regex:.github/workflows/release.yml:sigstore"),
    ("SLIM-18", "Pre-commit hooks", "file:.pre-commit-config.yaml"),
    ("SLIM-19", "Container image definition", "file:Dockerfile"),
    ("SLIM-20", "Generated documentation kept in sync by CI", "regex:.github/workflows/ci.yml:docs-build"),
    ("SLIM-21", "API contract published", "file:aero_audit/web/openapi.py"),
    ("SLIM-22", "Observability endpoints", "file:aero_audit/observability.py"),
    ("SLIM-23", "Test suite present", "glob:tests/test_*.py"),
    ("SLIM-24", "Supply-chain scorecard workflow", "file:.github/workflows/scorecard.yml"),
)

SDLS_EXPECTATIONS: tuple[str, ...] = (
    "Spacecraft telemetry accepted for analysis should arrive over links protected with CCSDS Space Data Link Security (355.0-B): authenticated frames, replay protection via sequence numbers, key rotation per mission policy.",
    "Where a link is unauthenticated (ground-station relays, hobbyist decoders), treat the stream like ADS-B: physics plausibility (SPC rules), continuity, and corroboration before any operational conclusion.",
    "Record the security association identifier and authentication status alongside each ingested packet so findings can state which data was authenticated.",
    "Never store link keys in this repository or its data directories; SDLS key management stays with the mission's ground segment (reference implementation: nasa/CryptoLib).",
)


def slim_checklist(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root)
    rows = []
    for cid, title, how in SLIM_CHECKS:
        kind, _, spec = how.partition(":")
        ok = False
        if kind == "file":
            ok = (root / spec).is_file()
        elif kind == "glob":
            ok = any(root.glob(spec))
        elif kind == "regex":
            fpath, _, rx = spec.partition(":")
            try:
                ok = re.search(rx, (root / fpath).read_text()) is not None
            except OSError:
                ok = False
        rows.append({"id": cid, "title": title, "ok": ok, "how": how})
    passed = sum(1 for r in rows if r["ok"])
    return {"passed": passed, "total": len(rows), "score": round(passed / len(rows), 3), "rows": rows}


def classification() -> list[dict[str, Any]]:
    return [{"component": c.name, "path": c.path, "class": c.nasa_class, "safety_related": c.safety_related, "rationale": c.rationale,
             "activities": list(ACTIVITIES_BY_CLASS[c.nasa_class])} for c in COMPONENTS]


def render_markdown(root: str | Path = ".") -> str:
    slim = slim_checklist(root)
    lines = ["# Software assurance (generated)", "", "## NPR 7150.2 classification", "",
             "| Component | Paths | Class | Safety-related | Rationale | Required activities |", "|---|---|---|---|---|---|"]
    for r in classification():
        lines.append(f"| {r['component']} | `{r['path']}` | {r['class']} | {'yes' if r['safety_related'] else 'no'} | {r['rationale']} | {'; '.join(r['activities'])} |")
    lines += ["", f"## SLIM repository checklist: {slim['passed']} / {slim['total']} ({slim['score']:.0%})", "", "| Id | Check | Status |", "|---|---|---|"]
    lines += [f"| {r['id']} | {r['title']} | {'pass' if r['ok'] else 'MISSING'} |" for r in slim["rows"]]
    lines += ["", "## Space data link security expectations (CCSDS 355.0-B)", ""] + [f"- {s}" for s in SDLS_EXPECTATIONS] + [""]
    return "\n".join(lines)


__all__ = ["ACTIVITIES_BY_CLASS", "COMPONENTS", "SDLS_EXPECTATIONS", "SLIM_CHECKS", "Component", "classification", "render_markdown", "slim_checklist"]
