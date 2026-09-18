"""Assurance classification and SLIM checklist against this tree; the data catalogue with search and reconciliation."""

import json
import time
from pathlib import Path

from aero_audit.governance import assurance, catalog
from aero_audit.synthetic import generate


def test_assurance_classification_and_slim_checklist_on_this_repo():
    rows = assurance.classification()
    assert {r["class"] for r in rows} <= {"A", "B", "C", "D", "E"} and all(r["activities"] for r in rows)
    assert any(r["safety_related"] for r in rows) and any(not r["safety_related"] for r in rows)
    slim = assurance.slim_checklist(".")
    assert slim["total"] == len(assurance.SLIM_CHECKS) and slim["passed"] >= slim["total"] - 1  # everything the checklist asks for exists here
    md = assurance.render_markdown(".")
    assert "NPR 7150.2" in md and "SLIM-15" in md and "355.0-B" in md
    missing = [r["id"] for r in slim["rows"] if not r["ok"]]
    assert missing == [] or missing == ["SLIM-17"]  # signing is on the release workflow only after v0.6.0


def test_catalog_build_search_and_reconcile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/recordings").mkdir(parents=True)
    rec = generate(tmp_path / "data/recordings/synthetic_c.jsonl", n_aircraft=10, polls=5, seed=2)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/a_x.json").write_text("{}")
    (tmp_path / "reports/a_x.manifest.json").write_text("{}")
    (tmp_path / "data/space/elements").mkdir(parents=True)
    (tmp_path / "data/space/elements/celestrak_stations_x.tle").write_text("ISS\n1 25544U ...\n2 25544 ...\n")
    (tmp_path / "data/space/elements/celestrak_stations_x.tle.provenance.json").write_text('{"source": "x"}')
    cat = catalog.build_catalog(tmp_path)
    assert cat["collections"]["recordings"]["count"] == 1 and cat["collections"]["reports"]["count"] == 2 and cat["granules_total"] >= 4
    g = cat["collections"]["recordings"]["granules"][0]
    assert g["time_start"] <= g["time_end"] and g["region"] and len(g["sha256"]) == 64
    el = cat["collections"]["elements"]["granules"][0]
    assert el["provenance"].endswith(".provenance.json")
    assert any(x.get("kind") == "manifest" for x in cat["collections"]["reports"]["granules"])
    p = catalog.save_catalog(cat, tmp_path / "data/app/catalog.json")
    assert catalog.load_catalog(p)["granules_total"] == cat["granules_total"]
    assert [x["id"] for x in catalog.search(cat, q="synthetic_c")] == ["data/recordings/synthetic_c.jsonl"]
    assert catalog.search(cat, collection="elements")[0]["collection"] == "elements"
    assert catalog.search(cat, since_ts=time.time() + 3600) == []
    Path(rec).write_text(Path(rec).read_text() + "\n")
    (tmp_path / "reports/b.md").write_text("# b")
    (tmp_path / "reports/a_x.json").unlink()
    new = catalog.build_catalog(tmp_path)
    r = catalog.reconcile(cat, new)
    assert r["drift"] and "reports/b.md" in r["added"] and "reports/a_x.json" in r["removed"] and "data/recordings/synthetic_c.jsonl" in r["changed"]
    assert json.dumps(r) and not catalog.reconcile(new, new)["drift"]
