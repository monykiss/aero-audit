"""Operators keyed by the three-letter ICAO designator that starts a callsign."""

from __future__ import annotations

import re

# code: (name, country, category)  category: airline | regional | cargo | business | charter
OPERATORS: dict[str, tuple[str, str, str]] = {
    "AAL": ("American Airlines", "US", "airline"), "DAL": ("Delta Air Lines", "US", "airline"),
    "UAL": ("United Airlines", "US", "airline"), "SWA": ("Southwest Airlines", "US", "airline"),
    "JBU": ("JetBlue", "US", "airline"), "ASA": ("Alaska Airlines", "US", "airline"),
    "NKS": ("Spirit Airlines", "US", "airline"), "FFT": ("Frontier Airlines", "US", "airline"),
    "AAY": ("Allegiant Air", "US", "airline"), "HAL": ("Hawaiian Airlines", "US", "airline"),
    "SCX": ("Sun Country", "US", "airline"), "MXY": ("Breeze Airways", "US", "airline"),
    "SKW": ("SkyWest", "US", "regional"), "RPA": ("Republic Airways", "US", "regional"),
    "EDV": ("Endeavor Air", "US", "regional"), "ENY": ("Envoy Air", "US", "regional"),
    "PDT": ("Piedmont Airlines", "US", "regional"), "JIA": ("PSA Airlines", "US", "regional"),
    "ASH": ("Mesa Airlines", "US", "regional"), "GJS": ("GoJet Airlines", "US", "regional"),
    "QXE": ("Horizon Air", "US", "regional"), "AWI": ("Air Wisconsin", "US", "regional"),
    "CPZ": ("Compass Airlines", "US", "regional"), "TSC": ("Air Transat", "CA", "airline"),
    "FDX": ("FedEx Express", "US", "cargo"), "UPS": ("UPS Airlines", "US", "cargo"),
    "ABX": ("ABX Air", "US", "cargo"), "ATN": ("Air Transport International", "US", "cargo"),
    "GTI": ("Atlas Air", "US", "cargo"), "CKS": ("Kalitta Air", "US", "cargo"),
    "PAC": ("Polar Air Cargo", "US", "cargo"), "NCR": ("National Airlines", "US", "cargo"),
    "AJT": ("Amerijet", "US", "cargo"), "CJT": ("Cargojet", "CA", "cargo"), "GEC": ("Lufthansa Cargo", "DE", "cargo"),
    "ACA": ("Air Canada", "CA", "airline"), "JZA": ("Jazz Aviation", "CA", "regional"),
    "ROU": ("Air Canada Rouge", "CA", "airline"), "WJA": ("WestJet", "CA", "airline"),
    "WEN": ("WestJet Encore", "CA", "regional"), "POE": ("Porter Airlines", "CA", "airline"),
    "FLE": ("Flair Airlines", "CA", "airline"), "SWG": ("Sunwing", "CA", "airline"),
    "AMX": ("Aeromexico", "MX", "airline"), "SLI": ("Aeromexico Connect", "MX", "regional"),
    "VOI": ("Volaris", "MX", "airline"), "VIV": ("Viva Aerobus", "MX", "airline"),
    "BAW": ("British Airways", "GB", "airline"), "VIR": ("Virgin Atlantic", "GB", "airline"),
    "DLH": ("Lufthansa", "DE", "airline"), "AFR": ("Air France", "FR", "airline"),
    "KLM": ("KLM", "NL", "airline"), "UAE": ("Emirates", "AE", "airline"), "QTR": ("Qatar Airways", "QA", "airline"),
    "SIA": ("Singapore Airlines", "SG", "airline"), "CPA": ("Cathay Pacific", "HK", "airline"),
    "JAL": ("Japan Airlines", "JP", "airline"), "ANA": ("All Nippon Airways", "JP", "airline"),
    "KAL": ("Korean Air", "KR", "airline"), "TAM": ("LATAM Brasil", "BR", "airline"),
    "AVA": ("Avianca", "CO", "airline"), "CMP": ("Copa Airlines", "PA", "airline"),
    "IBE": ("Iberia", "ES", "airline"), "EIN": ("Aer Lingus", "IE", "airline"), "SWR": ("Swiss", "CH", "airline"),
    "THY": ("Turkish Airlines", "TR", "airline"), "ETD": ("Etihad", "AE", "airline"), "ELY": ("El Al", "IL", "airline"),
    "EJA": ("NetJets", "US", "business"), "LXJ": ("Flexjet", "US", "business"),
    "EJM": ("Executive Jet Management", "US", "business"), "XOJ": ("XOJET", "US", "business"),
    "WUP": ("Wheels Up", "US", "business"), "JTL": ("Jet Linx", "US", "business"),
    "VJA": ("VistaJet", "US", "business"), "TWY": ("Sunwest Aviation", "CA", "business"),
    "DCM": ("Delta Private Jets", "US", "business"), "PJS": ("PrivatAir", "CH", "business"),
    "GAJ": ("Gama Aviation", "US", "business"), "JAS": ("Jet Aviation", "US", "business"),
    "N": ("General aviation (US registration)", "US", "ga"),
}
_MILITARY = re.compile(r"^(RCH|REACH|SAM|EVAC|TOPCAT|DUKE|HORSE|FRED|REDHK|PAT|CNV|NAVY|ARMY|COAST|CG|GLEX|SLICK|MOOSE|SPAR|VENUS|JAKE|GOLD|TITAN|OTIS|KING|BLUE|VIPER|RAPTOR|EAGLE|SWIFT|GRIFN|BLADE|SNAKE|ROCKY|RAIDR|KNIFE|HAWK|AF\d|USAF|TEST)")


def operator_of(callsign: str | None, registration: str | None = None) -> tuple[str, str, str, str]:
    """(code, name, country, category) for a callsign; falls back to registration / military words."""
    cs = (callsign or "").strip().upper()
    if cs.startswith("HBAL"):  # stratospheric balloons (Loon-style); at 60,000 ft they top every altitude sort
        return "HBAL", "High-altitude balloon", "US", "balloon"
    if len(cs) >= 3 and cs[:3].isalpha() and cs[:3] in OPERATORS and (len(cs) == 3 or cs[3:4].isdigit() or cs[3:4].isalpha()):
        code = cs[:3]
        name, country, cat = OPERATORS[code]
        return code, name, country, cat
    if cs and _MILITARY.match(cs):
        return "MIL", "Military / government", "US", "military"
    reg = (registration or cs or "").upper()
    if reg.startswith("N") and len(reg) > 1 and (reg[1:2].isdigit()):
        return "N", "General aviation (US registration)", "US", "ga"
    if reg.startswith(("C-", "CF", "CG")):
        return "C", "General aviation (Canada)", "CA", "ga"
    if reg.startswith(("XA", "XB", "XC")):
        return "X", "General aviation (Mexico)", "MX", "ga"
    if cs and cs[:3].isalpha():
        return cs[:3], f"Unknown operator {cs[:3]}", "?", "unknown"
    return "?", "Unidentified", "?", "unknown"
