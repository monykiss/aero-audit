"""Software assurance reviews, practised: a dated review record per component (NPR 7150.2 class C
style peer review, or a self-review when there is one maintainer), the automatic checks the tree
can prove for that component, and a cadence that says when the next one is due.

The classification in `assurance.py` says what each component *should* get; this module records what
it *got*. Entries live in `docs/assurance/review_log.json` (kind ``self-review`` or ``peer-review``,
so a single-maintainer project never dresses a self-review up as a peer review), and
`aero gov reviews` renders `docs/generated/REVIEWS.md` and exits non-zero when a safety-related
component is overdue. Automatic checks are evidence, not the review: tests that import the
component, lint and static analysis in CI, fuzzing of the parsers, the traceability matrix and a
documentation page. The reviewer still reads the code.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .assurance import COMPONENTS, Component

REVIEW_LOG = Path("docs/assurance/review_log.json")
CADENCE_DAYS = {"A": 30, "B": 60, "C": 90, "D": 90, "E": 180}
SAFETY_CADENCE_DAYS = 90
KINDS = ("self-review", "peer-review")
OUTCOMES = ("accepted", "accepted-with-actions", "rejected")


def load_log(path: str | Path = REVIEW_LOG) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    rows = json.loads(p.read_text())
    if not isinstance(rows, list):
        raise TypeError("review log must be a JSON list")
    for r in rows:
        if r.get("kind") not in KINDS or r.get("outcome") not in OUTCOMES:
            raise ValueError(f"review entry {r.get('component')!r} on {r.get('date')!r}: kind must be one of {KINDS} and outcome one of {OUTCOMES}")
        date.fromisoformat(r["date"])
    return rows


def _module_patterns(comp: Component) -> list[re.Pattern[str]]:
    """Regexes that match an import of the component in a test file: `aero_audit.space.telemetry`,
    `from aero_audit.space import ..., telemetry`, or the bare package when no modules are listed."""
    pats: list[re.Pattern[str]] = []
    for part in comp.path.split(","):
        part = part.strip()
        m = re.match(r"([\w/]+)(?:\s*\(([^)]*)\))?", part)
        if not m:
            continue
        pkg = m.group(1).strip("/").replace("/", r"\.")
        mods = [x.strip() for x in (m.group(2) or "").split(",") if x.strip()]
        if mods:
            for mod in mods:
                pats.append(re.compile(rf"{pkg}\.{mod}\b|from {pkg} import [^\n]*\b{mod}\b"))
        else:
            parent, _, leaf = pkg.rpartition(r"\.")
            pats.append(re.compile(rf"{pkg}\b|from {parent} import [^\n]*\b{leaf}\b" if parent else rf"{pkg}\b"))
    return pats


def automatic_checks(comp: Component, root: str | Path = ".") -> list[dict[str, Any]]:
    root = Path(root)
    tests_text = "\n".join(p.read_text(errors="replace") for p in sorted((root / "tests").glob("test_*.py"))) if (root / "tests").is_dir() else ""
    pats = _module_patterns(comp)
    hit = [p.pattern for p in pats if p.search(tests_text)]
    docs_text = "\n".join(p.read_text(errors="replace") for p in sorted((root / "docs").glob("*.md"))) if (root / "docs").is_dir() else ""
    first_pkg = comp.path.split(",")[0].split(" ")[0].strip()
    from .traceability import gaps

    g = gaps()
    untraced = [m for m in g.get("modules_without_control", []) if m.startswith(first_pkg)]
    pyproject = (root / "pyproject.toml").read_text(errors="replace") if (root / "pyproject.toml").is_file() else ""
    rows = [
        {"check": "tests import the component", "ok": len(hit) == len(pats) and bool(pats), "detail": f"{len(hit)}/{len(pats)} module patterns found in tests/"},
        {"check": "lint configured (ruff)", "ok": "[tool.ruff]" in pyproject, "detail": "pyproject.toml [tool.ruff]"},
        {"check": "static analysis in CI (CodeQL)", "ok": (root / ".github/workflows/codeql.yml").is_file(), "detail": ".github/workflows/codeql.yml"},
        {"check": "parsers fuzzed", "ok": (root / "fuzz/fuzz_targets.py").is_file(), "detail": "fuzz/fuzz_targets.py (CI job)"},
        {"check": "modules traced to a control", "ok": not untraced, "detail": "no gaps" if not untraced else ", ".join(untraced[:4])},
        {"check": "documented", "ok": first_pkg in docs_text or first_pkg.replace("aero_audit/", "") in docs_text, "detail": f"docs/*.md mention {first_pkg}"},
    ]
    return rows


def status(now: datetime | None = None, root: str | Path = ".", log_path: str | Path = REVIEW_LOG) -> list[dict[str, Any]]:
    today = (now or datetime.now(UTC)).date()
    log = load_log(log_path)
    out = []
    for comp in COMPONENTS:
        mine = sorted((r for r in log if r.get("component") == comp.name), key=lambda r: r["date"])
        last = mine[-1] if mine else None
        cadence = min(CADENCE_DAYS.get(comp.nasa_class, 180), SAFETY_CADENCE_DAYS) if comp.safety_related else CADENCE_DAYS.get(comp.nasa_class, 180)
        days = (today - date.fromisoformat(last["date"])).days if last else None
        checks = automatic_checks(comp, root)
        out.append({"component": comp.name, "path": comp.path, "nasa_class": comp.nasa_class, "safety_related": comp.safety_related, "cadence_days": cadence,
                    "reviews": len(mine), "last_date": last["date"] if last else None, "last_kind": last["kind"] if last else None, "last_reviewer": last.get("reviewer") if last else None,
                    "last_outcome": last["outcome"] if last else None, "open_actions": list(last.get("actions") or []) if last and last["outcome"] == "accepted-with-actions" else [],
                    "days_since": days, "due": last is None or days > cadence, "checks_passed": sum(1 for c in checks if c["ok"]), "checks_total": len(checks), "checks": checks})
    return out


def summary(rows: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
    rows = rows if rows is not None else status(**kw)
    overdue = [r["component"] for r in rows if r["due"]]
    return {"components": len(rows), "reviewed": sum(1 for r in rows if r["reviews"]), "overdue": overdue, "overdue_safety_related": [r["component"] for r in rows if r["due"] and r["safety_related"]],
            "self_reviews": sum(1 for r in rows if r["last_kind"] == "self-review"), "peer_reviews": sum(1 for r in rows if r["last_kind"] == "peer-review"),
            "open_actions": sum(len(r["open_actions"]) for r in rows), "checks_passed": sum(r["checks_passed"] for r in rows), "checks_total": sum(r["checks_total"] for r in rows)}


def render_markdown(now: datetime | None = None, root: str | Path = ".") -> str:
    """Deterministic for a given tree: dates and cadences, never 'days since' (the generated page must not drift daily)."""
    from datetime import timedelta

    rows = status(now, root)
    s = summary(rows)
    lines = ["# Assurance reviews (generated)", "",
             (f"{s['reviewed']} of {s['components']} components reviewed ({s['peer_reviews']} peer, {s['self_reviews']} self); "
              f"open actions: {s['open_actions']}; automatic checks {s['checks_passed']}/{s['checks_total']}. `aero gov reviews` says what is overdue today."), "",
             ("A self-review is recorded as such; it satisfies the cadence, not the independence NPR 7150.2 asks of a class C peer review. "
              "The automatic checks are evidence the tree proves; the reviewer still reads the code."), "",
             "| Component | Class | Safety | Last review | Kind | Outcome | Cadence (days) | Next due | Checks |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        nxt = (date.fromisoformat(r["last_date"]) + timedelta(days=r["cadence_days"])).isoformat() if r["last_date"] else "now"
        lines.append(f"| {r['component']} | {r['nasa_class']} | {'yes' if r['safety_related'] else 'no'} | {r['last_date'] or '-'} | {r['last_kind'] or '-'} | {r['last_outcome'] or '-'} | "
                     f"{r['cadence_days']} | {nxt} | {r['checks_passed']}/{r['checks_total']} |")
    lines += ["", "## Open actions", ""]
    acts = [(r["component"], a) for r in rows for a in r["open_actions"]]
    lines += [f"- **{c}**: {a}" for c, a in acts] or ["none"]
    lines += ["", "## Automatic checks per component", ""]
    for r in rows:
        lines.append(f"- **{r['component']}**: " + "; ".join(f"{'✓' if c['ok'] else '✗'} {c['check']} ({c['detail']})" for c in r["checks"]))
    return "\n".join(lines) + "\n"


def render_packet(component_name: str, root: str | Path = ".") -> str:
    """A review packet for a second reviewer: what the component is, what the tree proves, what to read, what to answer,
    and the log entry to paste back. Turning self-reviews into peer reviews needs a person; this makes the ask concrete."""
    comp = next((c for c in COMPONENTS if c.name == component_name), None)
    if comp is None:
        raise KeyError(f"unknown component {component_name!r}; known: {', '.join(c.name for c in COMPONENTS)}")
    rows = [r for r in status(root=root) if r["component"] == comp.name]
    r = rows[0]
    root = Path(root)
    files: list[str] = []
    for part in comp.path.split(","):
        base = part.strip().split(" ")[0].strip("/")
        p = root / base
        files += sorted(str(x.relative_to(root)) for x in (p.rglob("*.py") if p.is_dir() else [p.with_suffix(".py")] if p.with_suffix(".py").is_file() else []))
    tests = sorted(str(t.relative_to(root)) for t in (root / "tests").glob("test_*.py") if any(pat.search(t.read_text(errors="replace")) for pat in _module_patterns(comp)))
    lines = [f"# Review packet: {comp.name}", "", f"NPR 7150.2 class {comp.nasa_class}, safety-related: {'yes' if comp.safety_related else 'no'}. {comp.rationale}", "",
             f"Last review: {r['last_date'] or 'none'} ({r['last_kind'] or '-'}, {r['last_outcome'] or '-'}); cadence {r['cadence_days']} days.", "",
             "## What the tree proves", ""] + [f"- {'✓' if c['ok'] else '✗'} {c['check']} ({c['detail']})" for c in r["checks"]] + [
             "", "## Files to read", ""] + [f"- `{f}`" for f in files[:60]] + ["", "## Tests that exercise it", ""] + [f"- `{t}`" for t in tests] + [
             "", "## Questions for the reviewer", "",
             "1. Do the module docstrings state what each analysis can and cannot claim, and do the findings' recommendations match?",
             "2. Are inputs from outside the tree (feeds, files, request bodies) validated or confined before use?",
             "3. Are failure paths explicit (no silent except, degraded states reported), and does a test cover each?",
             "4. Do thresholds and defaults appear in the report so a reader can judge a finding without the code?",
             "5. Is anything here a safety or security decision the toolkit should not be making on its own?", "",
             "## Log entry to paste into docs/assurance/review_log.json", "",
             "```json", json.dumps({"component": comp.name, "date": "YYYY-MM-DD", "kind": "peer-review", "reviewer": "name (affiliation)", "scope": "files above at commit <sha>",
                                    "outcome": "accepted | accepted-with-actions | rejected", "actions": [], "evidence": ["notes or issue links"]}, indent=1), "```", ""]
    return "\n".join(lines)


__all__ = ["CADENCE_DAYS", "KINDS", "OUTCOMES", "REVIEW_LOG", "automatic_checks", "load_log", "render_markdown", "render_packet", "status", "summary"]
