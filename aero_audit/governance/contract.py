"""The 1.0 contract: the surfaces a user can depend on, snapshotted and compared.

`current()` enumerates what the tree exposes today: CLI command paths, rule ids (air, space and UAS),
API routes, job names, study and control ids, playbook ids, documented environment variables and
the keys of the generic report envelope. `contracts/contract-1.0.json` is the snapshot taken at 1.0;
`diff()` lists what a change would remove (a breaking change under the stability policy in
docs/STABILITY.md) and what it adds (fine). `aero gov contract --check` and PUB-13 fail on any
removal, so a renamed command or a dropped rule id cannot ship by accident.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("contracts/contract-1.0.json")
SURFACES = ("cli", "rules", "api", "jobs", "studies", "controls", "playbooks", "env", "report_envelope")
ENV_VARS = ("AERO_EVALUATION_PATH", "AERO_HTTP_BACKEND", "AERO_LOG_FILE", "AERO_LOG_STDERR", "AERO_OFFLINE", "AERO_POLL_INTERVAL", "AERO_POST_RATE_LIMIT", "AERO_PROVIDER",
            "AERO_REGION", "AERO_SCHEDULE", "AERO_SETUP_ALLOW_PIPE", "AERO_TUNING", "AERO_SDLS_KEY_<spi>", "GITHUB_TOKEN", "NASA_API_KEY", "OPENSKY_CLIENT_ID",
            "OPENSKY_CLIENT_SECRET", "SPACETRACK_PASS", "SPACETRACK_USER")


def _cli_commands() -> list[str]:
    from ..cli import app

    def walk(a: Any, prefix: tuple[str, ...] = ()) -> list[str]:
        out = []
        for cmd in a.registered_commands:
            out.append(" ".join((*prefix, cmd.name or cmd.callback.__name__.replace("_", "-"))))
        for grp in a.registered_groups:
            out += walk(grp.typer_instance, (*prefix, grp.name))
        return out

    return sorted(walk(app))


def _api_routes() -> list[str]:
    from ..web.app import router
    from ..web.openapi import build_spec

    spec = build_spec(router)
    return sorted(f"{m.upper()} {p}" for p, ops in spec.get("paths", {}).items() for m in ops)


def _report_envelope() -> list[str]:
    from ..audit.generic_report import write_generic

    with tempfile.TemporaryDirectory() as td:
        p = write_generic(td, "contract", "summary", {"ok": True}, [])["json"]
        return sorted(json.loads(Path(p).read_text()).keys())


def current() -> dict[str, list[str]]:
    from ..audit.rules import RULE_CATALOG
    from ..domain_rules import SPACE_PLAYBOOKS, SPACE_RULE_CATALOG
    from ..security.playbooks import PLAYBOOKS
    from ..web.space_jobs import REGISTRY
    from .controls import CONTROLS
    from .studies import STUDIES

    return {"cli": _cli_commands(), "rules": sorted({*RULE_CATALOG, *SPACE_RULE_CATALOG}), "api": _api_routes(), "jobs": sorted(REGISTRY), "studies": sorted(STUDIES),
            "controls": sorted(CONTROLS), "playbooks": sorted({*PLAYBOOKS, *SPACE_PLAYBOOKS}), "env": sorted(ENV_VARS), "report_envelope": _report_envelope()}


def load(path: str | Path = CONTRACT_PATH) -> dict[str, Any] | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.is_file() else None


def write(path: str | Path = CONTRACT_PATH, version: str | None = None) -> Path:
    from .. import __version__

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": version or __version__, "surfaces": current()}, indent=1, sort_keys=True) + "\n")
    return p


def diff(snapshot: dict[str, Any] | None, now: dict[str, list[str]] | None = None) -> dict[str, Any]:
    now = now if now is not None else current()
    if not snapshot:
        return {"snapshot": None, "removed": {s: [] for s in SURFACES}, "added": {s: now.get(s, []) for s in SURFACES}, "breaking": False}
    old = snapshot.get("surfaces", {})
    removed = {s: sorted(set(old.get(s, [])) - set(now.get(s, []))) for s in SURFACES}
    added = {s: sorted(set(now.get(s, [])) - set(old.get(s, []))) for s in SURFACES}
    return {"snapshot": snapshot.get("version"), "removed": removed, "added": added, "breaking": any(removed.values())}


def render_markdown(d: dict[str, Any] | None = None) -> str:
    d = d if d is not None else diff(load())
    lines = [f"# Contract check against {d['snapshot'] or 'no snapshot'}", "", "**breaking**" if d["breaking"] else "no removals", ""]
    for s in SURFACES:
        if d["removed"][s] or d["added"][s]:
            lines.append(f"- {s}: removed {d['removed'][s] or 'none'}; added {len(d['added'][s])}")
    return "\n".join(lines) + "\n"


__all__ = ["CONTRACT_PATH", "ENV_VARS", "SURFACES", "current", "diff", "load", "render_markdown", "write"]
