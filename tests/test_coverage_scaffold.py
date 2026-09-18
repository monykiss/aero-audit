"""Coverage scaffolding: every CLI command answers --help; every space/UAS rule id emitted in code is catalogued and
every catalogued id is emitted; high-severity rules with a playbook are reachable through the Help page; job file
parameters are confined to the data roots."""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aero_audit import cli
from aero_audit.domain_rules import SPACE_PLAYBOOKS, SPACE_RULE_CATALOG
from aero_audit.security.playbooks import playbook_for, render_markdown

runner = CliRunner()


def _commands(app, prefix=()):
    """Every leaf command path of a typer app (groups recursed)."""
    out = []
    for cmd in app.registered_commands:
        out.append((*prefix, cmd.name or cmd.callback.__name__.replace("_", "-")))
    for grp in app.registered_groups:
        out += _commands(grp.typer_instance, (*prefix, grp.name))
    return out


COMMANDS = _commands(cli.app)


def test_cli_has_every_expected_group():
    groups = {c[0] for c in COMMANDS if len(c) > 1}
    assert {"space", "uas", "gov", "data", "obs", "log", "security", "risk", "vision", "config"} <= groups
    assert len(COMMANDS) >= 60


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: " ".join(p))
def test_every_command_answers_help(path):
    r = runner.invoke(cli.app, [*path, "--help"])
    assert r.exit_code == 0, r.output
    assert "Usage" in r.output or "usage" in r.output.lower()


def _emitted_rule_ids() -> set[str]:
    ids = set()
    for p in list(Path("aero_audit/space").glob("*.py")) + list(Path("aero_audit/uas").glob("*.py")):
        ids |= set(re.findall(r'"((?:SPC|ORB|DEB|DAA|SWX|LCH)-\d{3})"', p.read_text()))  # literals, whether passed directly or through a variable
    return ids


def test_space_rule_catalogue_matches_the_code_in_both_directions():
    emitted = _emitted_rule_ids()
    catalogued = set(SPACE_RULE_CATALOG)
    assert emitted - catalogued == set(), f"emitted but not catalogued: {sorted(emitted - catalogued)}"
    assert catalogued - emitted == set(), f"catalogued but never emitted: {sorted(catalogued - emitted)}"
    assert {cat for cat, _ in SPACE_RULE_CATALOG.values()} <= {"security", "safety", "operations", "data-quality", "ml"}
    assert set(SPACE_PLAYBOOKS) <= catalogued and all(pb.rule_id == rid for rid, pb in SPACE_PLAYBOOKS.items())
    assert playbook_for("ORB-004") is not None and playbook_for("SEC-010") is not None and playbook_for("NOPE-000") is None
    md = render_markdown()
    assert "ORB-004" in md and "LCH-001" in md


def test_rules_route_and_generated_docs_include_space_rules(tmp_path, monkeypatch):
    from aero_audit.web.app import App, r_rules

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AERO_SCHEDULE", "")
    app = App()
    try:
        rows = {r["rule"]: r for r in r_rules(app, {"query": {}})}
        assert rows["ORB-004"]["playbook"] and rows["DAA-002"]["category"] == "safety" and rows["SEC-010"]["playbook"]
    finally:
        app.scheduler.stop()
        app.sources.stop()


def test_job_file_parameters_are_confined(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job

    outside = tmp_path / "secret.json"
    outside.write_text("{}")
    (tmp_path / "data/samples").mkdir(parents=True)
    with pytest.raises(PermissionError):
        space_jobs.space_weather(Job("j", "space_weather", {}), {"file": str(outside)})
    with pytest.raises(PermissionError):
        space_jobs.launches(Job("j", "launches", {}), {"file": "../secret.json"})
    with pytest.raises(PermissionError):
        space_jobs.maneuvers(Job("j", "maneuvers", {}), {"files": ["/etc/hosts"]})
    with pytest.raises(PermissionError):
        space_jobs.conjunctions(Job("j", "conjunctions", {}), {"tle": str(outside)})
    with pytest.raises(PermissionError):
        space_jobs.cdm_inbox(Job("j", "cdm_inbox", {}), {"ledger": str(tmp_path / "elsewhere.jsonl")})
    with pytest.raises(FileNotFoundError):
        space_jobs.space_weather(Job("j", "space_weather", {}), {"file": "data/samples/missing.json"})
