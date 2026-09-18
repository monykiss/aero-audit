# Controls library (generated)

Implementation index: **97%** over 47 controls; 36 of 36 standards have at least one implemented or partial control.

## Compliance

| Id | Control | Status | Domains | Standards | Evidence |
|---|---|---|---|---|---|
| C-01 | Surveillance integrity minimums enforced | implemented | air-surveillance | CFR14-91.227, RTCA-DO260B, EU-1207-2011 | rule:SEC-012; rule:SEC-013; module:aero_audit/audit/rules.py; test:tests/test_rules.py; scenario:integrity_degrade; study:ST-01 |
| C-02 | Kinematic plausibility of every position report | implemented | air-surveillance | ICAO-DOC9924, ICAO-A10, RTCA-DO260B | rule:SEC-010; rule:SEC-011; rule:SEC-014; rule:SEC-018; module:aero_audit/audit/rules.py; module:aero_audit/features/tracks.py; test:tests/test_rules.py; test:tests/test_features.py; study:ST-02; scenario:teleport; scenario:velocity_forge; scenario:altitude_forge; scenario:replay; artefact:models/evaluation.json |
| C-03 | Emergency and unlawful-interference codes with confirmation tiers | implemented | air-surveillance | ICAO-DOC4444, ICAO-A17, RTCA-DO260B | rule:SEC-001; rule:SEC-002; rule:SEC-003; rule:SEC-004; module:aero_audit/audit/rules.py; module:aero_audit/audit/policy.py; scenario:squawk_hijack; test:tests/test_rules.py; test:tests/test_policy.py |
| C-04 | Stream health: flooding and coverage collapse | implemented | air-surveillance | ICAO-DOC9924, ICAO-A10 | rule:SEC-016; rule:SEC-017; module:aero_audit/audit/engine.py; module:aero_audit/stream/poller.py; test:tests/test_security.py |
| C-05 | Cross-feed corroboration | implemented | air-surveillance | ICAO-DOC9924 | rule:SEC-015; module:aero_audit/security/corroborate.py; command:aero corroborate; test:tests/test_security.py; study:ST-10 |
| C-06 | Airspace and operations conformance | implemented | air-operations, air-surveillance | ICAO-DOC4444, ICAO-A11, CFR14-91.135, ICAO-A6 | rule:OPS-001; rule:OPS-002; rule:OPS-003; rule:OPS-004; rule:OPS-005; rule:SAF-003; rule:SAF-004; module:aero_audit/ecosystem.py; test:tests/test_rules.py; test:tests/test_ecosystem.py; study:ST-05 |
| C-07 | Apron capacity from imagery | partial | air-operations | ICAO-A14 | rule:OPS-VIS-001; rule:OPS-VIS-002; module:aero_audit/vision/apron.py; module:aero_audit/vision/detect.py; test:tests/test_vision_apron.py |
| C-08 | Launch telemetry plausibility | implemented | space-launch | CCSDS-133, CFR14-450 | rule:SPC-001; rule:SPC-002; rule:SPC-003; rule:SPC-004; rule:SPC-005; module:aero_audit/space/telemetry.py; module:aero_audit/space/footage.py; test:tests/test_space.py; test:tests/test_gap_fill.py; command:aero space telemetry-audit; command:aero space frames |
| C-09 | Conjunction screening | implemented | space-orbital | CCSDS-508, CCSDS-502 | module:aero_audit/space/orbital.py; module:aero_audit/space/cdm.py; rule:ORB-001; rule:ORB-002; rule:ORB-003; rule:ORB-004; rule:ORB-005; rule:ORB-006; rule:ORB-007; rule:ORB-008; module:aero_audit/space/maneuvers.py; module:aero_audit/space/satcat.py; test:tests/test_satcat.py; command:aero space satcat; module:aero_audit/space/cdm_inbox.py; module:aero_audit/space/spacetrack.py; test:tests/test_space_ops.py; test:tests/test_depth.py; command:aero space maneuvers; study:ST-20; test:tests/test_orbital.py; test:tests/test_cdm.py; command:aero space conjunctions; command:aero space cdm; study:ST-06; study:ST-12 |
| C-10 | Debris mitigation compliance | implemented | space-orbital | NASA-STD-8719.14, ISO-24113 | module:aero_audit/space/debris.py; rule:DEB-001; rule:DEB-002; rule:DEB-003; rule:DEB-004; rule:DEB-005; rule:DEB-006; rule:DEB-007; rule:DEB-008; test:tests/test_space_ops.py; command:aero space debris; study:ST-13 |
| C-11 | UAS well-clear and DAA alerting metrics | implemented | uas-utm, air-surveillance | ASTM-F3442, RTCA-DO365, ICAO-A2 | module:aero_audit/uas/wellclear.py; module:aero_audit/uas/encounters.py; module:aero_audit/uas/risk.py; rule:DAA-001; rule:DAA-002; rule:DAA-003; rule:DAA-004; test:tests/test_uas.py; test:tests/test_feeds_risk.py; module:aero_audit/uas/trend.py; rule:DAA-005; command:aero uas wellclear; command:aero uas risk; command:aero uas trend; study:ST-07; study:ST-16; study:ST-21 |
| C-12 | UTM API conformance | implemented | uas-utm | ASTM-F3411 | module:aero_audit/uas/utm.py; command:aero uas utm-fetch; test:tests/test_gap_fill.py; module:aero_audit/uas/utm.py; test:tests/test_uas.py; command:aero uas utm-check; study:ST-09 |
| C-33 | External asset integrity and provenance | implemented | space-assets | NASA-NOSA-1.3, NASA-MEDIA | module:aero_audit/space/nasa3d.py; module:aero_audit/space/nasa_images.py; test:tests/test_space.py; command:aero space fetch |
| C-34 | Crisis extent to operations impact | implemented | earth-crisis, air-operations | NASA-NPR-8715.3, ICAO-A11 | module:aero_audit/ingest/nws_alerts.py; command:aero data crisis-fetch; test:tests/test_gap_fill.py; study:ST-11; test:tests/test_governance.py |
| C-38 | Space weather watch | implemented | space-environment, air-operations, space-orbital | ICAO-A3, NOAA-SCALES | module:aero_audit/space/donki.py; test:tests/test_accounts_donki.py; module:aero_audit/space/spaceweather.py; rule:SWX-001; rule:SWX-002; rule:SWX-003; rule:SWX-004; rule:SWX-005; test:tests/test_feeds_risk.py; command:aero space weather; study:ST-17 |
| C-45 | Space-operations airspace joined to traffic | implemented | space-launch, air-operations | CFR14-91.143, CFR14-450, ICAO-A11 | rule:TFR-001; rule:TFR-002; rule:TFR-003; module:aero_audit/ingest/tfr.py; module:aero_audit/space/airspace.py; test:tests/test_airspace.py; command:aero space tfr; study:ST-22; doc:docs/SPACE.md |

## Risk

| Id | Control | Status | Domains | Standards | Evidence |
|---|---|---|---|---|---|
| C-13 | Threat catalogue with measured detection coverage | implemented | air-surveillance | NIST-CSF-2, ICAO-A17 | module:aero_audit/security/threats.py; module:aero_audit/security/watchlist.py; module:aero_audit/security/trust.py; rule:SEC-020; artefact:docs/generated/THREATS.md; test:tests/test_security.py |
| C-14 | Evidence-adjusted risk register | implemented | air-surveillance, air-operations | NIST-CSF-2, ICAO-A17 | module:aero_audit/risk/register.py; command:aero risk assess; test:tests/test_risk.py |
| C-15 | Unified air and space register | implemented | air-surveillance, space-launch, space-orbital, uas-utm | NIST-CSF-2 | module:aero_audit/governance/register.py; command:aero gov risks; test:tests/test_governance.py |
| C-16 | Response playbooks with triage SLAs | implemented | air-surveillance, air-operations | NIST-SP800-53, ICAO-A17 | module:aero_audit/security/playbooks.py; module:aero_audit/security/playbook_model.py; module:aero_audit/alerts.py; artefact:docs/generated/PLAYBOOKS.md; test:tests/test_security.py |
| C-17 | Operational impact quantification | implemented | air-operations | ICAO-A11 | module:aero_audit/impact.py; command:aero impact; test:tests/test_impact.py |
| C-39 | Launch-window airspace | implemented | space-launch, air-operations | CFR14-91.143 | module:aero_audit/space/launches.py; rule:LCH-001; rule:LCH-002; rule:LCH-003; test:tests/test_feeds_risk.py; command:aero space launches; study:ST-18 |
| C-46 | Reentry corridor watch | implemented | space-orbital, air-operations | CFR14-91.143, ICAO-DOC4444, NASA-STD-8719.14, CCSDS-502 | rule:REN-001; rule:REN-002; rule:REN-003; module:aero_audit/space/reentry.py; test:tests/test_airspace.py; command:aero space reentry; study:ST-23 |

## Study

| Id | Control | Status | Domains | Standards | Evidence |
|---|---|---|---|---|---|
| C-18 | Injected-scenario evaluation | implemented | air-surveillance | NIST-AI-RMF | command:aero evaluate; artefact:models/evaluation.json; test:tests/test_evaluate.py |
| C-19 | Model card, registry and grouped holdout | implemented | air-surveillance | NIST-AI-RMF | artefact:models/kinematic_iforest.md; module:aero_audit/ml/train.py; module:aero_audit/ml/anomaly.py; module:aero_audit/ml/evaluate.py; rule:ML-001; test:tests/test_ml.py; test:tests/test_security.py |
| C-20 | Study registry with provenance | implemented | air-surveillance, air-operations, space-assets, space-launch | NASA-SLIM | module:aero_audit/governance/studies.py; command:aero gov run-study; test:tests/test_governance.py; study:ST-03; study:ST-04 |
| C-21 | Encounter and collision-risk modelling | implemented | uas-utm, air-surveillance | ASTM-F3442 | module:aero_audit/uas/encounters.py; module:aero_audit/uas/encounter_model.py; test:tests/test_uas.py; test:tests/test_depth.py; command:aero uas encounter-model; study:ST-08; study:ST-19 |
| C-37 | Training-data provenance and scene classifier | implemented | space-assets, space-launch | NIST-AI-RMF, NASA-MEDIA | module:aero_audit/space/mesh.py; test:tests/test_mesh_formats.py; command:aero space classify-eval; test:tests/test_gap_fill.py; module:aero_audit/space/dataset.py; module:aero_audit/space/classifier.py; module:aero_audit/space/render.py; test:tests/test_dataset_classifier.py; test:tests/test_depth.py; command:aero space classify-train; command:aero space render; study:ST-14 |

## Governance

| Id | Control | Status | Domains | Standards | Evidence |
|---|---|---|---|---|---|
| C-22 | Provenance and manifests on every report | implemented | air-surveillance, air-operations, space-launch | NIST-SP800-53, ISO-27001 | module:aero_audit/audit/generic_report.py; test:tests/test_generic_report_demo.py; module:aero_audit/provenance.py; artefact:reports/*.manifest.json; command:aero log verify-report; test:tests/test_provenance_and_tour.py |
| C-23 | Hash-chained audit log | implemented | air-surveillance, air-operations | NIST-SP800-53, ISO-27001 | module:aero_audit/web/audit.py; command:aero log verify; test:tests/test_audit_chain.py |
| C-24 | Model integrity gate | implemented | air-surveillance | NIST-SP800-53, NIST-AI-RMF | module:aero_audit/ml/registry.py; test:tests/test_model_registry.py |
| C-25 | Local application hardening | implemented | air-surveillance, air-operations | NIST-SP800-53, ISO-27001 | module:aero_audit/web/security.py; test:tests/test_app_security.py; doc:SECURITY.md |
| C-26 | Supply-chain assurance | implemented | air-surveillance, air-operations, space-assets, space-launch | NIST-SP800-53, NASA-SLIM | workflow:.github/workflows/ci.yml; workflow:.github/workflows/codeql.yml; artefact:requirements.lock.txt; doc:SECURITY.md; test:tests/test_model_registry.py |
| C-27 | Data retention | implemented | air-surveillance | ISO-27001 | command:aero data prune; doc:SECURITY.md; test:tests/test_web.py |
| C-28 | Licence and attribution tracking | implemented | air-surveillance, space-assets | ODbL-1.0, NASA-NOSA-1.3, NASA-MEDIA | doc:data/samples/ATTRIBUTION.md; module:aero_audit/space/nasa3d.py; module:aero_audit/space/nasa_images.py; test:tests/test_space.py |
| C-29 | Passive-only operating policy | implemented | air-surveillance, air-operations, space-launch, space-orbital, uas-utm | ICAO-A17, CFR14-450 | doc:SECURITY.md; doc:CONTRIBUTING.md; module:aero_audit/stream/poller.py; test:tests/test_app_security.py |
| C-30 | Threshold change control | implemented | air-surveillance, air-operations | ISO-27001, NIST-SP800-53 | module:aero_audit/tuning.py; command:aero config show; test:tests/test_tuning.py |
| C-35 | Continuous monitoring of the platform itself | implemented | air-surveillance, air-operations, space-launch, space-orbital | NIST-CSF-2, NIST-SP800-53, ISO-27001 | module:aero_audit/observability.py; test:tests/test_observability.py; command:aero obs health; doc:docs/OBSERVABILITY.md; artefact:ops/aero-rules.yml |
| C-31 | Software assurance classification | partial | space-launch, space-orbital, air-surveillance | NASA-NPR-7150.2, NASA-STD-8739.8, NASA-SLIM | module:aero_audit/governance/assurance.py; test:tests/test_assurance_catalog.py; command:aero gov assurance; artefact:docs/generated/ASSURANCE.md |
| C-32 | Space data link security expectations | partial | space-orbital, space-launch | CCSDS-355 | module:aero_audit/governance/assurance.py; artefact:docs/generated/ASSURANCE.md; test:tests/test_assurance_catalog.py |
| C-36 | Data catalogue and reconciliation | implemented | air-surveillance, air-operations, space-assets, space-launch, space-orbital | NASA-SLIM, ISO-27001 | module:aero_audit/governance/catalog.py; test:tests/test_assurance_catalog.py; command:aero data catalog; study:ST-15 |
| C-40 | Scheduled intake | implemented | space-orbital, space-environment, space-launch | NASA-SLIM, NIST-CSF-2 | module:aero_audit/web/schedule.py; module:aero_audit/web/space_jobs.py; test:tests/test_feeds_risk.py; command:aero space watch |
| C-41 | Integration inventory | implemented | air-surveillance, space-assets, space-orbital, space-environment, space-launch | NIST-SP800-53, ISO-27001 | module:aero_audit/space/livecheck.py; command:aero space live-check; test:tests/test_livecheck.py; module:aero_audit/integrations.py; test:tests/test_feeds_risk.py; command:aero accounts; doc:docs/ACCOUNTS.md |
| C-42 | Bidirectional traceability | implemented | air-surveillance, air-operations, space-assets, space-launch, space-orbital, uas-utm, space-environment | NASA-NPR-7150.2, NASA-SLIM | module:aero_audit/governance/traceability.py; artefact:docs/generated/TRACEABILITY.md; test:tests/test_depth.py; command:aero gov traceability; command:aero docs-build |
| C-44 | Periodic digest | implemented | air-surveillance, air-operations, space-orbital, space-environment, space-launch, uas-utm | NASA-SLIM, NIST-CSF-2 | module:aero_audit/governance/digest.py; test:tests/test_digest.py; command:aero gov digest |
| C-43 | Publication readiness | implemented | space-assets, space-launch, space-orbital, uas-utm, space-environment | NASA-NOSA-1.3, NASA-MEDIA, ODbL-1.0 | module:aero_audit/space/demo.py; command:aero space demo; test:tests/test_generic_report_demo.py; module:aero_audit/governance/publish.py; module:aero_audit/governance/status.py; artefact:docs/generated/STATUS.md; test:tests/test_publish_status.py; command:aero gov publish-check; doc:docs/UPSTREAM.md |
| C-47 | Mission dossier | implemented | space-launch, air-operations, space-orbital, space-environment | CFR14-450, CFR14-91.143, NASA-SLIM | module:aero_audit/space/mission.py; module:aero_audit/knowledge/spaceports.py; test:tests/test_airspace.py; command:aero space mission; study:ST-24; doc:docs/SPACE.md |

## Policies

| Id | Policy | Statement | Owner | Controls |
|---|---|---|---|---|
| P-01 | Passive only | The programme receives and analyses; it never transmits, commands, or interacts with aircraft, ATC, launch or spacecraft systems. | programme lead | C-29 |
| P-02 | Feed etiquette | One poller per host, intervals of 12 s or more, 429-aware back-off; never load-test a public feed. | data steward | C-27 |
| P-03 | Retention and privacy | Recordings default to 30-day retention; watchlist protect entries are honoured; nothing personal is derived beyond the broadcast. | data steward | C-27, C-28 |
| P-04 | Attribution | Every external dataset or asset carries its licence text and attribution in code and in the tree. | data steward | C-28, C-33 |
| P-05 | Model release gate | A model is used only with a card, a registry entry, a grouped-holdout evaluation and an injected-scenario evaluation. | ML lead | C-18, C-19, C-24 |
| P-06 | Change control | Main is protected; CI (lint, tests, docs drift, dependency audit, secret scan, container) must pass; generated docs cannot drift from code. | programme lead | C-26, C-30 |
| P-07 | Incident triage | Findings follow their playbook SLAs; critical within 15 minutes, high within 60; ML alone never escalates. | operations lead | C-16 |
| P-08 | Private until upstream | Space and UAS work stays on a local branch until licence questions are settled and an upstream home is agreed; `aero gov publish-check` must pass before the branch is pushed. | programme lead | C-28, C-31, C-43 |
| P-10 | Observability | Every deployment exposes /metrics, /healthz and /readyz; the Prometheus alert rules in ops/ are the minimum on-call set. | operations lead | C-35 |
| P-09 | Secrets | No credentials in the tree, recordings, reports or the audit log; .env is ignored and scanned for in CI. | security lead | C-26 |

## Standards

| Id | Standard | Body | Area | Implemented / partial / planned controls |
|---|---|---|---|---|
| ICAO-A2 | ICAO Annex 2, Rules of the Air | ICAO | air | 1 / 0 / 0 |
| ICAO-A6 | ICAO Annex 6, Operation of Aircraft | ICAO | air | 1 / 0 / 0 |
| ICAO-A10 | ICAO Annex 10 Vol III/IV, Aeronautical Telecommunications | ICAO | air | 2 / 0 / 0 |
| ICAO-A11 | ICAO Annex 11, Air Traffic Services | ICAO | air | 4 / 0 / 0 |
| ICAO-A14 | ICAO Annex 14, Aerodromes | ICAO | air | 0 / 1 / 0 |
| ICAO-A17 | ICAO Annex 17, Security | ICAO | air | 5 / 0 / 0 |
| ICAO-DOC4444 | ICAO Doc 4444 PANS-ATM | ICAO | air | 3 / 0 / 0 |
| ICAO-DOC9924 | ICAO Doc 9924, Aeronautical Surveillance Manual | ICAO | air | 3 / 0 / 0 |
| RTCA-DO260B | RTCA DO-260B, 1090ES ADS-B MOPS | RTCA | air | 3 / 0 / 0 |
| RTCA-DO365 | RTCA DO-365, DAA MOPS for UAS | RTCA | air | 1 / 0 / 0 |
| CFR14-91.227 | 14 CFR 91.227 ADS-B Out performance | FAA | air | 1 / 0 / 0 |
| CFR14-91.135 | 14 CFR 91.135 Class A operations | FAA | air | 1 / 0 / 0 |
| CFR14-91.143 | 14 CFR 91.143 Flight limitation in the proximity of space flight operations | FAA | air | 4 / 0 / 0 |
| ICAO-A3 | ICAO Annex 3, Meteorological Service (space weather advisories, Amdt 78+) | ICAO | air | 1 / 0 / 0 |
| NOAA-SCALES | NOAA Space Weather Scales (R / S / G) | NOAA SWPC | space | 1 / 0 / 0 |
| EU-1207-2011 | EU Regulation 1207/2011 (SPI IR) as amended | EU | air | 1 / 0 / 0 |
| ASTM-F3411 | ASTM F3411, Remote ID and Tracking | ASTM | air | 1 / 0 / 0 |
| ASTM-F3442 | ASTM F3442/F3442M, DAA performance for smaller UAS | ASTM | air | 2 / 0 / 0 |
| CFR14-450 | 14 CFR Part 450, Launch and Reentry Licensing | FAA AST | space | 4 / 0 / 0 |
| CCSDS-133 | CCSDS 133.0-B, Space Packet Protocol | CCSDS | space | 1 / 0 / 0 |
| CCSDS-502 | CCSDS 502.0-B, Orbit Data Messages | CCSDS | space | 2 / 0 / 0 |
| CCSDS-508 | CCSDS 508.0-B, Conjunction Data Message | CCSDS | space | 1 / 0 / 0 |
| CCSDS-355 | CCSDS 355.0-B, Space Data Link Security | CCSDS | space | 0 / 1 / 0 |
| NASA-NPR-8715.3 | NASA NPR 8715.3, General Safety Program Requirements | NASA | space | 1 / 0 / 0 |
| NASA-STD-8719.14 | NASA-STD-8719.14, Limiting Orbital Debris | NASA | space | 2 / 0 / 0 |
| ISO-24113 | ISO 24113, Space debris mitigation requirements | ISO | space | 1 / 0 / 0 |
| NASA-NPR-7150.2 | NASA NPR 7150.2, Software Engineering Requirements | NASA | software | 1 / 1 / 0 |
| NASA-STD-8739.8 | NASA-STD-8739.8, Software Assurance and Safety | NASA | software | 0 / 1 / 0 |
| NASA-SLIM | NASA-AMMOS SLIM best-practice guides | NASA AMMOS | software | 7 / 1 / 0 |
| NIST-CSF-2 | NIST Cybersecurity Framework 2.0 | NIST | cyber | 6 / 0 / 0 |
| NIST-SP800-53 | NIST SP 800-53 r5 | NIST | cyber | 9 / 0 / 0 |
| ISO-27001 | ISO/IEC 27001:2022 Annex A | ISO | cyber | 8 / 0 / 0 |
| NIST-AI-RMF | NIST AI Risk Management Framework 1.0 | NIST | cyber | 4 / 0 / 0 |
| ODbL-1.0 | Open Database License 1.0 | ODC | data | 2 / 0 / 0 |
| NASA-NOSA-1.3 | NASA Open Source Agreement 1.3 | NASA | data | 3 / 0 / 0 |
| NASA-MEDIA | NASA media usage guidelines | NASA | data | 4 / 0 / 0 |
