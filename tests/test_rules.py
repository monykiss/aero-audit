from pathlib import Path

from aero_audit.audit import AuditEngine
from aero_audit.ingest import iter_recording
from aero_audit.synthetic import generate


def _run(tmp_path: Path) -> AuditEngine:
    rec = generate(tmp_path / "syn.jsonl", n_aircraft=30, polls=24, seed=7)
    engine = AuditEngine(cooldown_s=120)
    engine.run(iter_recording(rec))
    return engine


def test_injected_anomalies_are_caught(tmp_path):
    engine = _run(tmp_path)
    rules = {f.rule_id for f in engine.findings}
    for expected in ("SEC-001", "SEC-010", "SEC-012", "SEC-013", "OPS-002", "OPS-004", "OPS-005", "SAF-003"):
        assert expected in rules, f"{expected} missing; got {sorted(rules)}"


def test_spoof_is_attributed_to_the_right_aircraft(tmp_path):
    engine = _run(tmp_path)
    spoof = [f for f in engine.findings if f.rule_id == "SEC-010"]
    assert {f.icao24 for f in spoof} == {"a00000"}
    assert spoof[0].severity.value in ("high", "critical")
    assert spoof[0].evidence["implied_gs_kt"] > 750


def test_normal_traffic_is_quiet(tmp_path):
    engine = _run(tmp_path)
    noisy = {f.icao24 for f in engine.findings if f.category.value in ("security", "safety")}
    injected = {f"a{i:05x}" for i in range(8)}
    assert noisy <= injected, f"false positives on normal traffic: {noisy - injected}"


def test_cooldown_dedups_repeats(tmp_path):
    engine = _run(tmp_path)
    emerg = [f for f in engine.findings if f.rule_id == "SEC-001"]
    # 7700 is set for ~16 polls (160 s): first fix unconfirmed (medium), second escalates to high through the
    # cooldown, then the 120 s cooldown holds -> a handful of findings, not 16
    assert 2 <= len(emerg) <= 4
    assert emerg[0].severity.value == "medium" and "unconfirmed" in emerg[0].title
    assert emerg[1].severity.value == "high" and emerg[1].evidence["consecutive_fixes"] >= 2
    assert emerg[-1].occurrences >= 2


def test_mlat_jump_is_data_quality_not_security():
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, Source, StateVector

    def sv(lat, ts):
        return StateVector(icao24="ae0001", ts=ts, lat=lat, lon=-105.0, baro_alt_ft=40000, gs_kt=None,
                           position_source="mlat", source=Source.ADSBLOL)

    eng = AuditEngine(cooldown_s=0)
    eng.process_batch(Batch(ts=0, provider="p", region="r", states=[sv(41.0, 0)]))
    out = eng.process_batch(Batch(ts=30, provider="p", region="r", states=[sv(42.5, 30)]))  # 90 nm in 30 s
    jump = next(f for f in out if f.rule_id == "SEC-010")
    assert jump.category.value == "data-quality" and jump.severity.value == "medium"


def test_altitude_forgery_is_caught_and_source_aware():
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, Source, StateVector

    def sv(alt, ts, src="adsb"):
        return StateVector(icao24="a11111", ts=ts, lat=40.0, lon=-74.0 + 0.02 * (ts / 30), baro_alt_ft=alt,
                           gs_kt=300, track_deg=90, vrate_fpm=0.0, position_source=src, source=Source.ADSBLOL)

    eng = AuditEngine(cooldown_s=0)
    eng.process_batch(Batch(ts=0, provider="p", region="r", states=[sv(30000, 0)]))
    out = eng.process_batch(Batch(ts=30, provider="p", region="r", states=[sv(36000, 30)]))  # +6000 ft in 30 s, reported 0 fpm
    f = next(x for x in out if x.rule_id == "SEC-018")
    assert f.category.value == "security" and f.severity.value == "high"
    eng2 = AuditEngine(cooldown_s=0)
    eng2.process_batch(Batch(ts=0, provider="p", region="r", states=[sv(30000, 0, "mlat")]))
    out2 = eng2.process_batch(Batch(ts=30, provider="p", region="r", states=[sv(36000, 30, "mlat")]))
    f2 = next(x for x in out2 if x.rule_id == "SEC-018")
    assert f2.category.value == "data-quality"


def test_single_fix_7500_is_unconfirmed_then_escalates():
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, Source, StateVector

    def sv(ts, squawk):
        return StateVector(icao24="a45bfa", ts=ts, lat=33.3 + ts / 36000, lon=-118.4, baro_alt_ft=15000, gs_kt=350,
                           squawk=squawk, position_source="adsb", source=Source.OPENSKY)

    eng = AuditEngine()
    eng.process_batch(Batch(ts=0, provider="p", region="r", states=[sv(0, "2435")]))
    first = eng.process_batch(Batch(ts=20, provider="p", region="r", states=[sv(20, "7500")]))
    f1 = next(f for f in first if f.rule_id == "SEC-003")
    assert f1.severity.value == "high" and "unconfirmed" in f1.title
    second = eng.process_batch(Batch(ts=40, provider="p", region="r", states=[sv(40, "7500")]))
    f2 = next(f for f in second if f.rule_id == "SEC-003")
    assert f2.severity.value == "critical" and f2.evidence["consecutive_fixes"] == 2  # escalation beat the cooldown
    third = eng.process_batch(Batch(ts=60, provider="p", region="r", states=[sv(60, "7500")]))
    assert not [f for f in third if f.rule_id == "SEC-003"]  # same severity inside cooldown: suppressed


def test_departure_from_high_elevation_airport_is_not_an_altitude_jump():
    from aero_audit.audit import AuditEngine
    from aero_audit.ingest.opensky import map_row

    ground = map_row(["acb9ed", "AAL1456 ", "US", 0, 0, -111.97, 40.79, None, True, 10.0, 180.0, 0.0, None, None, "1234", False, 0], 0)
    air = map_row(["acb9ed", "AAL1456 ", "US", 25, 25, -111.96, 40.78, 1310.0, False, 80.0, 180.0, 5.0, None, None, "1234", False, 0], 25)
    assert ground.baro_alt_ft is None and abs(air.baro_alt_ft - 4297.9) < 1
    from aero_audit.models import Batch

    eng = AuditEngine(cooldown_s=0)
    eng.process_batch(Batch(ts=0, provider="p", region="r", states=[ground]))
    out = eng.process_batch(Batch(ts=25, provider="p", region="r", states=[air]))
    assert not [f for f in out if f.rule_id in ("SEC-018", "SAF-003")]


def test_recorded_zero_altitude_on_ground_does_not_create_vertical_rate():
    """Recordings made before the altitude fix store 0 ft on the ground; the feature layer must not trust it."""
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, Source, StateVector

    ground = StateVector(icao24="acb9ed", ts=0, lat=40.79, lon=-111.97, baro_alt_ft=0.0, gs_kt=54, on_ground=True,
                         position_source="adsb", source=Source.OPENSKY)
    air = StateVector(icao24="acb9ed", ts=25, lat=40.78, lon=-111.96, baro_alt_ft=3950, gs_kt=160, vrate_fpm=65,
                      on_ground=False, position_source="adsb", source=Source.OPENSKY)
    eng = AuditEngine(cooldown_s=0)
    eng.process_batch(Batch(ts=0, provider="p", region="r", states=[ground]))
    out = eng.process_batch(Batch(ts=25, provider="p", region="r", states=[air]))
    assert not [f for f in out if f.rule_id in ("SEC-018", "SAF-003")]
    assert eng.store.features("acb9ed").implied_vrate_fpm is None


def test_proximity_rule_flags_close_pairs_only_when_airborne_and_high():
    from aero_audit.audit import AuditEngine
    from aero_audit.models import Batch, Source, StateVector

    def sv(i, lat, lon, alt, ts=1000.0):
        return StateVector(icao24=i, ts=ts, lat=lat, lon=lon, baro_alt_ft=alt, gs_kt=300, track_deg=90,
                           position_source="adsb", source=Source.ADSBLOL)

    close = [sv("p1", 40.0, -74.0, 30000), sv("p2", 40.0, -74.02, 30300)]  # ~0.9 nm, 300 ft
    spaced = [sv("q1", 41.0, -74.0, 31000), sv("q2", 41.0, -74.02, 32000)]  # 1,000 ft apart
    low = [sv("r1", 42.0, -74.0, 2000), sv("r2", 42.0, -74.02, 2100)]  # approach phase, excluded
    out = AuditEngine(cooldown_s=0).process_batch(Batch(ts=1000, provider="p", region="r", states=close + spaced + low))
    prox = [f for f in out if f.rule_id == "SAF-004"]
    assert len(prox) == 1 and prox[0].icao24 == "p1" and prox[0].evidence["other_icao24"] == "p2"
    assert prox[0].severity.value == "medium"
