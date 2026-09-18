"""Renderer, element-history manoeuvre and decay detection, the encounter model, and the traceability matrix."""

import json
from pathlib import Path

import numpy as np
import pytest

from aero_audit.governance import traceability as tr
from aero_audit.space import maneuvers, render
from aero_audit.space.orbital import parse_tle
from aero_audit.uas import encounter_model as em

SAMPLE = Path("data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz")
BOX = ["v -1 -0.3 -0.3", "v 1 -0.3 -0.3", "v 1 0.3 -0.3", "v -1 0.3 -0.3", "v -1 -0.3 0.3", "v 1 -0.3 0.3", "v 1 0.3 0.3", "v -1 0.3 0.3", "v 1.8 0 0",
       "f 1 2 3 4", "f 5 6 7 8", "f 1 2 6 5", "f 2 3 7 6", "f 3 4 8 7", "f 4 1 5 8", "f 2 9 3", "f 3 9 7", "f 7 9 6", "f 6 9 2"]


def _checksum(line: str) -> str:
    s = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
    return line[:68] + str(s % 10)


def _tle(norad: int, ddd: float, n: float, inc: float = 51.64, ndot: str = "+.00010000", bstar: str = " 10000-3") -> str:
    l1 = f"1 {norad:05d}U 98067A   26{ddd:012.8f} {ndot}  00000-0 {bstar} 0  9990"
    l2 = f"2 {norad:05d} {inc:8.4f} 247.4627 0006703 130.5360 325.0288 {n:11.8f}123456"
    return f"OBJ {norad}\n{_checksum(l1)}\n{_checksum(l2)}\n"


def test_obj_loader_fans_polygons_and_rasteriser_shades_a_silhouette(tmp_path):
    p = tmp_path / "box.obj"
    p.write_text("\n".join(BOX) + "\n")
    v, f = render.load_obj(p)
    assert v.shape == (9, 3) and f.shape == (6 * 2 + 4, 3)  # six quads fanned to two triangles each, four nose triangles
    img = render.rasterise(v, f, 64, yaw=30, pitch=20)
    assert img.shape == (64, 64) and img.min() >= 0.05 and img.max() <= 1.0
    covered = (img > 0.06).mean()
    assert 0.05 < covered < 0.6  # an object, not a blank frame and not a fill
    side = render.rasterise(v, f, 64, yaw=90, pitch=0)  # end-on view of a 2:0.6 box is smaller than the broadside view
    assert (side > 0.06).mean() < (render.rasterise(v, f, 64, yaw=0, pitch=0) > 0.06).mean()
    (tmp_path / "empty.obj").write_text("# nothing\n")
    with pytest.raises(ValueError):
        render.load_obj(tmp_path / "empty.obj")


def test_render_views_writes_manifest_and_dataset_items(tmp_path):
    pytest.importorskip("cv2")
    p = tmp_path / "probe.obj"
    p.write_text("\n".join(BOX) + "\n")
    m = render.render_views(p, tmp_path / "renders", label="probe", n_yaw=4, pitches=(0.0, 30.0), size=96)
    assert len(m["views"]) == 8 and all(Path(vw["file"]).is_file() and len(vw["sha256"]) == 64 for vw in m["views"])
    assert json.loads((tmp_path / "renders/probe/renders.manifest.json").read_text())["model_sha256"] == m["model_sha256"]
    items = render.dataset_items(m)
    assert len(items) == 8 and {it["label"] for it in items} == {"probe"} and items[0]["source"] == "nasa3d-render" and items[0]["split"] in ("train", "val")
    assert len({vw["sha256"] for vw in m["views"]}) > 1  # different viewpoints give different images


def test_manoeuvre_and_decay_detection_from_element_history(tmp_path):
    a, b, c = tmp_path / "a.tle", tmp_path / "b.tle", tmp_path / "c.tle"
    a.write_text(_tle(25544, 250.5, 15.49) + _tle(90001, 250.5, 16.30, ndot="+.00500000", bstar=" 50000-2"))
    b.write_text(_tle(25544, 251.5, 15.49) + _tle(90001, 251.5, 16.35, ndot="+.00600000", bstar=" 50000-2"))
    c.write_text(_tle(25544, 252.5, 15.47) + _tle(90001, 252.5, 16.42, ndot="+.00700000", bstar=" 50000-2"))
    assert all(len(parse_tle(f.read_text())) == 2 for f in (a, b, c))
    me = maneuvers.mean_elements(parse_tle(a.read_text())[0])
    assert 6700 < me["a_km"] < 6900 and abs(me["inc_deg"] - 51.64) < 1e-3 and me["bstar"] == pytest.approx(0.1e-3)
    summary, fs = maneuvers.analyse([a, b, c])
    assert summary["objects"] == 2 and summary["with_history"] == 2
    iss = [ch for ch in summary["changes"] if ch["norad"] == 25544]
    assert len(iss) == 1 and iss[0]["da_km"] > 5  # reboost between b and c; the a->b step is unchanged and not flagged
    assert any(d["norad"] == 90001 and d["perigee_km"] < 200 and d["decay_days_estimate"] < 30 for d in summary["decaying"])
    assert {f.rule_id for f in fs} == {"ORB-006", "ORB-007"}
    quiet, fq = maneuvers.analyse([a, b])
    assert [ch["norad"] for ch in quiet["changes"]] == [90001] and all(f.rule_id != "ORB-006" or f.callsign == "OBJ 90001" for f in fq)
    assert maneuvers.decay_days({"ndot_rev_day2": 0.0, "n_rev_day": 15.5}) is None


def test_encounter_model_fit_sample_simulate_is_deterministic():
    from aero_audit.uas.encounters import extract_encounters

    ex = extract_encounters(SAMPLE, max_batches=6)
    model = em.fit(ex)
    assert model["n"] >= 5 and len(model["range_ft"]) == model["n"] and 0.0 <= model["converging_share"] <= 1.0
    encs = em.sample_encounters(model, 50, seed=1)
    assert len(encs) == 50 and all(0 <= e["hmd_ft"] <= e["range_ft"] * 1.0001 for e in encs)
    sim1 = em.simulate(model, 300, seed=3)
    sim2 = em.simulate(model, 300, seed=3)
    assert sim1 == sim2 and sim1["nmac_mitigated"] <= sim1["nmac_unmitigated"] <= sim1["n"]
    assert sim1["rates"] and sim1["rates"]["nmac_per_fh_mitigated"] <= sim1["rates"]["nmac_per_fh_unmitigated"]
    # a head-on encounter with zero miss distance and no vertical offset must reach NMAC; a wide one must not
    hit = em._propagate({"range_ft": 20000.0, "dz_ft": 0.0, "speed_fps": 400.0, "hmd_ft": 0.0, "vz_fps": 0.0, "converging": True})
    miss = em._propagate({"range_ft": 20000.0, "dz_ft": 0.0, "speed_fps": 400.0, "hmd_ft": 6000.0, "vz_fps": 0.0, "converging": True})
    assert hit["nmac"] and hit["t_violation"] is not None and hit["t_violation"] < hit["t_min"] and not miss["nmac"]
    with pytest.raises(ValueError):
        em.fit({"pairs": {}})


def test_traceability_matrix_gaps_and_coverage():
    rows = tr.matrix()
    assert {r["id"] for r in rows} == set(tr.CONTROLS) and all(set(tr.KINDS) <= set(r) for r in rows)
    rev = tr.reverse()
    assert "C-09" in rev["rule"]["ORB-002"] and "C-38" in rev["standard"]["ICAO-A3"]
    g = tr.gaps()
    assert g["test_files_missing"] == [] and g["rules_without_control"] == [] and g["studies_without_control"] == []
    assert g["implemented_without_module_or_command"] == [] and g["standards_without_control"] == []
    cov = tr.coverage()
    assert cov["rules_traced"] == 1.0 and cov["studies_traced"] == 1.0 and cov["controls_with_tests"] >= 0.9
    md = tr.render_markdown()
    assert "## Gaps" in md and "| C-09 " in md and "ORB-006" in md


@pytest.mark.parametrize("study", ["ST-19", "ST-20"])
def test_new_studies_run_offline(tmp_path, study):
    from aero_audit.governance import run_study

    if study == "ST-20":
        a, b = tmp_path / "a.tle", tmp_path / "b.tle"
        a.write_text(_tle(25544, 250.5, 15.49))
        b.write_text(_tle(25544, 252.5, 15.47))
        rec = run_study(study, tmp_path / "studies", files=[a, b])
        assert rec["result"]["changes"] == 1
    else:
        rec = run_study(study, tmp_path / "studies", recording=SAMPLE, n=200, max_batches=4)
        assert rec["result"]["simulation"]["n"] == 200
    assert Path(rec["files"]["md"]).is_file()


def test_rasteriser_normalises_any_scale():
    v = np.array([[0, 0, 0], [1000, 0, 0], [1000, 1000, 0], [0, 1000, 0]], dtype=float)
    f = np.array([[0, 1, 2], [0, 2, 3]])
    img = render.rasterise(v, f, 32, 0, 0)
    assert 0.5 < (img > 0.06).mean() < 0.8  # a square scaled to 0.8 of the frame
