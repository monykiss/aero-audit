from aero_audit.audit.findings import Category, Finding, Severity
from aero_audit.impact import ImpactAssumptions, estimate_holding_impact


def test_holding_impact_sums_windows():
    f = [Finding(rule_id="OPS-002", title="h", severity=Severity.LOW, category=Category.OPERATIONS,
                 icao24=i, ts=0, evidence={"span_s": 300}) for i in ("a", "b")]
    est = estimate_holding_impact(f, ImpactAssumptions(fuel_kg_per_min=40, co2_kg_per_kg_fuel=3.16,
                                                       delay_cost_per_min=100, fuel_price_per_kg=1.0))
    assert est.holds == 2 and est.aircraft == 2 and est.observed_minutes == 10
    assert est.fuel_kg == 400 and abs(est.co2_kg - 1264) < 1e-6 and est.delay_cost == 1000
