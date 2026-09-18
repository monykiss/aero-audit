# Assurance reviews (generated)

9 of 9 components reviewed (0 peer, 9 self); open actions: 1; automatic checks 54/54. `aero gov reviews` says what is overdue today.

A self-review is recorded as such; it satisfies the cadence, not the independence NPR 7150.2 asks of a class C peer review. The automatic checks are evidence the tree proves; the reviewer still reads the code.

| Component | Class | Safety | Last review | Kind | Outcome | Cadence (days) | Next due | Checks |
|---|---|---|---|---|---|---|---|---|
| Rules engine and scoring | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Feed ingest and recording | D | no | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Anomaly model and evaluation | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Local app and API | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Space assets and footage | E | no | 2026-09-18 | self-review | accepted-with-actions | 180 | 2027-03-17 | 6/6 |
| Launch telemetry and orbital analysis | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| UAS well-clear metrics | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Launch and reentry airspace | D | yes | 2026-09-18 | self-review | accepted | 90 | 2026-12-17 | 6/6 |
| Governance layer | E | no | 2026-09-18 | self-review | accepted | 180 | 2027-03-17 | 6/6 |

## Open actions

- **Space assets and footage**: hand-curated labels and richer classes before the scene classifier labels a report

## Automatic checks per component

- **Rules engine and scoring**: ✓ tests import the component (1/1 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/audit)
- **Feed ingest and recording**: ✓ tests import the component (2/2 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/ingest)
- **Anomaly model and evaluation**: ✓ tests import the component (1/1 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/ml)
- **Local app and API**: ✓ tests import the component (1/1 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/web)
- **Space assets and footage**: ✓ tests import the component (5/5 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/space)
- **Launch telemetry and orbital analysis**: ✓ tests import the component (5/5 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/space)
- **UAS well-clear metrics**: ✓ tests import the component (1/1 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/uas)
- **Launch and reentry airspace**: ✓ tests import the component (5/5 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/ingest/tfr)
- **Governance layer**: ✓ tests import the component (1/1 module patterns found in tests/); ✓ lint configured (ruff) (pyproject.toml [tool.ruff]); ✓ static analysis in CI (CodeQL) (.github/workflows/codeql.yml); ✓ parsers fuzzed (fuzz/fuzz_targets.py (CI job)); ✓ modules traced to a control (no gaps); ✓ documented (docs/*.md mention aero_audit/governance)
