"""Well-clear maths against hand-computed values, encounter extraction on the bundled sample, contract validation."""

import json
import math
from pathlib import Path

from aero_audit.uas import (
    ALERT_LEVELS,
    WCV,
    alert_level,
    evaluate,
    extract_encounters,
    hmd_ft,
    summarize_encounters,
    tau_mod_s,
)
from aero_audit.uas.utm import check_samples, response_schema, validate
from aero_audit.uas.wellclear import FT_PER_NM, FT_PER_S_PER_KT, relative_geometry, violates

SAMPLE = Path("data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz")


def test_tau_mod_and_hmd_by_hand():
    closure = 400.0 * FT_PER_S_PER_KT  # 675 ft/s head-on
    s5 = (5 * FT_PER_NM, 0.0)
    v = (-closure, 0.0)
    assert hmd_ft(s5, v) < 1e-6  # dead ahead, will pass through
    tm = tau_mod_s(s5, v, WCV.dthr_ft)
    expected = (WCV.dthr_ft**2 - (5 * FT_PER_NM) ** 2) / (-(5 * FT_PER_NM) * closure)
    assert abs(tm - expected) < 1e-6 and 40 < tm < 48
    assert not violates(s5, v, 0.0, 0.0)  # 44 s > TTHR 35 s: still well clear
    s3 = (3 * FT_PER_NM, 0.0)
    assert violates(s3, v, 0.0, 0.0) and not violates(s3, v, 800.0, 0.0)  # inside tau but 800 ft above -> vertical ok
    assert math.isinf(tau_mod_s(s5, (closure, 0.0), WCV.dthr_ft))  # diverging
    assert tau_mod_s((1000.0, 0.0), v, WCV.dthr_ft) == 0.0  # already inside DTHR
    # offset track: HMD 1 nm > DTHR -> never violates horizontally
    assert not violates((5 * FT_PER_NM, 1.0 * FT_PER_NM), v, 0.0, 0.0) and abs(hmd_ft((5 * FT_PER_NM, FT_PER_NM), v) - FT_PER_NM) < 1.0


def test_alert_levels_escalate_with_time_to_violation():
    closure = 400.0 * FT_PER_S_PER_KT
    v = (-closure, 0.0)
    # 5 nm head-on: tau_mod 44 s, so well clear is lost 9 s from now (44 - 35): inside the 25 s warning time
    lvl, name, t = alert_level((5 * FT_PER_NM, 0.0), v, 0.0, 0.0)
    assert name == "warning" and lvl == 3 and 5 < t < 15
    # 8 nm: tau_mod ~72 s, violation ~37 s away: corrective (55 s) but not warning (25 s)
    lvl, name, t = alert_level((8 * FT_PER_NM, 0.0), v, 0.0, 0.0)
    assert name == "corrective" and lvl == 2 and 25 < t <= 55
    lvl, name, _ = alert_level((8 * FT_PER_NM, 0.0), v, 600.0, 0.0)
    assert name == "preventive"  # 600 ft: inside the preventive ZTHR (700) only
    assert alert_level((12 * FT_PER_NM, 0.0), v, 0.0, 0.0) == (0, None, None)  # ~73 s away: beyond every alerting time
    assert alert_level((5 * FT_PER_NM, 0.0), (closure, 0.0), 0.0, 0.0) == (0, None, None)  # diverging
    e = evaluate((5 * FT_PER_NM, 0.0), v, 0.0, 0.0)
    assert e["well_clear"] and e["alert"] == "warning" and e["closure_ftps"] > 600 and e["hmd_ft"] == 0.0 and 5 < e["time_to_violation_s"] < 15
    assert [p.name for p in ALERT_LEVELS] == ["preventive", "corrective", "warning"]


def test_relative_geometry_units():
    s, v = relative_geometry(40.0, -74.0, 300.0, 90.0, 40.0, -73.9, 300.0, 270.0)  # 0.1 deg east at 40N, head-on E/W
    assert abs(s[0] - 0.1 * 60 * math.cos(math.radians(40.0)) * FT_PER_NM) < 1.0 and abs(s[1]) < 1e-6
    assert abs(v[0] + 600.0 * FT_PER_S_PER_KT) < 1e-6 and abs(v[1]) < 1e-6


def test_encounters_on_the_bundled_sample():
    ex = extract_encounters(SAMPLE, max_batches=4)
    assert ex["batches"] == 4 and ex["aircraft_airborne"] > 100 and ex["flight_hours"] > 0
    summary, findings = summarize_encounters(ex)
    assert summary["encounter_pairs"] >= 1 and summary["violations"] >= 0 and "violations_per_flight_hour" in summary
    for r in summary["pairs"][:5]:
        assert r["min_range_ft"] >= 0 and r["max_alert"] in (0, 1, 2, 3)
    assert all(f.rule_id in ("DAA-001", "DAA-002") for f in findings)


def test_schema_lite_validator_and_conformance_report():
    doc = {"components": {"schemas": {"Position": {"type": "object", "required": ["lat", "lng", "time_measured"],
                                                    "properties": {"lat": {"type": "number", "minimum": -90, "maximum": 90}, "lng": {"type": "number"},
                                                                   "alt": {"type": "number", "nullable": True}, "time_measured": {"type": "string", "format": "date-time"},
                                                                   "source": {"type": "string", "enum": ["ADS-B", "GPS"]}}, "additionalProperties": False},
                                     "Fix": {"allOf": [{"$ref": "#/components/schemas/Position"}, {"type": "object", "properties": {"id": {"type": "string", "format": "uuid"}}}]}}},
           "paths": {"/positions": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Position"}}}}}}}}}}
    good = {"lat": 40.6, "lng": -73.8, "alt": None, "time_measured": "2026-09-15T12:00:00Z", "source": "ADS-B"}
    assert validate(good, doc["components"]["schemas"]["Position"], doc) == []
    bad = {"lat": 95, "lng": "x", "time_measured": "yesterday", "source": "radar", "extra": 1}
    probs = validate(bad, doc["components"]["schemas"]["Position"], doc)
    assert any("maximum" in p for p in probs) and any("expected number" in p for p in probs) and any("date-time" in p for p in probs)
    assert any("enum" in p for p in probs) and any("unexpected property" in p for p in probs)
    assert validate([good], response_schema(doc, "/positions"), doc) == [] and validate([bad], response_schema(doc, "/positions"), doc)
    fix = {**good, "id": "not-a-uuid"}
    assert any("uuid" in p for p in validate(fix, doc["components"]["schemas"]["Fix"], doc))
    rep = check_samples(doc, [("a", good), ("b", bad)], schema_name="Position")
    assert rep["samples"] == 2 and rep["conformant"] == 1 and rep["rows"][1]["problems"]
    rep2 = check_samples(doc, [("list", [good, good])], path="/positions")
    assert rep2["conformant"] == 1
    assert json.dumps(rep2)
