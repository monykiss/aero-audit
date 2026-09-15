"""CCSDS CDM parsing, the 2D probability of collision, and the ORB-004 / ORB-005 rules."""

import math
from pathlib import Path

import pytest

from aero_audit.space import cdm as cdmmod

SAMPLE = Path("data/samples/synthetic_conjunction.cdm")


def test_parse_sample_cdm():
    c = cdmmod.parse_cdm(SAMPLE.read_text())
    assert c.message_id == "SYN-2026-0915-001" and c.originator == "AERO-AUDIT-SYNTHETIC" and c.tca.startswith("2026-09-16")
    assert c.miss_distance_m == 50.0 and c.relative_speed_ms == 15000.0 and c.stated_pc is None
    assert len(c.objects) == 2 and c.objects[0].designator == "99991" and c.objects[1].name == "SYN-DEBRIS-B"
    assert c.objects[0].position_km == (7000.0, 0.0, 0.0) and c.objects[1].velocity_kms == (0.0, -7.5, 0.0)
    assert c.objects[0].cov_rtn_m2[0][0] == 10000.0 and c.objects[1].cov_rtn_m2[2][2] == 10000.0
    assert c.to_dict()["objects"][0]["has_covariance"]


def test_pc_matches_the_closed_form_for_an_isotropic_case():
    c = cdmmod.parse_cdm(SAMPLE.read_text())
    r = cdmmod.pc_2d(c, hbr_m=20.0)
    # isotropic sigma 100 m per object -> combined 2e4 m^2 in the plane; miss 50 m; small disc approximation:
    # Pc ~ (pi hbr^2) / (2 pi s^2) * exp(-miss^2 / (2 s^2))
    s2 = 2 * 10000.0
    approx = (math.pi * 20.0**2) / (2 * math.pi * s2) * math.exp(-(50.0**2) / (2 * s2))
    assert abs(r["pc"] - approx) / approx < 0.03 and 0.005 < r["pc"] < 0.02
    assert abs(r["miss_m"] - 50.0) < 1e-6 and abs(r["relative_speed_ms"] - 15000.0) < 1e-6
    assert r["sigma_plane_m"][0] == pytest.approx(math.sqrt(s2), rel=1e-6)


def test_pc_limits_and_inconsistency_rules():
    text = SAMPLE.read_text()
    far = cdmmod.parse_cdm(text.replace("Z = 0.05 [km]", "Z = 5.0 [km]"))
    assert cdmmod.pc_2d(far)["pc"] < 1e-9
    tight = cdmmod.parse_cdm(text.replace("10000.0 [m**2]", "1.0 [m**2]").replace("Z = 0.05 [km]", "Z = 0.0 [km]"))
    assert cdmmod.pc_2d(tight, hbr_m=20.0)["pc"] > 0.99  # sigmas of 1 m, zero miss, 20 m disc
    res, fs = cdmmod.assess(cdmmod.parse_cdm(text))
    assert {f.rule_id for f in fs} == {"ORB-004"} and fs[0].severity.value == "high" and res["miss_consistency"] < 0.01
    _res2, fs2 = cdmmod.assess(cdmmod.parse_cdm(text.replace("MISS_DISTANCE = 50.0 [m]", "MISS_DISTANCE = 500.0 [m]")))
    assert any(f.rule_id == "ORB-005" for f in fs2) and any(f.rule_id == "ORB-004" for f in fs2)
    bad = cdmmod.parse_cdm(text.replace("CR_R = 10000.0 [m**2]", "CR_R = -1.0 [m**2]", 1))
    res3, fs3 = cdmmod.assess(bad)
    assert "error" in res3 and fs3[0].rule_id == "ORB-005" and "positive definite" in fs3[0].title
    _res4, fs4 = cdmmod.assess(cdmmod.parse_cdm(text.replace("Z = 0.05 [km]", "Z = 0.6 [km]").replace("MISS_DISTANCE = 50.0 [m]", "MISS_DISTANCE = 600.0 [m]")))
    assert fs4 == [] or all(f.rule_id != "ORB-004" or f.severity.value == "medium" for f in fs4)


def test_rtn_rotation_preserves_trace_and_definiteness():
    cov = [[4.0, 1.0, 0.0], [1.0, 9.0, 0.5], [0.0, 0.5, 16.0]]
    out = cdmmod.rtn_to_inertial(cov, (7000.0, 100.0, 50.0), (-0.1, 7.5, 0.2))
    assert abs(sum(out[i][i] for i in range(3)) - 29.0) < 1e-9 and cdmmod.positive_definite(out)
    assert not cdmmod.positive_definite([[1.0, 2.0, 0.0], [2.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
