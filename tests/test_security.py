import json

from aero_audit.audit import AuditEngine
from aero_audit.audit.rules import RULE_CATALOG
from aero_audit.models import Batch, Source, StateVector
from aero_audit.security import PLAYBOOKS, THREATS, TrustLedger, WatchEntry, Watchlist, corroborate
from aero_audit.security.threats import Coverage


def test_threat_catalog_only_references_real_rules():
    known = set(RULE_CATALOG)
    for t in THREATS:
        unknown = set(t.detected_by) - known
        assert not unknown, f"{t.id} references unknown rules {unknown}"
        if t.coverage is Coverage.GAP:
            assert not t.detected_by


def test_every_rule_has_a_playbook_except_info_only():
    missing = [rid for rid in RULE_CATALOG if rid not in PLAYBOOKS and rid != "OPS-VIS-002"]
    assert not missing, f"rules without playbooks: {missing}"


def _sv(icao, lat, lon, ts, gs=400.0, track=90.0, src=Source.ADSBLOL, alt=30000.0):
    return StateVector(icao24=icao, ts=ts, lat=lat, lon=lon, baro_alt_ft=alt, gs_kt=gs, track_deg=track,
                       position_source="adsb", source=src)


def test_corroborate_agrees_after_dead_reckoning():
    # aircraft heading east at 360 kt = 6 nm/min = 0.1 deg lon/min at the equator-ish latitude 0
    a = Batch(ts=100, provider="a", region="r", states=[_sv("x", 0.0, 10.0, 100, gs=360, track=90)])
    b = Batch(ts=160, provider="b", region="r", states=[_sv("x", 0.0, 10.1, 160, gs=360, track=90, src=Source.OPENSKY)])
    res = corroborate(a, b)
    assert res.matched == 1 and res.disagreements == 0 and res.separations_nm[0] < 0.5


def test_corroborate_flags_spoof():
    a = Batch(ts=100, provider="a", region="r", states=[_sv("x", 0.0, 10.0, 100)])
    b = Batch(ts=100, provider="b", region="r", states=[_sv("x", 0.5, 10.0, 100, src=Source.OPENSKY)])  # 30 nm apart
    res = corroborate(a, b)
    assert res.disagreements == 1
    f = res.findings[0]
    assert f.rule_id == "SEC-015" and f.severity.value == "high" and f.evidence["separation_nm"] > 25


def test_trust_ledger_erodes_and_recovers():
    from aero_audit.audit.findings import Category, Finding, Severity

    led = TrustLedger()
    f = Finding(rule_id="SEC-010", title="t", severity=Severity.CRITICAL, category=Category.SECURITY, icao24="abc", ts=0)
    assert led.penalize(f) < 0.5
    for _ in range(40):
        led.observe_clean("abc")
    assert led.score("abc") > 0.9
    assert led.low_trust() == []


def test_watchlist_matches_prefix_and_address(tmp_path):
    wl = Watchlist([WatchEntry("vip", "protect", callsign_prefix="LIFE", mode="protect", severity="info"),
                    WatchEntry("bad", "detect", icao24="ABC123")])
    p = tmp_path / "wl.json"
    wl.save(p)
    wl2 = Watchlist.load(p)
    sv = StateVector(icao24="abc123", callsign="LIFE12 ", ts=0, lat=0, lon=0, source=Source.SYNTHETIC)
    hits = wl2.check(sv)
    assert {h.title for h in hits} == {"Watchlist match (protect): vip", "Watchlist match (detect): bad"}
    assert all(h.rule_id == "SEC-020" for h in hits)


def _batch(ts, icaos, region="r"):
    return Batch(ts=ts, provider="p", region=region, states=[_sv(i, 40.0, -74.0 + k * 0.01, ts) for k, i in enumerate(icaos)])


def test_stream_checks_burst_and_collapse():
    eng = AuditEngine(cooldown_s=0)
    base = [f"a{i:04x}" for i in range(60)]
    for k in range(5):
        eng.process_batch(_batch(1000 + 10 * k, base))
    burst = base + [f"b{i:04x}" for i in range(80)]
    f = eng.process_batch(_batch(1060, burst))
    assert any(x.rule_id == "SEC-016" for x in f)
    f = eng.process_batch(_batch(1070, base[:10]))
    assert any(x.rule_id == "SEC-017" for x in f)


def test_engine_reports_low_trust_and_alerts(tmp_path):
    from aero_audit.alerts import Alerter, JsonlSink
    from aero_audit.audit.findings import Severity

    log = tmp_path / "alerts.jsonl"
    eng = AuditEngine(cooldown_s=0, alerter=Alerter([JsonlSink(log)], Severity.HIGH))
    sv1 = _sv("dead01", 40.0, -74.0, 1000)
    sv2 = _sv("dead01", 41.0, -74.0, 1010)  # 60 nm in 10 s -> SEC-010 critical
    eng.process_batch(Batch(ts=1000, provider="p", region="r", states=[sv1]))
    eng.process_batch(Batch(ts=1010, provider="p", region="r", states=[sv2]))
    s = eng.summary()
    assert s["by_rule"].get("SEC-010") == 1 and s["alerts_sent"] == 1
    assert s["low_trust_aircraft"] and s["low_trust_aircraft"][0][0] == "dead01"
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["rule_id"] == "SEC-010"


def test_compliance_kpi_counts_only_adsb_airborne():
    eng = AuditEngine(cooldown_s=0)
    good = StateVector(icao24="g1", ts=1, lat=40, lon=-74, baro_alt_ft=20000, nic=8, nac_p=9, sil=3,
                       position_source="adsb", source=Source.ADSBLOL)
    bad = StateVector(icao24="b1", ts=1, lat=40, lon=-74, baro_alt_ft=20000, nic=5, nac_p=5, sil=0,
                      position_source="adsb", source=Source.ADSBLOL)
    tisb = StateVector(icao24="t1", ts=1, lat=40, lon=-74, baro_alt_ft=20000, nic=0, nac_p=0, sil=0,
                       position_source="tisb", source=Source.ADSBLOL)
    eng.process_batch(Batch(ts=1, provider="p", region="r", states=[good, bad, tisb]))
    s = eng.summary()
    assert s["adsb_airborne_fixes"] == 2 and s["adsb_compliance_rate"] == 0.5


def test_per_rule_cooldown_override_suppresses_slow_conditions():
    eng = AuditEngine(cooldown_s=0)  # default cooldown off, overrides still apply
    sv = StateVector(icao24="c1", ts=0, lat=40, lon=-74, baro_alt_ft=20000, nic=5, nac_p=5, sil=0,
                     position_source="adsb", source=Source.ADSBLOL)
    n = 0
    for k in range(10):
        n += sum(1 for f in eng.process_batch(Batch(ts=k * 60, provider="p", region="r", states=[sv.model_copy(update={"ts": k * 60})]))
                 if f.rule_id == "SEC-012")
    assert n == 1  # 10 minutes < 15-minute override -> one finding, occurrences keep counting
    assert next(f for f in eng.findings if f.rule_id == "SEC-012").occurrences == 1


def test_ml_findings_require_persistence():
    from aero_audit.audit.findings import Category, Finding, Severity

    class FakeModel:
        def findings(self, feats, ctx):
            return [Finding(rule_id="ML-001", title="m", severity=Severity.LOW, category=Category.ML,
                            icao24=f.icao24, ts=f.ts) for f in feats]

    eng = AuditEngine(ml_model=FakeModel(), cooldown_s=0)
    out = []
    for k in range(3):
        sv = _sv("m1", 40.0, -74.0 + 0.05 * k, 1000 + 30 * k, alt=20000.0)
        out += [f for f in eng.process_batch(Batch(ts=1000 + 30 * k, provider="p", region="r", states=[sv])) if f.rule_id == "ML-001"]
    # first feature row appears at batch 2 (needs two fixes) -> one flag; second row at batch 3 -> persistence met
    assert len(out) == 1 and out[0].evidence["flagged_fixes_10min"] == 2


def test_reports_include_html_and_executive_summary(tmp_path):
    from aero_audit.audit import write_reports

    eng = AuditEngine(cooldown_s=0)
    eng.process_batch(Batch(ts=1000, provider="p", region="r", states=[_sv("dead01", 40.0, -74.0, 1000)]))
    eng.process_batch(Batch(ts=1010, provider="p", region="r", states=[_sv("dead01", 41.0, -74.0, 1010)]))
    jp, mp, hp = write_reports(eng, tmp_path, "t")
    assert jp.exists() and "## Executive summary" in mp.read_text()
    h = hp.read_text()
    assert "<!doctype html>" in h and "SEC-010" in h and "Do first" in h


def test_threat_scenarios_exist_and_measured_recall_renders():
    from aero_audit.ml.evaluate import SCENARIOS
    from aero_audit.security.threats import coverage_matrix, render_markdown

    for t in THREATS:
        assert set(t.scenarios) <= set(SCENARIOS), t.id
    fake = {"recording": "x", "created_at": "now", "median_revisit_s": 20,
            "scenarios": [{"name": "teleport", "recall": 0.88}, {"name": "ghost_perfect", "recall": 0.0}]}
    row = next(r for r in coverage_matrix(fake) if r["id"] == "T01")
    assert row["measured"] == "teleport 88%, ghost_perfect 0%"
    assert "Measured recall" in render_markdown(fake)
    assert next(r for r in coverage_matrix(None) if r["id"] == "T01")["measured"] == "-"
