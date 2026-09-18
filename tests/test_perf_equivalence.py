"""The vectorised hot paths must agree with their scalar references: well-clear projection, rasteriser, conjunction screen;
the catalogue hash cache must be invisible to results; page summaries are memoised briefly."""

from datetime import UTC, datetime

import numpy as np
import pytest

from aero_audit.bench_space import sphere_mesh, synthetic_elements
from aero_audit.governance import catalog
from aero_audit.space import render
from aero_audit.space.orbital import _screen_reference, screen
from aero_audit.uas import wellclear as wc


def test_projection_matches_scalar_reference_on_random_geometries():
    rng = np.random.default_rng(0)
    checked = 0
    for _ in range(1500):
        s = (float(rng.uniform(-60000, 60000)), float(rng.uniform(-60000, 60000)))
        v = (float(rng.uniform(-700, 700)), float(rng.uniform(-700, 700)))
        dz = float(rng.uniform(-3000, 3000))
        vz = float(rng.choice([0.0, rng.uniform(-30, 30)]))
        for p in (*wc.ALERT_LEVELS, wc.WCV):
            assert wc.time_to_violation(s, v, dz, vz, p, 55.0) == wc._time_to_violation_scalar(s, v, dz, vz, p, 55.0)
            checked += 1
    assert checked == 6000
    assert wc.time_to_violation((0.0, 0.0), (0.0, 0.0), 0.0, 0.0, wc.WCV, 10.0) == 0.0  # stationary inside: violated now
    assert wc.time_to_violation((100000.0, 0.0), (10.0, 0.0), 0.0, 0.0, wc.WCV, 55.0) is None  # diverging


def test_rasteriser_matches_reference_bit_for_bit_with_and_without_chunking():
    v, f = sphere_mesh(48, 24)
    ref = render._rasterise_reference(v, f, 80, 30, 20)
    assert np.array_equal(render.rasterise(v, f, 80, 30, 20), ref)
    assert np.array_equal(render.rasterise(v, f, 80, 30, 20, chunk_px=3000), ref)  # many small chunks, same z-buffer outcome
    for yaw, pitch in ((0, 0), (90, -30), (200, 60)):
        assert np.array_equal(render.rasterise(v, f, 48, yaw, pitch), render._rasterise_reference(v, f, 48, yaw, pitch))
    empty = render.rasterise(v, np.zeros((0, 3), dtype=np.int64), 16)
    assert empty.shape == (16, 16) and float(empty.max()) == pytest.approx(0.05)


def test_screen_matches_reference_on_a_synthetic_shell():
    pytest.importorskip("sgp4")
    from aero_audit.space.orbital import ElementSet

    sets = synthetic_elements(30)
    # a trailing twin of the first object (same plane, mean anomaly 0.05 deg behind): a guaranteed close, co-moving pair
    l2 = sets[0].line2
    ma = float(l2[43:51]) - 0.05
    twin_l2 = l2[:43] + f"{ma:8.4f}" + l2[51:68]
    twin_l2 += str(sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in twin_l2) % 10)
    sets.append(ElementSet("TWIN", sets[0].line1, twin_l2))
    start = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    new = screen(sets, start, 4.0, 10.0, max_sets=40)
    ref = _screen_reference(sets, start, 4.0, 10.0, max_sets=40)

    def key(r: dict) -> dict:
        return {(a["a"], a["b"]): (a["tca_s"], a["min_km"], a["rel_speed_kms"]) for a in r["approaches"] + r["co_moving"]}

    assert key(new) == key(ref) and new["propagation_errors"] == ref["propagation_errors"] and new["pairs"] == ref["pairs"] == 31 * 30 // 2
    assert ("BENCH 0", "TWIN") in key(new) and key(new)[("BENCH 0", "TWIN")][1] < 10.0


def test_catalog_hash_cache_is_transparent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/a.json").write_text("{}")
    first = catalog.build_catalog(tmp_path)
    cache = tmp_path / catalog.HASH_CACHE
    assert cache.is_file()
    second = catalog.build_catalog(tmp_path)
    assert [g["sha256"] for g in second["collections"]["reports"]["granules"]] == [g["sha256"] for g in first["collections"]["reports"]["granules"]]
    (tmp_path / "reports/a.json").write_text('{"changed": true}')
    third = catalog.build_catalog(tmp_path)
    assert third["collections"]["reports"]["granules"][0]["sha256"] != first["collections"]["reports"]["granules"][0]["sha256"]
    nocache = catalog.build_catalog(tmp_path, hash_cache=None)
    assert nocache["collections"]["reports"]["granules"][0]["sha256"] == third["collections"]["reports"]["granules"][0]["sha256"]


def test_summaries_are_memoised_briefly(monkeypatch):
    from aero_audit.web import views

    calls = {"n": 0}

    def fake() -> dict:
        calls["n"] += 1
        return {"n": calls["n"]}

    views._cache.clear()
    assert views._memo("t", fake)["n"] == 1 and views._memo("t", fake)["n"] == 1
    monkeypatch.setattr(views, "CACHE_TTL_S", 0.0)
    assert views._memo("t", fake)["n"] == 2
    views._cache.clear()
