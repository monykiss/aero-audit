"""UAS integration: well-clear and alerting metrics on recorded encounters, encounter extraction
from surveillance recordings, and contract checks against UTM OpenAPI documents.

The well-clear definitions follow NASA's DAIDALUS / RTCA DO-365 formulation (modified tau,
horizontal miss distance, vertical threshold); this package computes metrics offline on recorded
tracks and never issues guidance to anything airborne.
"""

from .encounters import extract_encounters, summarize_encounters
from .wellclear import ALERT_LEVELS, WCV, WellClearParams, alert_level, evaluate, hmd_ft, tau_mod_s

__all__ = ["ALERT_LEVELS", "WCV", "WellClearParams", "alert_level", "evaluate", "extract_encounters", "hmd_ft", "summarize_encounters", "tau_mod_s"]
