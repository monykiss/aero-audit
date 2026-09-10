from aero_audit.ml.evaluate import SCENARIOS, evaluate
from aero_audit.synthetic import generate


def test_harness_measures_recall_on_synthetic_background(tmp_path):
    rec = generate(tmp_path / "bg.jsonl", n_aircraft=30, polls=24, seed=11)
    rep = evaluate(rec, model_path=None, n_targets=5, seed=1,
                   scenarios=["teleport", "squawk_hijack", "altitude_forge", "replay", "ghost_perfect"])
    by = {r.name: r for r in rep.results}
    assert by["teleport"].recall >= 0.8 and by["teleport"].median_ttd_s is not None
    assert by["squawk_hijack"].recall == 1.0
    assert by["altitude_forge"].recall >= 0.8
    assert by["replay"].recall >= 0.8
    assert by["ghost_perfect"].known_gap and by["ghost_perfect"].recall <= 0.2
    assert rep.rule_precision["SEC-010"] is not None and rep.rule_precision["SEC-010"] >= 0.5
    assert set(SCENARIOS) >= {"velocity_forge", "integrity_degrade", "slow_drift"}


def test_target_selection_is_region_aware():
    from aero_audit.ml.evaluate import select_targets
    from aero_audit.models import Batch, Source, StateVector

    def sv(i, ts):
        return StateVector(icao24=i, ts=ts, lat=40, lon=-74, baro_alt_ft=30000, gs_kt=400, position_source="adsb",
                           source=Source.ADSBLOL)

    batches = []
    for k in range(20):  # two regions interleaved; each aircraft only in its own region
        region = "a" if k % 2 == 0 else "b"
        batches.append(Batch(ts=k * 10, provider="p", region=region, states=[sv(f"x{region}", k * 10)]))
    assert set(select_targets(batches, 5, 1)) == {"xa", "xb"}
    assert select_targets(batches, 5, 1, onset=19) == []  # nothing left after onset -> not a valid target


def test_stale_positions_do_not_qualify_as_targets():
    from aero_audit.ml.evaluate import select_targets
    from aero_audit.models import Batch, Source, StateVector

    def sv(ts):  # same position timestamp every batch: the feed is re-reporting a stale fix
        return StateVector(icao24="stale1", ts=ts, lat=40, lon=-74, baro_alt_ft=30000, gs_kt=400,
                           position_source="adsb", source=Source.ADSBLOL)

    batches = [Batch(ts=k * 10, provider="p", region="a", states=[sv(100.0)]) for k in range(20)]
    assert select_targets(batches, 5, 1, onset=5) == []
