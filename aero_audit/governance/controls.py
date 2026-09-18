"""Controls library with typed evidence, plus the policies that govern the programme.

A control's ``status`` is a claim; its ``evidence`` says where to look. Evidence strings are
typed by prefix so tooling can check them: ``rule:SEC-010`` (a rule id that must exist),
``test:tests/test_x.py``, ``artefact:reports/*.manifest.json``, ``command:aero log verify``,
``workflow:.github/workflows/ci.yml``, ``module:aero_audit/web/security.py``, ``doc:SECURITY.md``,
``scenario:teleport`` (an evaluation scenario), ``study:ST-01``.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain_rules import SPACE_RULE_CATALOG
from .domains import DOMAINS
from .standards import STANDARDS

PILLARS = ("compliance", "risk", "study", "governance")
STATUSES = ("implemented", "partial", "planned")
STATUS_EFFECTIVENESS = {"implemented": 0.6, "partial": 0.35, "planned": 0.0}  # same scale as threat coverage
SPACE_RULES = tuple(SPACE_RULE_CATALOG)  # every space / UAS rule id, with description and category, lives in domain_rules


@dataclass(frozen=True)
class Control:
    id: str
    title: str
    objective: str
    pillar: str
    domains: tuple[str, ...]
    standards: tuple[str, ...]
    status: str
    evidence: tuple[str, ...]
    owner: str = "programme lead"
    cadence_days: int = 90
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "objective": self.objective, "pillar": self.pillar,
                "domains": list(self.domains), "standards": list(self.standards), "status": self.status,
                "evidence": list(self.evidence), "owner": self.owner, "cadence_days": self.cadence_days, "notes": self.notes}


@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    statement: str
    owner: str
    controls: tuple[str, ...]
    review_days: int = 180

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "statement": self.statement, "owner": self.owner,
                "controls": list(self.controls), "review_days": self.review_days}


CONTROLS: dict[str, Control] = {c.id: c for c in (
    # ---- compliance ----------------------------------------------------------------------
    Control("C-01", "Surveillance integrity minimums enforced", "Flag airborne ADS-B fixes below NIC 7 / NACp 8 / SIL 3.",
            "compliance", ("air-surveillance",), ("CFR14-91.227", "RTCA-DO260B", "EU-1207-2011"), "implemented",
            ("rule:SEC-012", "rule:SEC-013", "module:aero_audit/audit/rules.py", "test:tests/test_rules.py", "scenario:integrity_degrade", "study:ST-01"), cadence_days=90),
    Control("C-02", "Kinematic plausibility of every position report", "Impossible jumps, speed and altitude physics, replayed fixes, ghosts.",
            "compliance", ("air-surveillance",), ("ICAO-DOC9924", "ICAO-A10", "RTCA-DO260B"), "implemented",
            ("rule:SEC-010", "rule:SEC-011", "rule:SEC-014", "rule:SEC-018", "module:aero_audit/audit/rules.py", "module:aero_audit/features/tracks.py", "test:tests/test_rules.py", "test:tests/test_features.py", "study:ST-02", "scenario:teleport", "scenario:velocity_forge",
             "scenario:altitude_forge", "scenario:replay", "artefact:models/evaluation.json")),
    Control("C-03", "Emergency and unlawful-interference codes with confirmation tiers", "7500/7600/7700 and the emergency subfield; single fix unconfirmed, second confirms.",
            "compliance", ("air-surveillance",), ("ICAO-DOC4444", "ICAO-A17", "RTCA-DO260B"), "implemented",
            ("rule:SEC-001", "rule:SEC-002", "rule:SEC-003", "rule:SEC-004", "module:aero_audit/audit/rules.py", "module:aero_audit/audit/policy.py", "scenario:squawk_hijack", "test:tests/test_rules.py", "test:tests/test_policy.py")),
    Control("C-04", "Stream health: flooding and coverage collapse", "Bursts of never-seen addresses and sudden loss of the picture.",
            "compliance", ("air-surveillance",), ("ICAO-DOC9924", "ICAO-A10"), "implemented", ("rule:SEC-016", "rule:SEC-017", "module:aero_audit/audit/engine.py", "module:aero_audit/stream/poller.py", "test:tests/test_security.py")),
    Control("C-05", "Cross-feed corroboration", "Dead-reckoned comparison of two independent feeds; disagreement is a finding.",
            "compliance", ("air-surveillance",), ("ICAO-DOC9924",), "implemented", ("rule:SEC-015", "module:aero_audit/security/corroborate.py", "command:aero corroborate", "test:tests/test_security.py", "study:ST-10"),
            notes="Needs two live feeds; the known gaps (perfect ghost, slow drift) close only here."),
    Control("C-06", "Airspace and operations conformance", "Holding, pattern work, level busts, VFR codes at altitude, coverage gaps, separation screen, vertical rates.",
            "compliance", ("air-operations", "air-surveillance"), ("ICAO-DOC4444", "ICAO-A11", "CFR14-91.135", "ICAO-A6"), "implemented",
            ("rule:OPS-001", "rule:OPS-002", "rule:OPS-003", "rule:OPS-004", "rule:OPS-005", "rule:SAF-003", "rule:SAF-004", "module:aero_audit/ecosystem.py", "test:tests/test_rules.py", "test:tests/test_ecosystem.py", "study:ST-05")),
    Control("C-07", "Apron capacity from imagery", "Zone occupancy against declared capacity from detections.",
            "compliance", ("air-operations",), ("ICAO-A14",), "partial", ("rule:OPS-VIS-001", "rule:OPS-VIS-002", "module:aero_audit/vision/apron.py", "module:aero_audit/vision/detect.py", "test:tests/test_vision_apron.py"),
            notes="COCO baseline finds 4 of 12 parked transports; fine-tuning on aerial datasets is the next ML task."),
    Control("C-08", "Launch telemetry plausibility", "Acceleration, altitude/speed consistency, dropouts, time regressions on a telemetry stream.",
            "compliance", ("space-launch",), ("CCSDS-133", "CFR14-450"), "implemented",
            ("rule:SPC-001", "rule:SPC-002", "rule:SPC-003", "rule:SPC-004", "rule:SPC-005", "module:aero_audit/space/telemetry.py", "module:aero_audit/space/footage.py", "test:tests/test_space.py", "test:tests/test_gap_fill.py", "command:aero space telemetry-audit", "command:aero space frames"),
            notes="Recorded telemetry (CSV or the public Telemetry-Data JSON); a real Falcon 9 ascent audits clean. No public live packet source exists; overlay OCR is not implemented."),
    Control("C-09", "Conjunction screening", "Propagate catalogued objects, screen close approaches, flag stale elements; probability of collision once CDMs with covariance are ingested.",
            "compliance", ("space-orbital",), ("CCSDS-508", "CCSDS-502"), "implemented",
            ("module:aero_audit/space/orbital.py", "module:aero_audit/space/cdm.py", "rule:ORB-001", "rule:ORB-002", "rule:ORB-003", "rule:ORB-004", "rule:ORB-005", "rule:ORB-006", "rule:ORB-007", "rule:ORB-008", "module:aero_audit/space/maneuvers.py", "module:aero_audit/space/satcat.py", "test:tests/test_satcat.py", "command:aero space satcat", "module:aero_audit/space/cdm_inbox.py", "module:aero_audit/space/spacetrack.py", "test:tests/test_space_ops.py", "test:tests/test_depth.py", "command:aero space maneuvers", "study:ST-20",
             "test:tests/test_orbital.py", "test:tests/test_cdm.py", "command:aero space conjunctions", "command:aero space cdm", "study:ST-06", "study:ST-12"),
            notes="Distance screen on CelesTrak elements via SGP4; Pc only from CDMs with covariance; inbox ledger with event trends; element history and SATCAT identity keyless. Space-Track optional."),
    Control("C-10", "Debris mitigation compliance", "Check mission parameters against disposal, passivation, lifetime, casualty-risk and trackability rules.",
            "compliance", ("space-orbital",), ("NASA-STD-8719.14", "ISO-24113"), "implemented",
            ("module:aero_audit/space/debris.py", "rule:DEB-001", "rule:DEB-002", "rule:DEB-003", "rule:DEB-004", "rule:DEB-005", "rule:DEB-006", "rule:DEB-007", "rule:DEB-008",
             "test:tests/test_space_ops.py", "command:aero space debris", "study:ST-13"),
            notes="Checklist with a simple decay-model lifetime estimate; not a certified orbital-lifetime analysis."),
    Control("C-11", "UAS well-clear and DAA alerting metrics", "Well-clear violations, NMAC-proximate encounters and alert lead time from the DO-365 / DAIDALUS definitions on recorded tracks.",
            "compliance", ("uas-utm", "air-surveillance"), ("ASTM-F3442", "RTCA-DO365", "ICAO-A2"), "implemented",
            ("module:aero_audit/uas/wellclear.py", "module:aero_audit/uas/encounters.py", "module:aero_audit/uas/risk.py", "rule:DAA-001", "rule:DAA-002", "rule:DAA-003", "rule:DAA-004",
             "test:tests/test_uas.py", "test:tests/test_feeds_risk.py", "module:aero_audit/uas/trend.py", "rule:DAA-005", "command:aero uas wellclear", "command:aero uas risk", "command:aero uas trend", "study:ST-07", "study:ST-16", "study:ST-21"),
            notes="Definitions re-implemented from DAIDALUS/DO-365 for offline metrics at surveillance update rates, with density classes, risk ratio, encounter model and trend; not a DAA system."),
    Control("C-12", "UTM API conformance", "Validate captured exchanges against OpenAPI contracts (NASA utm-apis, and this app's own document).",
            "compliance", ("uas-utm",), ("ASTM-F3411",), "implemented", ("module:aero_audit/uas/utm.py", "command:aero uas utm-fetch", "test:tests/test_gap_fill.py", "module:aero_audit/uas/utm.py", "test:tests/test_uas.py", "command:aero uas utm-check", "study:ST-09"), notes="Validated against NASA's real utm-apis contracts with external references resolved; captured exchanges are the user's to supply."),
    Control("C-33", "External asset integrity and provenance", "NASA-3D assets verified against git blob ids; library downloads hashed; sidecars and manifests.",
            "compliance", ("space-assets",), ("NASA-NOSA-1.3", "NASA-MEDIA"), "implemented",
            ("module:aero_audit/space/nasa3d.py", "module:aero_audit/space/nasa_images.py", "test:tests/test_space.py", "command:aero space fetch")),
    Control("C-34", "Crisis extent to operations impact", "Intersect satellite-derived crisis extents with airports and hubs; flag affected operations.",
            "compliance", ("earth-crisis", "air-operations"), ("NASA-NPR-8715.3", "ICAO-A11"), "implemented", ("module:aero_audit/ingest/nws_alerts.py", "command:aero data crisis-fetch", "test:tests/test_gap_fill.py", "study:ST-11", "test:tests/test_governance.py"),
            notes="Live NWS alert polygons and any GeoJSON extent; the flood algorithms themselves are not re-implemented; the relief-flight coverage study is still open."),
    # ---- risk ----------------------------------------------------------------------------
    Control("C-13", "Threat catalogue with measured detection coverage", "Twelve surveillance threats mapped to rules and evaluation scenarios.",
            "risk", ("air-surveillance",), ("NIST-CSF-2", "ICAO-A17"), "implemented", ("module:aero_audit/security/threats.py", "module:aero_audit/security/watchlist.py", "module:aero_audit/security/trust.py", "rule:SEC-020", "artefact:docs/generated/THREATS.md", "test:tests/test_security.py")),
    Control("C-14", "Evidence-adjusted risk register", "Precision-weighted hits per 1,000 aircraft at the Wilson lower bound move likelihood bands; residual from control effectiveness.",
            "risk", ("air-surveillance", "air-operations"), ("NIST-CSF-2", "ICAO-A17"), "implemented", ("module:aero_audit/risk/register.py", "command:aero risk assess", "test:tests/test_risk.py")),
    Control("C-15", "Unified air and space register", "One register across domains with residuals from control status where detectors do not exist yet.",
            "risk", ("air-surveillance", "space-launch", "space-orbital", "uas-utm"), ("NIST-CSF-2",), "implemented", ("module:aero_audit/governance/register.py", "command:aero gov risks", "test:tests/test_governance.py")),
    Control("C-16", "Response playbooks with triage SLAs", "Triage, verify, escalate, contain per rule.",
            "risk", ("air-surveillance", "air-operations"), ("NIST-SP800-53", "ICAO-A17"), "implemented", ("module:aero_audit/security/playbooks.py", "module:aero_audit/alerts.py", "artefact:docs/generated/PLAYBOOKS.md", "test:tests/test_security.py")),
    Control("C-17", "Operational impact quantification", "Holding minutes to fuel, CO2 and delay cost with stated assumptions.",
            "risk", ("air-operations",), ("ICAO-A11",), "implemented", ("module:aero_audit/impact.py", "command:aero impact", "test:tests/test_impact.py")),
    # ---- study ---------------------------------------------------------------------------
    Control("C-18", "Injected-scenario evaluation", "Recall, time-to-detect and per-rule precision on real traffic with eight attack scenarios; results weight scoring.",
            "study", ("air-surveillance",), ("NIST-AI-RMF",), "implemented", ("command:aero evaluate", "artefact:models/evaluation.json", "test:tests/test_evaluate.py")),
    Control("C-19", "Model card, registry and grouped holdout", "Every trained model documented, checksummed and evaluated on unseen aircraft.",
            "study", ("air-surveillance",), ("NIST-AI-RMF",), "implemented", ("artefact:models/kinematic_iforest.md", "module:aero_audit/ml/train.py", "module:aero_audit/ml/anomaly.py", "module:aero_audit/ml/evaluate.py", "rule:ML-001", "test:tests/test_ml.py", "test:tests/test_security.py")),
    Control("C-20", "Study registry with provenance", "Reproducible analyses with inputs, method, metrics and hashed outputs.",
            "study", ("air-surveillance", "air-operations", "space-assets", "space-launch"), ("NASA-SLIM",), "implemented", ("module:aero_audit/governance/studies.py", "command:aero gov run-study", "test:tests/test_governance.py", "study:ST-03", "study:ST-04")),
    Control("C-21", "Encounter and collision-risk modelling", "Encounter and NMAC-proximate rates per flight hour from recordings; risk classes (MIT LL lineage) still to come.",
            "study", ("uas-utm", "air-surveillance"), ("ASTM-F3442",), "implemented", ("module:aero_audit/uas/encounters.py", "module:aero_audit/uas/encounter_model.py", "test:tests/test_uas.py", "test:tests/test_depth.py", "command:aero uas encounter-model", "study:ST-08", "study:ST-19"), notes="Encounter rates, density classes, an empirical encounter model with Monte Carlo NMAC estimates and a trend across recordings; programme thresholds, not certification values."),
    # ---- governance ----------------------------------------------------------------------
    Control("C-22", "Provenance and manifests on every report", "Code commit, input hash, model hash, evaluation hash, threshold overrides; SHA-256 per file.",
            "governance", ("air-surveillance", "air-operations", "space-launch"), ("NIST-SP800-53", "ISO-27001"), "implemented",
            ("module:aero_audit/audit/generic_report.py", "test:tests/test_generic_report_demo.py", "module:aero_audit/provenance.py", "artefact:reports/*.manifest.json", "command:aero log verify-report", "test:tests/test_provenance_and_tour.py")),
    Control("C-23", "Hash-chained audit log", "Every action linked to the previous one; verification names the first broken line.",
            "governance", ("air-surveillance", "air-operations"), ("NIST-SP800-53", "ISO-27001"), "implemented",
            ("module:aero_audit/web/audit.py", "command:aero log verify", "test:tests/test_audit_chain.py")),
    Control("C-24", "Model integrity gate", "A model loads only when its SHA-256 matches the registry.",
            "governance", ("air-surveillance",), ("NIST-SP800-53", "NIST-AI-RMF"), "implemented", ("module:aero_audit/ml/registry.py", "test:tests/test_model_registry.py")),
    Control("C-25", "Local application hardening", "Host validation, CSRF token, Origin checks, CSP, path confinement, token mode beyond loopback.",
            "governance", ("air-surveillance", "air-operations"), ("NIST-SP800-53", "ISO-27001"), "implemented",
            ("module:aero_audit/web/security.py", "test:tests/test_app_security.py", "doc:SECURITY.md")),
    Control("C-26", "Supply-chain assurance", "Hash-pinned universal lock, pip-audit, gitleaks over history, CodeQL, actions pinned to SHAs, non-root container.",
            "governance", ("air-surveillance", "air-operations", "space-assets", "space-launch"), ("NIST-SP800-53", "NASA-SLIM"), "implemented",
            ("workflow:.github/workflows/ci.yml", "workflow:.github/workflows/codeql.yml", "artefact:requirements.lock.txt", "doc:SECURITY.md", "test:tests/test_model_registry.py")),
    Control("C-27", "Data retention", "Recordings pruned by age; state and outputs kept out of version control.",
            "governance", ("air-surveillance",), ("ISO-27001",), "implemented", ("command:aero data prune", "doc:SECURITY.md", "test:tests/test_web.py")),
    Control("C-28", "Licence and attribution tracking", "ODbL, NOSA and NASA media terms carried with data and in attribution files.",
            "governance", ("air-surveillance", "space-assets"), ("ODbL-1.0", "NASA-NOSA-1.3", "NASA-MEDIA"), "implemented",
            ("doc:data/samples/ATTRIBUTION.md", "module:aero_audit/space/nasa3d.py", "module:aero_audit/space/nasa_images.py", "test:tests/test_space.py")),
    Control("C-29", "Passive-only operating policy", "Receive and analyse only; never transmit or interact with aircraft, ATC, launch or spacecraft systems.",
            "governance", ("air-surveillance", "air-operations", "space-launch", "space-orbital", "uas-utm"), ("ICAO-A17", "CFR14-450"), "implemented",
            ("doc:SECURITY.md", "doc:CONTRIBUTING.md", "module:aero_audit/stream/poller.py", "test:tests/test_app_security.py")),
    Control("C-30", "Threshold change control", "Overrides live in aero.toml, are logged in the audit chain and stamped into every report's provenance.",
            "governance", ("air-surveillance", "air-operations"), ("ISO-27001", "NIST-SP800-53"), "implemented",
            ("module:aero_audit/tuning.py", "command:aero config show", "test:tests/test_tuning.py")),
    Control("C-35", "Continuous monitoring of the platform itself", "Metrics with Prometheus exposition, liveness and readiness probes, structured logs with request correlation, alert rules.",
            "governance", ("air-surveillance", "air-operations", "space-launch", "space-orbital"), ("NIST-CSF-2", "NIST-SP800-53", "ISO-27001"), "implemented",
            ("module:aero_audit/observability.py", "test:tests/test_observability.py", "command:aero obs health", "doc:docs/OBSERVABILITY.md", "artefact:ops/aero-rules.yml")),
    Control("C-31", "Software assurance classification", "Components classified per NPR 7150.2 with the activities each class implies; SLIM repository checklist evaluated on the tree.",
            "governance", ("space-launch", "space-orbital", "air-surveillance"), ("NASA-NPR-7150.2", "NASA-STD-8739.8", "NASA-SLIM"), "partial",
            ("module:aero_audit/governance/assurance.py", "test:tests/test_assurance_catalog.py", "command:aero gov assurance", "artefact:docs/generated/ASSURANCE.md"),
            notes="Classification and checklist exist; the class-C style peer reviews and traceability are not yet practised."),
    Control("C-32", "Space data link security expectations", "SDLS expectations stated for any spacecraft telemetry ingested; authentication status to be recorded per packet.",
            "governance", ("space-orbital", "space-launch"), ("CCSDS-355",), "partial", ("module:aero_audit/governance/assurance.py", "artefact:docs/generated/ASSURANCE.md", "test:tests/test_assurance_catalog.py"),
            notes="NASA CryptoLib is the reference implementation; the toolkit only consumes what such links deliver."),
    Control("C-36", "Data catalogue and reconciliation", "Every recording, report, study, asset, element set, CDM and model registered with hash, time bounds and provenance; drift reported.",
            "governance", ("air-surveillance", "air-operations", "space-assets", "space-launch", "space-orbital"), ("NASA-SLIM", "ISO-27001"), "implemented",
            ("module:aero_audit/governance/catalog.py", "test:tests/test_assurance_catalog.py", "command:aero data catalog", "study:ST-15")),
    Control("C-37", "Training-data provenance and scene classifier", "Datasets assembled with per-item hash, attribution and deterministic splits; scene classifier with card, registry entry and validation metrics.",
            "study", ("space-assets", "space-launch"), ("NIST-AI-RMF", "NASA-MEDIA"), "implemented",
            ("module:aero_audit/space/mesh.py", "test:tests/test_mesh_formats.py", "command:aero space classify-eval", "test:tests/test_gap_fill.py", "module:aero_audit/space/dataset.py", "module:aero_audit/space/classifier.py", "module:aero_audit/space/render.py", "test:tests/test_dataset_classifier.py", "test:tests/test_depth.py", "command:aero space classify-train", "command:aero space render", "study:ST-14"),
            notes="Hashed, attributed datasets with deterministic splits; histogram and YOLO classifiers with cards, registry entries and a de-duplicated second-source hold-out (56% top-1): implemented, not yet good enough to label reports."),
    Control("C-38", "Space weather watch", "NOAA scales and Kp fetched keyless, mapped to ICAO advisory conditions (GNSS, HF, radiation), stale products flagged, exposed high-latitude traffic listed.",
            "compliance", ("space-environment", "air-operations", "space-orbital"), ("ICAO-A3", "NOAA-SCALES"), "implemented",
            ("module:aero_audit/space/donki.py", "test:tests/test_accounts_donki.py", "module:aero_audit/space/spaceweather.py", "rule:SWX-001", "rule:SWX-002", "rule:SWX-003", "rule:SWX-004", "rule:SWX-005", "test:tests/test_feeds_risk.py",
             "command:aero space weather", "study:ST-17"), cadence_days=30),
    Control("C-39", "Launch-window airspace", "Launch windows and pads joined to observed traffic: aircraft inside the hazard radius during the window, stale launch records, coverage gaps.",
            "risk", ("space-launch", "air-operations"), ("CFR14-91.143",), "implemented",
            ("module:aero_audit/space/launches.py", "rule:LCH-001", "rule:LCH-002", "rule:LCH-003", "test:tests/test_feeds_risk.py", "command:aero space launches", "study:ST-18"),
            notes="Hazard radius is a programme default (50 nm); the NOTAM/TFR geometry is authoritative."),
    Control("C-40", "Scheduled intake", "CDM inbox, space weather, launch windows, conjunction screens and catalogue builds run on an interval as ordinary jobs, audited and counted; network jobs skipped offline.",
            "governance", ("space-orbital", "space-environment", "space-launch"), ("NASA-SLIM", "NIST-CSF-2"), "implemented",
            ("module:aero_audit/web/schedule.py", "module:aero_audit/web/space_jobs.py", "test:tests/test_feeds_risk.py", "command:aero space watch"), cadence_days=30),
    Control("C-41", "Integration inventory", "Every external service listed with what it unlocks, its keyless fallback and whether its credentials are present; values never printed; credentials only from the environment.",
            "governance", ("air-surveillance", "space-assets", "space-orbital", "space-environment", "space-launch"), ("NIST-SP800-53", "ISO-27001"), "implemented",
            ("module:aero_audit/space/livecheck.py", "command:aero space live-check", "test:tests/test_livecheck.py", "module:aero_audit/integrations.py", "test:tests/test_feeds_risk.py", "command:aero accounts", "doc:docs/ACCOUNTS.md")),
    Control("C-42", "Bidirectional traceability", "Controls traced to standards, rules, modules, tests and studies and back; gaps (untested controls, orphan rules, unreferenced studies) listed and kept at zero for rules, studies and standards.",
            "governance", ("air-surveillance", "air-operations", "space-assets", "space-launch", "space-orbital", "uas-utm", "space-environment"), ("NASA-NPR-7150.2", "NASA-SLIM"), "implemented",
            ("module:aero_audit/governance/traceability.py", "artefact:docs/generated/TRACEABILITY.md", "test:tests/test_depth.py", "command:aero gov traceability", "command:aero docs-build")),
    Control("C-44", "Periodic digest", "Every report of the last N days folded into one brief with a manifest: counts by kind, findings by rule and severity, worst findings, posture, live check, jobs, publication gate; runs as a scheduled job.",
            "governance", ("air-surveillance", "air-operations", "space-orbital", "space-environment", "space-launch", "uas-utm"), ("NASA-SLIM", "NIST-CSF-2"), "implemented",
            ("module:aero_audit/governance/digest.py", "test:tests/test_digest.py", "command:aero gov digest")),
    Control("C-43", "Publication readiness", "Mechanical checks before the private branch goes public: nothing private tracked, no secret-looking strings, every source attributed, generated docs fresh, library and traceability clean, optional deps declared, changelog and README complete; the licence item stays open until upstream answers.",
            "governance", ("space-assets", "space-launch", "space-orbital", "uas-utm", "space-environment"), ("NASA-NOSA-1.3", "NASA-MEDIA", "ODbL-1.0"), "implemented",
            ("module:aero_audit/space/demo.py", "command:aero space demo", "test:tests/test_generic_report_demo.py", "module:aero_audit/governance/publish.py", "module:aero_audit/governance/status.py", "artefact:docs/generated/STATUS.md", "test:tests/test_publish_status.py", "command:aero gov publish-check", "doc:docs/UPSTREAM.md")),
)}


POLICIES: tuple[Policy, ...] = (
    Policy("P-01", "Passive only", "The programme receives and analyses; it never transmits, commands, or interacts with aircraft, ATC, launch or spacecraft systems.", "programme lead", ("C-29",)),
    Policy("P-02", "Feed etiquette", "One poller per host, intervals of 12 s or more, 429-aware back-off; never load-test a public feed.", "data steward", ("C-27",)),
    Policy("P-03", "Retention and privacy", "Recordings default to 30-day retention; watchlist protect entries are honoured; nothing personal is derived beyond the broadcast.", "data steward", ("C-27", "C-28")),
    Policy("P-04", "Attribution", "Every external dataset or asset carries its licence text and attribution in code and in the tree.", "data steward", ("C-28", "C-33")),
    Policy("P-05", "Model release gate", "A model is used only with a card, a registry entry, a grouped-holdout evaluation and an injected-scenario evaluation.", "ML lead", ("C-18", "C-19", "C-24")),
    Policy("P-06", "Change control", "Main is protected; CI (lint, tests, docs drift, dependency audit, secret scan, container) must pass; generated docs cannot drift from code.", "programme lead", ("C-26", "C-30")),
    Policy("P-07", "Incident triage", "Findings follow their playbook SLAs; critical within 15 minutes, high within 60; ML alone never escalates.", "operations lead", ("C-16",)),
    Policy("P-08", "Private until upstream", "Space and UAS work stays on a local branch until licence questions are settled and an upstream home is agreed; `aero gov publish-check` must pass before the branch is pushed.", "programme lead", ("C-28", "C-31", "C-43")),
    Policy("P-10", "Observability", "Every deployment exposes /metrics, /healthz and /readyz; the Prometheus alert rules in ops/ are the minimum on-call set.", "operations lead", ("C-35",)),
    Policy("P-09", "Secrets", "No credentials in the tree, recordings, reports or the audit log; .env is ignored and scanned for in CI.", "security lead", ("C-26",)),
)


def validate() -> list[str]:
    """Referential integrity of the library; empty list means clean."""
    from ..audit.rules import RULE_CATALOG
    from ..ml.evaluate import SCENARIOS
    from .studies import STUDIES

    problems: list[str] = []
    for c in CONTROLS.values():
        if c.pillar not in PILLARS:
            problems.append(f"{c.id}: unknown pillar {c.pillar}")
        if c.status not in STATUSES:
            problems.append(f"{c.id}: unknown status {c.status}")
        for d in c.domains:
            if d not in DOMAINS:
                problems.append(f"{c.id}: unknown domain {d}")
        for s in c.standards:
            if s not in STANDARDS:
                problems.append(f"{c.id}: unknown standard {s}")
        if c.status == "implemented" and not c.evidence:
            problems.append(f"{c.id}: implemented without evidence")
        for e in c.evidence:
            kind, _, ref = e.partition(":")
            if kind == "rule" and ref not in RULE_CATALOG and ref not in SPACE_RULES:
                problems.append(f"{c.id}: unknown rule {ref}")
            elif kind == "scenario" and ref not in SCENARIOS:
                problems.append(f"{c.id}: unknown scenario {ref}")
            elif kind == "study" and ref not in STUDIES:
                problems.append(f"{c.id}: unknown study {ref}")
            elif kind in ("test", "module", "doc", "workflow") and not Path(ref).exists():
                problems.append(f"{c.id}: missing file {ref}")
            elif kind == "artefact" and "*" not in ref and not Path(ref).exists() and not ref.startswith("reports/"):
                problems.append(f"{c.id}: missing artefact {ref}")
            elif kind not in ("rule", "scenario", "study", "test", "module", "doc", "workflow", "artefact", "command"):
                problems.append(f"{c.id}: unknown evidence kind {kind}")
    for p in POLICIES:
        for cid in p.controls:
            if cid not in CONTROLS:
                problems.append(f"{p.id}: unknown control {cid}")
    return problems


def evidence_present(control: Control) -> dict[str, bool]:
    """Which file-backed evidence items exist on disk right now (rules, commands and studies are assumed present)."""
    out: dict[str, bool] = {}
    for e in control.evidence:
        kind, _, ref = e.partition(":")
        if kind in ("test", "module", "doc", "workflow"):
            out[e] = Path(ref).exists()
        elif kind == "artefact":
            if "*" in ref:
                folder, pat = ref.rsplit("/", 1)
                out[e] = any(fnmatch.fnmatch(p.name, pat) for p in Path(folder).glob("*")) if Path(folder).is_dir() else False
            else:
                out[e] = Path(ref).exists()
        else:
            out[e] = True
    return out


def coverage() -> dict[str, Any]:
    """Standards and domains by control status."""
    by_std: dict[str, dict[str, int]] = {s: {"implemented": 0, "partial": 0, "planned": 0} for s in STANDARDS}
    by_dom: dict[str, dict[str, int]] = {d: {"implemented": 0, "partial": 0, "planned": 0} for d in DOMAINS}
    by_pillar: dict[str, dict[str, int]] = {p: {"implemented": 0, "partial": 0, "planned": 0} for p in PILLARS}
    for c in CONTROLS.values():
        by_pillar[c.pillar][c.status] += 1
        for s in c.standards:
            by_std[s][c.status] += 1
        for d in c.domains:
            by_dom[d][c.status] += 1
    covered_standards = sum(1 for v in by_std.values() if v["implemented"] or v["partial"])
    return {"by_standard": by_std, "by_domain": by_dom, "by_pillar": by_pillar,
            "standards_total": len(STANDARDS), "standards_with_controls": covered_standards}


def implementation_index(controls: dict[str, Control] | None = None) -> float:
    cs = list((controls or CONTROLS).values())
    if not cs:
        return 0.0
    return round(sum({"implemented": 1.0, "partial": 0.5, "planned": 0.0}[c.status] for c in cs) / len(cs), 3)


def render_markdown() -> str:
    cov = coverage()
    head = (f"Implementation index: **{implementation_index():.0%}** over {len(CONTROLS)} controls; "
            f"{cov['standards_with_controls']} of {cov['standards_total']} standards have at least one implemented or partial control.")
    lines = ["# Controls library (generated)", "", head, ""]
    for pillar in PILLARS:
        lines += [f"## {pillar.title()}", "", "| Id | Control | Status | Domains | Standards | Evidence |", "|---|---|---|---|---|---|"]
        for c in CONTROLS.values():
            if c.pillar != pillar:
                continue
            lines.append(f"| {c.id} | {c.title} | {c.status} | {', '.join(c.domains)} | {', '.join(c.standards)} | {'; '.join(c.evidence) or '-'} |")
        lines.append("")
    lines += ["## Policies", "", "| Id | Policy | Statement | Owner | Controls |", "|---|---|---|---|---|"]
    lines += [f"| {p.id} | {p.title} | {p.statement} | {p.owner} | {', '.join(p.controls)} |" for p in POLICIES]
    lines += ["", "## Standards", "", "| Id | Standard | Body | Area | Implemented / partial / planned controls |", "|---|---|---|---|---|"]
    for s in STANDARDS.values():
        v = cov["by_standard"][s.id]
        lines.append(f"| {s.id} | {s.title} | {s.body} | {s.area} | {v['implemented']} / {v['partial']} / {v['planned']} |")
    return "\n".join(lines) + "\n"


__all__ = ["CONTROLS", "PILLARS", "POLICIES", "SPACE_RULES", "STATUSES", "STATUS_EFFECTIVENESS", "Control", "Policy",
           "coverage", "evidence_present", "implementation_index", "render_markdown", "validate"]
