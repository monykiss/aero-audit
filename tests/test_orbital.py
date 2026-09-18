"""Orbital slice: TLE parsing with checksums, SGP4 propagation, conjunction screening, ORB rules."""

from datetime import UTC, datetime, timedelta

import pytest

from aero_audit.space import orbital

ISS = ("ISS (ZARYA)", "1 25544U 98067A   26253.46606357  .00004975  00000+0  98181-4 0  9990",
       "2 25544  51.6301 238.0248 0004989 125.6916 234.4537 15.49068969584973")
# same orbit, mean anomaly shifted by 0.02 deg: a few km ahead, a guaranteed close approach
NEAR = ("SHADOW", "1 99999U 26001A   26253.46606357  .00004975  00000+0  98181-4 0  9990",
        "2 99999  51.6301 238.0248 0004989 125.6916 234.4737 15.49068969584973")


def _fix_checksum(line: str) -> str:
    total = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
    return line[:68] + str(total % 10)


def _text(*sets):
    return "\n".join(f"{n}\n{_fix_checksum(l1)}\n{_fix_checksum(l2)}" for n, l1, l2 in sets) + "\n"


def test_parse_tle_and_checksums():
    sets = orbital.parse_tle(_text(ISS, NEAR))
    assert [s.norad_id for s in sets] == [25544, 99999] and sets[0].epoch.year == 2026
    bad = _text(ISS).replace("9990", "9991")  # corrupt the checksum digit
    assert orbital.parse_tle(bad) == []
    two_line = "\n".join(_text(ISS).splitlines()[1:])
    assert orbital.parse_tle(two_line)[0].name == "NORAD 25544"


def test_screen_finds_the_shadow_and_flags_stale_elements():
    pytest.importorskip("sgp4")
    sets = orbital.parse_tle(_text(ISS, NEAR))
    start = sets[0].epoch + timedelta(hours=1)
    res = orbital.screen(sets, start, hours=2.0, threshold_km=50.0, coarse_step_s=60.0, fine_step_s=2.0, min_rel_speed_kms=0.0)
    assert res["pairs"] == 1 and len(res["approaches"]) == 1
    default = orbital.screen(sets, start, hours=2.0, threshold_km=50.0, coarse_step_s=60.0, fine_step_s=2.0)
    assert default["approaches"] == [] and len(default["co_moving"]) == 1  # same orbit, near-zero relative speed: docked / formation, not a conjunction
    a = res["approaches"][0]
    assert a["min_km"] < 20 and a["rel_speed_kms"] < 0.5 and res["propagation_errors"] == []
    fs = orbital.findings(res, sets)
    assert {f.rule_id for f in fs} == {"ORB-002"}
    late = orbital.screen(sets, sets[0].epoch + timedelta(days=30), hours=0.5, threshold_km=50.0, coarse_step_s=300.0, fine_step_s=10.0)
    fs2 = orbital.findings(late, sets)
    assert sum(1 for f in fs2 if f.rule_id == "ORB-001") == 2 and all("age_days" in f.evidence for f in fs2 if f.rule_id == "ORB-001")


def test_far_apart_objects_produce_no_approach():
    pytest.importorskip("sgp4")
    gps = ("GPS-LIKE", "1 40294U 14068A   26253.50000000  .00000010  00000+0  00000+0 0  9990",
           "2 40294  55.0000 100.0000 0010000  50.0000 310.0000  2.00560000 80000")
    sets = orbital.parse_tle(_text(ISS, gps))
    assert len(sets) == 2
    res = orbital.screen(sets, sets[0].epoch, hours=1.0, threshold_km=10.0, coarse_step_s=120.0)
    assert res["approaches"] == [] and res["covariance"].startswith("none")


def test_group_name_validation():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(orbital.fetch_group("../etc"))
    assert datetime.now(UTC).year >= 2026
