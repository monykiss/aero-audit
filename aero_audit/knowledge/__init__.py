"""Bundled reference data for the flight ecosystem: airports, operators, aircraft types."""

from .airlines import OPERATORS, operator_of
from .airports import AIRPORTS, Airport, nearest_airport
from .types import TYPES, type_info

__all__ = ["AIRPORTS", "OPERATORS", "TYPES", "Airport", "nearest_airport", "operator_of", "type_info"]
