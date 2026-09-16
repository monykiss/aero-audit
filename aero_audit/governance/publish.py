"""Publication readiness: what has to be true before the private branch becomes public (policy P-08).

Every check is mechanical and reads the tree as git sees it, so the answer is the same on any
machine: nothing private is tracked, no secret-looking string is committed, every external source is
attributed, generated docs match the code, the control library and traceability are clean, optional
dependencies are declared, and the changelog has an entry for what would be released. The command
``aero gov publish-check`` prints the table and exits non-zero on any failure; the generated
STATUS.md carries the summary.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PRIVATE_PREFIXES = ("data/space/", "data/recordings/", "reports/", "logs/", "runs/", "data/app/")
PRIVATE_FILES = (".env", "models/scene_yolo_cls.pt", "models/scene_classifier.joblib")
SECRET_PATTERNS = (re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"ghp_[A-Za-z0-9]{30,}"), re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                   re.compile(r"(?i)(?:spacetrack_pass|opensky_client_secret|nasa_api_key)\s*=\s*['\"]?[A-Za-z0-9+/_\-]{8,}"))
REQUIRED_ATTRIBUTION = ("adsb.lol", "NASA", "NOAA", "Space Devs", "CelesTrak")
TEXT_SUFFIXES = (".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".js", ".html", ".css", ".cfg", ".ini", ".sh", ".example")


def tracked_files(root: str | Path = ".") -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln for ln in out.splitlines() if ln]


def checks(root: str | Path = ".") -> list[dict[str, Any]]:
    root = Path(root)
    files = tracked_files(root)
    rows: list[dict[str, Any]] = []

    def row(cid: str, title: str, ok: bool, detail: str) -> None:
        rows.append({"id": cid, "title": title, "ok": bool(ok), "detail": detail})

    private = [f for f in files if f.startswith(PRIVATE_PREFIXES) or f in PRIVATE_FILES]
    private = [f for f in private if not f.endswith(".gitkeep")]
    row("PUB-01", "Nothing private tracked", not private, "clean" if not private else "tracked: " + ", ".join(private[:6]))
    hits = []
    for f in files:
        p = root / f
        if p.suffix.lower() not in TEXT_SUFFIXES or not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        pats = SECRET_PATTERNS[:3] if f.startswith("tests/") else SECRET_PATTERNS  # test fixtures assign placeholder values by design; real key shapes still count
        for pat in pats:
            if pat.search(text) and f != "aero_audit/governance/publish.py":
                hits.append(f"{f} ({pat.pattern[:24]})")
                break
    row("PUB-02", "No secret-looking strings in tracked text", not hits, "clean" if not hits else "; ".join(hits[:5]))
    attr = (root / "data/samples/ATTRIBUTION.md")
    text = attr.read_text() if attr.is_file() else ""
    missing = [s for s in REQUIRED_ATTRIBUTION if s.lower() not in text.lower()]
    row("PUB-03", "Every external source attributed", attr.is_file() and not missing, "all named" if not missing else "missing: " + ", ".join(missing))
    stale = _stale_generated(root)
    row("PUB-04", "Generated docs match the code", not stale, "fresh" if not stale else "stale: " + ", ".join(stale[:6]))
    from .controls import validate
    from .traceability import gaps

    problems = validate()
    row("PUB-05", "Control library referentially clean", not problems, "clean" if not problems else "; ".join(problems[:4]))
    g = gaps()
    hard = {k: v for k, v in g.items() if k in ("rules_without_control", "studies_without_control", "standards_without_control", "test_files_missing", "controls_without_tests") and v}
    row("PUB-06", "Traceability: no orphan rules, studies, standards or untested controls", not hard, "clean" if not hard else "; ".join(f"{k}: {len(v)}" for k, v in hard.items()))
    py = (root / "pyproject.toml").read_text() if (root / "pyproject.toml").is_file() else ""
    lock = (root / "requirements.lock.txt").read_text() if (root / "requirements.lock.txt").is_file() else ""
    deps_ok = "sgp4" in py and "sgp4" in lock and "DracoPy" in py and "ultralytics" in py
    row("PUB-07", "Optional dependencies declared and sgp4 locked", deps_ok, "space extra + lock, vision extra" if deps_ok else "check pyproject extras and requirements.lock.txt")
    ch = (root / "CHANGELOG.md").read_text() if (root / "CHANGELOG.md").is_file() else ""
    row("PUB-08", "Changelog carries an Unreleased section", "## Unreleased" in ch, "present" if "## Unreleased" in ch else "add '## Unreleased' with what this branch adds")
    readme = (root / "README.md").read_text() if (root / "README.md").is_file() else ""
    docs_needed = ("docs/SPACE.md", "docs/UAS.md", "docs/ACCOUNTS.md", "docs/HOLISTIC_PLAN.md")
    miss_docs = [d for d in docs_needed if d not in readme or not (root / d).is_file()]
    row("PUB-09", "README links the branch documentation", not miss_docs, "linked" if not miss_docs else "missing: " + ", ".join(miss_docs))
    row("PUB-10", "Licence question settled with upstream (P-08)", False, "waiting on the NASA-3D-Resources licence confirmation; see docs/UPSTREAM.md")
    return rows


def _stale_generated(root: Path) -> list[str]:
    from ..docs_build import build

    cur = root / "docs/generated"
    if not cur.is_dir():
        return ["docs/generated missing"]
    with tempfile.TemporaryDirectory() as td:
        written = build(td, status=False)
        stale = []
        for p in written:
            old = cur / p.name
            if not old.is_file() or _normalise(old.read_text()) != _normalise(p.read_text()):
                stale.append(p.name)
    return stale


def _normalise(text: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?Z?", "<ts>", text)


def summary(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else checks()
    failed = [r["id"] for r in rows if not r["ok"]]
    return {"total": len(rows), "passed": len(rows) - len(failed), "failed": failed, "ready": not failed, "blocking_on_user": failed == ["PUB-10"]}


def render_markdown(rows: list[dict[str, Any]] | None = None) -> str:
    rows = rows if rows is not None else checks()
    s = summary(rows)
    lines = ["# Publication readiness (generated)", "", f"{s['passed']} of {s['total']} checks pass. " + ("Ready to publish." if s["ready"] else ("Only the upstream licence question remains (P-08)." if s["blocking_on_user"] else "Not ready: " + ", ".join(s["failed"]))), "",
             "| Check | OK | Detail |", "|---|---|---|"]
    lines += [f"| {r['id']} {r['title']} | {'yes' if r['ok'] else 'NO'} | {r['detail']} |" for r in rows]
    return "\n".join(lines) + "\n"


__all__ = ["PRIVATE_FILES", "PRIVATE_PREFIXES", "REQUIRED_ATTRIBUTION", "SECRET_PATTERNS", "checks", "render_markdown", "summary", "tracked_files"]
