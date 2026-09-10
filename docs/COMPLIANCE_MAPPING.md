# Compliance and framework mapping

The toolkit is an evidence generator. This table shows which control families each part of it
supports so an auditor can cite it in an assessment. It does not claim certification.

## Aviation-specific

| Framework / regulation | Relevant content | Toolkit support |
|---|---|---|
| ICAO Annex 17 (Security) | Security programme, threat assessment, detection of unlawful interference | Threat catalog, risk register, SEC-003 / SEC-004, playbooks |
| ICAO Doc 8973 (Aviation Security Manual) | Risk assessment methodology | 5x5 register with evidence adjustment |
| ICAO Doc 4444 PANS-ATM | Emergency codes 7500/7600/7700, holding, level busts | SEC-001..003, OPS-002, OPS-004 |
| ICAO Doc 9924 (Aeronautical Surveillance Manual) | Surveillance integrity and coverage | SEC-015/016/017, OPS-001 |
| ICAO Annex 10 Vol III / IV | 24-bit address allocation; surveillance systems | SEC-014, SEC-017 |
| ICAO Annex 14 / A-CDM | Apron management, stand utilisation KPIs | OPS-VIS-001/002 |
| RTCA DO-260B (ADS-B MOPS) | NIC/NACp/SIL semantics, emergency status subfield, message consistency | SEC-004, SEC-011, SEC-012 |
| 14 CFR 91.227(c) | ADS-B Out performance (NACp >= 8, NIC >= 7, SIL 3) | SEC-012 thresholds |
| 14 CFR 91.135 / AIM 4-1-20 | Class A transponder code requirements | OPS-005 |
| FAA AC 20-165B / AC 90-114 | ADS-B Out installation and operations | SEC-010, SEC-013 |
| EU 1207/2011 (SPI IR) as amended | European ADS-B Out performance | SEC-012 (thresholds comparable) |

## Cyber and risk frameworks

| Framework | Function / control | Toolkit support |
|---|---|---|
| NIST CSF 2.0 | GV.RM (risk management strategy) | `docs/RISK_REGISTER`, `aero risk assess` |
| | ID.RA (risk assessment) | Threat catalog, evidence-adjusted likelihoods |
| | DE.CM (continuous monitoring), DE.AE (adverse event analysis) | Live audit, stream checks, alerts, explainable findings |
| | RS.MA / RS.AN (incident management, analysis) | Playbooks with triage SLAs, JSONL alert log, replayable recordings |
| NIST SP 800-53 r5 | AU-6 (audit review), AU-12 (audit generation) | JSON/Markdown/HTML reports with evidence; hash-chained app audit log (`aero log verify`) |
| | AU-9 (protection of audit information), AU-10 (non-repudiation) | Tamper-evident audit chain; report manifests with SHA-256 per file and provenance (`aero log verify-report`) |
| | CM-14 (signed components), SI-7 (software and information integrity) | Models load only on a registry SHA-256 match; dependencies installed with `--require-hashes`; actions pinned to commit SHAs |
| | SC-7 (boundary protection), AC-3 (access enforcement) | App bound to loopback by default; token required for any other bind; Host, Origin and CSRF checks; path confinement |
| | SI-4 (system monitoring), SI-7 (integrity) | SEC-010/011/012/015 |
| | IR-4 / IR-5 (incident handling / monitoring) | Playbooks, alert sinks |
| | SA-11 / SR-3 / SR-4 (developer testing, supply chain, provenance) | Offline test suite incl. security tests, hash-pinned universal lock, `pip-audit`, gitleaks, CodeQL, Dependabot, `SECURITY.md` |
| ISO/IEC 27001:2022 Annex A | A.5.7 threat intelligence | Threat catalog |
| | A.8.15 logging, A.8.9 configuration management | Hash-chained audit log; `aero.toml` overrides recorded in every report's provenance |
| | A.8.28 secure coding, A.5.21 ICT supply chain | CSP without inline script, path confinement, CodeQL; hash-verified dependencies |
| | A.8.16 monitoring activities | Live audit + alerts |
| | A.5.30 ICT readiness | Two-feed fallback, coverage-collapse detection |
| NIST AI RMF 1.0 | MAP (context), MEASURE (evaluate), MANAGE (monitor) | Model card with holdout evaluation, ML-001 explanations, "never escalate on ML alone" playbook |
| MITRE ATT&CK-style tactics (adapted) | injection / modification / deletion / misuse | `tactic` field on each threat |

## Evidence an auditor can collect from this toolkit

1. `reports/*.json`: findings with rule id, evidence, control references, risk score, trust.
2. `data/recordings/*.jsonl`: raw batches enabling independent re-audit.
3. `models/*.md`: model cards with training window, features, altitude bands, holdout flag rates.
4. `models/registry.json`: provenance for every trained model (data files, rows, sha256, metrics);
   the same hash gates loading.
5. `models/evaluation.json` and `reports/evaluation_*.md`: injected-scenario recall, time-to-detect,
   and per-rule precision on real traffic, i.e. measured detective-control effectiveness.
6. `reports/risk_assessment_*.md`: register with precision-weighted evidence, Wilson lower-bound
   rates, inherent and residual scores, heat map.
7. `docs/generated/THREATS.md`: threat catalog with measured recall per threat.
8. `aero.toml` + `aero config show`: the effective thresholds in force for an audit.
9. `tests/`: regression suite proving injected anomalies remain detectable and the app's
   security controls hold (rebinding, CSRF, path confinement, token mode).
10. `data/app/audit.jsonl` + `aero log verify`: who did what to the picture, hash-chained.
11. `reports/*.manifest.json` + `aero log verify-report`: SHA-256 of every report file plus the
    code commit, input hash, model hash and registry status behind it.
