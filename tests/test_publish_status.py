"""Publication readiness checks on this tree and on a deliberately broken one; the generated status page."""

from pathlib import Path

from typer.testing import CliRunner

from aero_audit import cli
from aero_audit.governance import publish, status


def test_publish_checks_on_this_tree_leave_only_the_licence_item_open():
    rows = {r["id"]: r for r in publish.checks(".")}
    assert set(rows) == {f"PUB-{i:02d}" for i in range(1, 12)}
    failing = [k for k, r in rows.items() if not r["ok"]]
    assert failing == ["PUB-10"], {k: rows[k]["detail"] for k in failing}
    s = publish.summary(list(rows.values()))
    assert s["blocking_on_user"] and not s["ready"] and s["passed"] == 10
    md = publish.render_markdown(list(rows.values()))
    assert "Only the upstream licence question remains" in md and "| PUB-02 " in md


def test_secret_and_private_detection_on_a_scratch_repo(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "data/space").mkdir(parents=True)
    (tmp_path / "data/space/cache.json").write_text("{}")
    (tmp_path / "notes.md").write_text("token ghp_" + "A" * 36 + " here\n")  # built at runtime so this source file carries no token-shaped literal
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    files = publish.tracked_files(tmp_path)
    assert "data/space/cache.json" in files and "notes.md" in files
    monkeypatch.chdir(tmp_path)
    rows = {r["id"]: r for r in publish.checks(tmp_path)}
    assert not rows["PUB-01"]["ok"] and "data/space/cache.json" in rows["PUB-01"]["detail"]
    assert not rows["PUB-02"]["ok"] and "notes.md" in rows["PUB-02"]["detail"]
    assert not rows["PUB-03"]["ok"] and not rows["PUB-09"]["ok"]
    assert publish._normalise("built 2026-09-16T08:00:00Z and 2026-09-16 08:00Z") == "built <ts> and <ts>"


def test_status_page_and_publish_command():
    md = status.render_markdown(".")
    assert "# Programme status" in md and "## Publication readiness" in md and "| Domain |" in md
    g = status.gather(".")
    assert g["tests"] > 150 and g["studies"]["runnable"] >= 15 and g["rules"]["space_uas"] >= 30
    r = CliRunner().invoke(cli.app, ["gov", "publish-check"])
    assert r.exit_code == 0 and "PUB-10" in r.output
    r = CliRunner().invoke(cli.app, ["gov", "publish-check", "--strict"])
    assert r.exit_code == 1
    assert Path("docs/generated/STATUS.md").is_file()
