"""Turn operational findings into quantities decision-makers recognise: minutes, fuel, CO2, cost.

Defaults are order-of-magnitude values documented in docs/IMPACT.md; every one is a parameter
because the operator's own numbers are always better than ours.
"""

from __future__ import annotations

from dataclasses import dataclass

from .audit.findings import Finding


@dataclass(frozen=True)
class ImpactAssumptions:
    fuel_kg_per_min: float = 40.0  # narrow-body holding burn ~2,400 kg/h
    co2_kg_per_kg_fuel: float = 3.16  # ICAO carbon calculator factor
    delay_cost_per_min: float = 100.0  # EUR, order of magnitude (EUROCONTROL / Univ. of Westminster)
    fuel_price_per_kg: float = 0.85  # EUR/kg Jet A-1, order of magnitude


@dataclass
class HoldingImpact:
    holds: int
    aircraft: int
    observed_minutes: float
    fuel_kg: float
    co2_kg: float
    fuel_cost: float
    delay_cost: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "holds": self.holds,
            "aircraft": self.aircraft,
            "observed_minutes": round(self.observed_minutes, 1),
            "fuel_kg": round(self.fuel_kg),
            "co2_kg": round(self.co2_kg),
            "fuel_cost": round(self.fuel_cost),
            "delay_cost": round(self.delay_cost),
        }


DEFAULT_ASSUMPTIONS = ImpactAssumptions()


def estimate_holding_impact(findings: list[Finding], a: ImpactAssumptions = DEFAULT_ASSUMPTIONS) -> HoldingImpact:
    """Sum observed holding time from OPS-002 evidence (`span_s` of the detection window).

    Observed time is a floor: the window only covers the last N fixes and the capture may end
    mid-hold. Repeated OPS-002 findings for one aircraft (after the cooldown) add their windows.
    """
    holds = [f for f in findings if f.rule_id == "OPS-002"]
    minutes = sum(float(f.evidence.get("span_s") or 0) for f in holds) / 60.0
    fuel = minutes * a.fuel_kg_per_min
    return HoldingImpact(
        holds=len(holds),
        aircraft=len({f.icao24 for f in holds if f.icao24}),
        observed_minutes=minutes,
        fuel_kg=fuel,
        co2_kg=fuel * a.co2_kg_per_kg_fuel,
        fuel_cost=fuel * a.fuel_price_per_kg,
        delay_cost=minutes * a.delay_cost_per_min,
    )
