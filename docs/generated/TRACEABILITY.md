# Traceability matrix (generated)

Bidirectional traceability (NPR 7150.2 SWE-052 lineage): controls to standards, modules, rules, tests and studies; and back. Gaps are listed first because they are the actionable part.

| Coverage | Share |
|---|---|
| controls with tests | 100% |
| rules traced | 100% |
| studies traced | 100% |
| standards traced | 100% |

## Gaps

- **controls without tests**: none
- **implemented without module or command**: none
- **rules without control**: none
- **modules without control**: aero_audit/audit/generic_report.py, aero_audit/space/demo.py, aero_audit/space/donki.py, aero_audit/space/livecheck.py, aero_audit/space/mesh.py
- **studies without control**: none
- **standards without control**: none
- **test files missing**: none

## Controls

| Control | Status | Standards | Rules | Modules | Tests | Studies |
|---|---|---|---|---|---|---|
| C-01 Surveillance integrity minimums enforced | implemented | CFR14-91.227, RTCA-DO260B, EU-1207-2011 | SEC-012, SEC-013 | rules.py | test_rules.py | ST-01 |
| C-02 Kinematic plausibility of every position report | implemented | ICAO-DOC9924, ICAO-A10, RTCA-DO260B | SEC-010, SEC-011, SEC-014, SEC-018 | rules.py, tracks.py | test_rules.py, test_features.py | ST-02 |
| C-03 Emergency and unlawful-interference codes with confirmation tiers | implemented | ICAO-DOC4444, ICAO-A17, RTCA-DO260B | SEC-001, SEC-002, SEC-003, SEC-004 | rules.py, policy.py | test_rules.py, test_policy.py |  |
| C-04 Stream health: flooding and coverage collapse | implemented | ICAO-DOC9924, ICAO-A10 | SEC-016, SEC-017 | engine.py, poller.py | test_security.py |  |
| C-05 Cross-feed corroboration | implemented | ICAO-DOC9924 | SEC-015 | corroborate.py | test_security.py | ST-10 |
| C-06 Airspace and operations conformance | implemented | ICAO-DOC4444, ICAO-A11, CFR14-91.135, ICAO-A6 | OPS-001, OPS-002, OPS-003, OPS-004, OPS-005, SAF-003, SAF-004 | ecosystem.py | test_rules.py, test_ecosystem.py | ST-05 |
| C-07 Apron capacity from imagery | partial | ICAO-A14 | OPS-VIS-001, OPS-VIS-002 | apron.py, detect.py | test_vision_apron.py |  |
| C-08 Launch telemetry plausibility | partial | CCSDS-133, CFR14-450 | SPC-001, SPC-002, SPC-003, SPC-004, SPC-005 | telemetry.py, footage.py | test_space.py |  |
| C-09 Conjunction screening | partial | CCSDS-508, CCSDS-502 | ORB-001, ORB-002, ORB-003, ORB-004, ORB-005, ORB-006, ORB-007, ORB-008 | orbital.py, cdm.py, maneuvers.py, satcat.py, cdm_inbox.py, spacetrack.py | test_satcat.py, test_space_ops.py, test_depth.py, test_orbital.py, test_cdm.py | ST-20, ST-06, ST-12 |
| C-10 Debris mitigation compliance | partial | NASA-STD-8719.14, ISO-24113 | DEB-001, DEB-002, DEB-003, DEB-004, DEB-005, DEB-006, DEB-007, DEB-008 | debris.py | test_space_ops.py | ST-13 |
| C-11 UAS well-clear and DAA alerting metrics | partial | ASTM-F3442, RTCA-DO365, ICAO-A2 | DAA-001, DAA-002, DAA-003, DAA-004, DAA-005 | wellclear.py, encounters.py, risk.py, trend.py | test_uas.py, test_feeds_risk.py | ST-07, ST-16, ST-21 |
| C-12 UTM API conformance | partial | ASTM-F3411 |  | utm.py | test_uas.py | ST-09 |
| C-33 External asset integrity and provenance | implemented | NASA-NOSA-1.3, NASA-MEDIA |  | nasa3d.py, nasa_images.py | test_space.py |  |
| C-34 Crisis extent to operations impact | partial | NASA-NPR-8715.3, ICAO-A11 |  |  | test_governance.py | ST-11 |
| C-13 Threat catalogue with measured detection coverage | implemented | NIST-CSF-2, ICAO-A17 | SEC-020 | threats.py, watchlist.py, trust.py | test_security.py |  |
| C-14 Evidence-adjusted risk register | implemented | NIST-CSF-2, ICAO-A17 |  | register.py | test_risk.py |  |
| C-15 Unified air and space register | partial | NIST-CSF-2 |  | register.py | test_governance.py |  |
| C-16 Response playbooks with triage SLAs | implemented | NIST-SP800-53, ICAO-A17 |  | playbooks.py, alerts.py | test_security.py |  |
| C-17 Operational impact quantification | implemented | ICAO-A11 |  | impact.py | test_impact.py |  |
| C-18 Injected-scenario evaluation | implemented | NIST-AI-RMF |  |  | test_evaluate.py |  |
| C-19 Model card, registry and grouped holdout | implemented | NIST-AI-RMF | ML-001 | train.py, anomaly.py, evaluate.py | test_ml.py, test_security.py |  |
| C-20 Study registry with provenance | partial | NASA-SLIM |  | studies.py | test_governance.py | ST-03, ST-04 |
| C-21 Encounter and collision-risk modelling | partial | ASTM-F3442 |  | encounters.py, encounter_model.py | test_uas.py, test_depth.py | ST-08, ST-19 |
| C-22 Provenance and manifests on every report | implemented | NIST-SP800-53, ISO-27001 |  | provenance.py | test_provenance_and_tour.py |  |
| C-23 Hash-chained audit log | implemented | NIST-SP800-53, ISO-27001 |  | audit.py | test_audit_chain.py |  |
| C-24 Model integrity gate | implemented | NIST-SP800-53, NIST-AI-RMF |  | registry.py | test_model_registry.py |  |
| C-25 Local application hardening | implemented | NIST-SP800-53, ISO-27001 |  | security.py | test_app_security.py |  |
| C-26 Supply-chain assurance | implemented | NIST-SP800-53, NASA-SLIM |  |  | test_model_registry.py |  |
| C-27 Data retention | implemented | ISO-27001 |  |  | test_web.py |  |
| C-28 Licence and attribution tracking | implemented | ODbL-1.0, NASA-NOSA-1.3, NASA-MEDIA |  | nasa3d.py, nasa_images.py | test_space.py |  |
| C-29 Passive-only operating policy | implemented | ICAO-A17, CFR14-450 |  | poller.py | test_app_security.py |  |
| C-30 Threshold change control | implemented | ISO-27001, NIST-SP800-53 |  | tuning.py | test_tuning.py |  |
| C-35 Continuous monitoring of the platform itself | implemented | NIST-CSF-2, NIST-SP800-53, ISO-27001 |  | observability.py | test_observability.py |  |
| C-31 Software assurance classification | partial | NASA-NPR-7150.2, NASA-STD-8739.8, NASA-SLIM |  | assurance.py | test_assurance_catalog.py |  |
| C-32 Space data link security expectations | partial | CCSDS-355 |  | assurance.py | test_assurance_catalog.py |  |
| C-36 Data catalogue and reconciliation | implemented | NASA-SLIM, ISO-27001 |  | catalog.py | test_assurance_catalog.py | ST-15 |
| C-37 Training-data provenance and scene classifier | partial | NIST-AI-RMF, NASA-MEDIA |  | dataset.py, classifier.py, render.py | test_dataset_classifier.py, test_depth.py | ST-14 |
| C-38 Space weather watch | implemented | ICAO-A3, NOAA-SCALES | SWX-001, SWX-002, SWX-003, SWX-004, SWX-005 | spaceweather.py | test_feeds_risk.py | ST-17 |
| C-39 Launch-window airspace | implemented | CFR14-91.143 | LCH-001, LCH-002, LCH-003 | launches.py | test_feeds_risk.py | ST-18 |
| C-40 Scheduled intake | implemented | NASA-SLIM, NIST-CSF-2 |  | schedule.py, space_jobs.py | test_feeds_risk.py |  |
| C-41 Integration inventory | implemented | NIST-SP800-53, ISO-27001 |  | integrations.py | test_feeds_risk.py |  |
| C-42 Bidirectional traceability | implemented | NASA-NPR-7150.2, NASA-SLIM |  | traceability.py | test_depth.py |  |
| C-43 Publication readiness | implemented | NASA-NOSA-1.3, NASA-MEDIA, ODbL-1.0 |  | publish.py, status.py | test_publish_status.py |  |

## Rules to controls

| Rule | Controls |
|---|---|
| DAA-001 | C-11 |
| DAA-002 | C-11 |
| DAA-003 | C-11 |
| DAA-004 | C-11 |
| DAA-005 | C-11 |
| DEB-001 | C-10 |
| DEB-002 | C-10 |
| DEB-003 | C-10 |
| DEB-004 | C-10 |
| DEB-005 | C-10 |
| DEB-006 | C-10 |
| DEB-007 | C-10 |
| DEB-008 | C-10 |
| LCH-001 | C-39 |
| LCH-002 | C-39 |
| LCH-003 | C-39 |
| ML-001 | C-19 |
| OPS-001 | C-06 |
| OPS-002 | C-06 |
| OPS-003 | C-06 |
| OPS-004 | C-06 |
| OPS-005 | C-06 |
| OPS-VIS-001 | C-07 |
| OPS-VIS-002 | C-07 |
| ORB-001 | C-09 |
| ORB-002 | C-09 |
| ORB-003 | C-09 |
| ORB-004 | C-09 |
| ORB-005 | C-09 |
| ORB-006 | C-09 |
| ORB-007 | C-09 |
| ORB-008 | C-09 |
| SAF-003 | C-06 |
| SAF-004 | C-06 |
| SEC-001 | C-03 |
| SEC-002 | C-03 |
| SEC-003 | C-03 |
| SEC-004 | C-03 |
| SEC-010 | C-02 |
| SEC-011 | C-02 |
| SEC-012 | C-01 |
| SEC-013 | C-01 |
| SEC-014 | C-02 |
| SEC-015 | C-05 |
| SEC-016 | C-04 |
| SEC-017 | C-04 |
| SEC-018 | C-02 |
| SEC-020 | C-13 |
| SPC-001 | C-08 |
| SPC-002 | C-08 |
| SPC-003 | C-08 |
| SPC-004 | C-08 |
| SPC-005 | C-08 |
| SWX-001 | C-38 |
| SWX-002 | C-38 |
| SWX-003 | C-38 |
| SWX-004 | C-38 |
| SWX-005 | C-38 |

## Studies to controls

| Study | Controls |
|---|---|
| ST-01 | C-01 |
| ST-02 | C-02 |
| ST-03 | C-20 |
| ST-04 | C-20 |
| ST-05 | C-06 |
| ST-06 | C-09 |
| ST-07 | C-11 |
| ST-08 | C-21 |
| ST-09 | C-12 |
| ST-10 | C-05 |
| ST-11 | C-34 |
| ST-12 | C-09 |
| ST-13 | C-10 |
| ST-14 | C-37 |
| ST-15 | C-36 |
| ST-16 | C-11 |
| ST-17 | C-38 |
| ST-18 | C-39 |
| ST-19 | C-21 |
| ST-20 | C-09 |
| ST-21 | C-11 |
