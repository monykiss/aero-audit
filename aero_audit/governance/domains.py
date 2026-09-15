"""Domains: the parts of air and space navigation this programme covers, with an honest status.

``active`` means data flows and rules fire today; ``scaffold`` means the code path exists on
supplied inputs but no live source yet; ``planned`` means the standards and controls are named
and the integration is on the roadmap (docs/HOLISTIC_PLAN.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Domain:
    key: str
    name: str
    description: str
    status: str  # active | scaffold | planned
    data_sources: tuple[str, ...]
    rule_prefixes: tuple[str, ...]
    standards: tuple[str, ...]
    modules: tuple[str, ...]
    kpis: tuple[str, ...]
    upstream: tuple[str, ...] = ()  # open-source projects whose patterns or formats this domain adopts

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "description": self.description, "status": self.status,
                "data_sources": list(self.data_sources), "rule_prefixes": list(self.rule_prefixes),
                "standards": list(self.standards), "modules": list(self.modules), "kpis": list(self.kpis),
                "upstream": list(self.upstream)}


DOMAINS: dict[str, Domain] = {d.key: d for d in (
    Domain(
        "air-surveillance", "Air: surveillance integrity (ADS-B / Mode S)",
        "Every position report checked against physics, integrity fields, identity and stream health; "
        "cross-feed corroboration; trust ledger; measured detection recall.",
        "active",
        ("adsb.lol /v2 (readsb JSON, NIC/NACp/SIL)", "OpenSky Network states/all", "cross-feed corroboration"),
        ("SEC", "SAF", "ML"),
        ("ICAO-A10", "ICAO-A17", "ICAO-DOC9924", "RTCA-DO260B", "CFR14-91.227", "EU-1207-2011", "NIST-CSF-2", "NIST-SP800-53"),
        ("aero_audit/audit", "aero_audit/features", "aero_audit/ml", "aero_audit/security"),
        ("ADS-B integrity compliance rate", "critical+high findings per 1,000 aircraft", "recall by injected scenario",
         "median time-to-detect", "corroboration disagreement rate"),
        ("openskynetwork/opensky-api", "wiedehopf/readsb", "junzis/pyModeS", "xoolive/traffic"),
    ),
    Domain(
        "air-operations", "Air: operations, airports and ecosystem",
        "Flight phases, airports, operators, holding and its cost, level busts, coverage gaps, apron capacity, "
        "FAA programmes joined to live traffic.",
        "active",
        ("adsb.lol / OpenSky", "NOAA AWC METAR", "FAA NAS status XML", "bundled airport / operator / type tables", "apron imagery"),
        ("OPS", "OPS-VIS", "SAF"),
        ("ICAO-DOC4444", "ICAO-A11", "ICAO-A14", "CFR14-91.135", "ICAO-A6"),
        ("aero_audit/ecosystem.py", "aero_audit/knowledge", "aero_audit/impact.py", "aero_audit/vision"),
        ("holding minutes / fuel / CO2 / delay cost", "level-bust candidates", "coverage gaps", "apron occupancy vs capacity"),
        ("euctrl-pru/HexAeroPy", "euctrl-pru/trrrj", "OpenVSP/OpenVSP"),
    ),
    Domain(
        "space-assets", "Space: open assets with provenance",
        "NASA-3D-Resources catalogue with git-blob-verified fetch; NASA Image and Video Library search and "
        "download with SHA-256 manifests; licence text carried with every file.",
        "active",
        ("github.com/nasa/NASA-3D-Resources (tree API + raw)", "images-api.nasa.gov / images-assets.nasa.gov", "api.nasa.gov Mars Rover Photos (planned)"),
        (),
        ("NASA-NOSA-1.3", "NASA-MEDIA", "ODbL-1.0"),
        ("aero_audit/space/nasa3d.py", "aero_audit/space/nasa_images.py", "aero_audit/space/dataset.py", "aero_audit/space/classifier.py"),
        ("assets catalogued", "assets fetched with verified integrity", "manifest verification pass rate", "scene classifier validation accuracy"),
        ("nasa/NASA-3D-Resources", "NASA-AMMOS/3DTilesRendererJS", "NASA-AMMOS/MMGIS"),
    ),
    Domain(
        "space-launch", "Space: launch and ascent",
        "Launch telemetry plausibility (SPC rules), footage frames with hashed manifests, caption milestone "
        "timelines. Inputs are supplied files; no live telemetry source yet.",
        "scaffold",
        ("telemetry CSV (t, speed, altitude)", "local footage", "NASA library captions (.srt)"),
        ("SPC",),
        ("CCSDS-133", "CFR14-450", "NASA-NPR-8715.3", "NIST-SP800-53"),
        ("aero_audit/space/telemetry.py", "aero_audit/space/footage.py"),
        ("SPC findings per flight", "telemetry dropout seconds", "milestone timing vs published profile"),
        ("nasa/openmct", "nasa/hermes", "NASA-AMMOS/AIT-Core", "nasa/cFS (HS app)"),
    ),
    Domain(
        "space-orbital", "Space: orbital operations and conjunction",
        "Keyless CelesTrak elements, SGP4 screening with stale-element checks, CCSDS conjunction messages (KVN, XML) with covariance-based Pc, "
        "an inbox ledger with event trends, Space-Track public summaries, and the debris-mitigation checklist.",
        "active",
        ("CelesTrak GP elements (keyless)", "CCSDS CDM 508.0-B files (KVN / XML)", "space-track.org cdm_public (free account)", "mission descriptions (JSON)"),
        ("ORB", "DEB"),
        ("CCSDS-502", "CCSDS-508", "NASA-STD-8719.14", "ISO-24113", "CCSDS-355"),
        ("aero_audit/space/orbital.py", "aero_audit/space/cdm.py", "aero_audit/space/cdm_inbox.py", "aero_audit/space/spacetrack.py", "aero_audit/space/debris.py"),
        ("conjunctions screened per day", "Pc above threshold", "manoeuvre decisions with evidence", "debris rule compliance"),
        ("brandon-rhodes/python-sgp4", "skyfielders/python-skyfield", "nasa/GMAT", "open-space-collective/ccsds-data-messages", "nasa/CryptoLib"),
    ),
    Domain(
        "earth-crisis", "Earth observation: crisis overlays for operations",
        "Flood, fire and disaster extents from satellite products intersected with airports, routes and relief operations; "
        "NASA Ames Crisis Mapping Toolkit algorithms (MODIS, SAR, Landsat) as the reference, polygons supplied as GeoJSON.",
        "scaffold",
        ("GeoJSON crisis extents (from CMT / Earth Engine exports)", "bundled airport table"),
        (),
        ("NASA-NPR-8715.3", "ICAO-A11"),
        ("aero_audit/governance/studies.py",),
        ("airports inside a crisis extent", "hubs within N nm of an extent", "relief-flight coverage"),
        ("nasa/CrisisMappingToolkit", "NASA-AMMOS/MMGIS"),
    ),
    Domain(
        "uas-utm", "Air: UAS integration, detect-and-avoid, UTM",
        "Well-clear violations, alert levels and NMAC-proximate rates from the DAIDALUS / DO-365 definitions on recorded tracks; "
        "OpenAPI contract checks for UTM exchanges. Encounter-model risk classes are next.",
        "scaffold",
        ("surveillance recordings (ADS-B)", "UTM operator/USS APIs (OpenAPI)", "encounter models (planned)"),
        ("DAA",),
        ("ASTM-F3442", "RTCA-DO365", "ASTM-F3411", "ICAO-A2"),
        ("aero_audit/uas/wellclear.py", "aero_audit/uas/encounters.py", "aero_audit/uas/utm.py"),
        ("well-clear violation rate per flight hour", "alert lead time", "API conformance failures"),
        ("nasa/daidalus", "nasa/WellClear", "nasa/icarous", "nasa/utm-apis", "mit-ll/em-core", "mit-ll/air-risk-class"),
    ),
)}


__all__ = ["DOMAINS", "Domain"]
