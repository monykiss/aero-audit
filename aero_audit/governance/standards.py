"""Standards library: the regulations, standards and licences the controls map to, across air,
space, cyber, software assurance and data. Pointers for auditors, not legal determinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Standard:
    id: str
    title: str
    body: str  # issuing organisation
    area: str  # air | space | cyber | software | data
    scope: str
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "body": self.body, "area": self.area, "scope": self.scope, "url": self.url}


STANDARDS: dict[str, Standard] = {s.id: s for s in (
    # air
    Standard("ICAO-A2", "ICAO Annex 2, Rules of the Air", "ICAO", "air", "General flight rules; basis for UAS integration rules"),
    Standard("ICAO-A6", "ICAO Annex 6, Operation of Aircraft", "ICAO", "air", "Flight data monitoring, operational limits (vertical rates)"),
    Standard("ICAO-A10", "ICAO Annex 10 Vol III/IV, Aeronautical Telecommunications", "ICAO", "air", "24-bit address allocation, surveillance systems"),
    Standard("ICAO-A11", "ICAO Annex 11, Air Traffic Services", "ICAO", "air", "Separation, holding, ATS coordination"),
    Standard("ICAO-A14", "ICAO Annex 14, Aerodromes", "ICAO", "air", "Apron management, stand capacity"),
    Standard("ICAO-A17", "ICAO Annex 17, Security", "ICAO", "air", "Security programme, threat assessment, unlawful interference"),
    Standard("ICAO-DOC4444", "ICAO Doc 4444 PANS-ATM", "ICAO", "air", "Emergency codes 7500/7600/7700, holding, level busts"),
    Standard("ICAO-DOC9924", "ICAO Doc 9924, Aeronautical Surveillance Manual", "ICAO", "air", "Surveillance integrity, coverage, corroboration"),
    Standard("RTCA-DO260B", "RTCA DO-260B, 1090ES ADS-B MOPS", "RTCA", "air", "NIC/NACp/SIL semantics, emergency subfield, message consistency"),
    Standard("RTCA-DO365", "RTCA DO-365, DAA MOPS for UAS", "RTCA", "air", "Detect-and-avoid performance, well-clear alerting"),
    Standard("CFR14-91.227", "14 CFR 91.227 ADS-B Out performance", "FAA", "air", "NACp >= 8, NIC >= 7, SIL 3 in rule airspace", "https://www.ecfr.gov/current/title-14/section-91.227"),
    Standard("CFR14-91.135", "14 CFR 91.135 Class A operations", "FAA", "air", "Transponder code discipline above FL180", "https://www.ecfr.gov/current/title-14/section-91.135"),
    Standard("EU-1207-2011", "EU Regulation 1207/2011 (SPI IR) as amended", "EU", "air", "European ADS-B Out performance"),
    Standard("ASTM-F3411", "ASTM F3411, Remote ID and Tracking", "ASTM", "air", "UAS remote identification message content"),
    Standard("ASTM-F3442", "ASTM F3442/F3442M, DAA performance for smaller UAS", "ASTM", "air", "Well-clear definitions and DAA performance (NASA WellClear lineage)"),
    # space
    Standard("CFR14-450", "14 CFR Part 450, Launch and Reentry Licensing", "FAA AST", "space", "Flight safety analysis, telemetry, flight abort rules", "https://www.ecfr.gov/current/title-14/part-450"),
    Standard("CCSDS-133", "CCSDS 133.0-B, Space Packet Protocol", "CCSDS", "space", "Packet structure and sequencing for telemetry/command"),
    Standard("CCSDS-502", "CCSDS 502.0-B, Orbit Data Messages", "CCSDS", "space", "OPM/OMM/OEM orbit state exchange"),
    Standard("CCSDS-508", "CCSDS 508.0-B, Conjunction Data Message", "CCSDS", "space", "Conjunction assessment message exchange"),
    Standard("CCSDS-355", "CCSDS 355.0-B, Space Data Link Security", "CCSDS", "space", "Link-layer security for space data (NASA CryptoLib implements)"),
    Standard("NASA-NPR-8715.3", "NASA NPR 8715.3, General Safety Program Requirements", "NASA", "space", "Safety programme, hazard analysis"),
    Standard("NASA-STD-8719.14", "NASA-STD-8719.14, Limiting Orbital Debris", "NASA", "space", "Debris assessment and mitigation requirements"),
    Standard("ISO-24113", "ISO 24113, Space debris mitigation requirements", "ISO", "space", "Disposal, passivation, collision avoidance"),
    # software assurance
    Standard("NASA-NPR-7150.2", "NASA NPR 7150.2, Software Engineering Requirements", "NASA", "software", "Software classification, assurance, configuration management"),
    Standard("NASA-STD-8739.8", "NASA-STD-8739.8, Software Assurance and Safety", "NASA", "software", "Software assurance activities per class"),
    Standard("NASA-SLIM", "NASA-AMMOS SLIM best-practice guides", "NASA AMMOS", "software", "Repository hygiene, security, CI, documentation templates", "https://nasa-ammos.github.io/slim/"),
    # cyber and risk
    Standard("NIST-CSF-2", "NIST Cybersecurity Framework 2.0", "NIST", "cyber", "Govern, Identify, Protect, Detect, Respond, Recover"),
    Standard("NIST-SP800-53", "NIST SP 800-53 r5", "NIST", "cyber", "Security and privacy controls (AU, SI, SC, SA, SR, IR families)"),
    Standard("ISO-27001", "ISO/IEC 27001:2022 Annex A", "ISO", "cyber", "Information security controls"),
    Standard("NIST-AI-RMF", "NIST AI Risk Management Framework 1.0", "NIST", "cyber", "Map, Measure, Manage, Govern for AI systems"),
    # data and licences
    Standard("ODbL-1.0", "Open Database License 1.0", "ODC", "data", "Attribution and share-alike for adsb.lol data"),
    Standard("NASA-NOSA-1.3", "NASA Open Source Agreement 1.3", "NASA", "data", "Licence stated for NASA-3D-Resources"),
    Standard("NASA-MEDIA", "NASA media usage guidelines", "NASA", "data", "Insignia, endorsement and identifiable-people rules for NASA imagery", "https://www.nasa.gov/nasa-brand-center/images-and-media"),
)}


__all__ = ["STANDARDS", "Standard"]
