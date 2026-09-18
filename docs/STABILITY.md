# Stability policy (1.0)

aero-audit follows semantic versioning from 1.0.0. The surfaces below are the contract: nothing in
them is removed or renamed in a 1.x release. Additions are allowed at any time. The snapshot is
`contracts/contract-1.0.json`; `aero gov contract --check` (and publication check PUB-13) fails on
any removal, and `tests/test_release_1_0.py` runs the same comparison in CI.

## Frozen surfaces

| Surface | What is frozen | Where it is enumerated |
|---|---|---|
| CLI | every command path (`aero space tfr`, `aero gov posture`, ...) and the meaning of its documented options; new options may appear with defaults that keep the old behaviour | `aero --help` tree |
| Rule ids | every rule id (air: SEC/OPS/SAF/VIS/ML; space and UAS: SPC/ORB/DEB/DAA/SWX/LCH/TFR/REN) and its category; thresholds may be tuned and the change noted in the changelog | `docs/generated/RULES.md` |
| API | every `METHOD /api/v1/...` route and the fields its responses carry today; new fields may be added | `/api/v1/openapi.json`, `docs/generated/API.md` |
| Jobs | job names accepted by `/api/v1/jobs`, `aero space watch` and `AERO_SCHEDULE` | `web/space_jobs.REGISTRY` |
| Studies and controls | ids ST-xx and C-xx; a study's runner may improve, its question does not change | `docs/generated/STUDIES.md`, `CONTROLS.md` |
| Playbooks | playbook ids (they are rule ids) | `docs/generated/PLAYBOOKS.md` |
| Environment variables | the documented names and their meaning | `docs/ACCOUNTS.md`, `.env.example` |
| Report envelope | the top-level keys of every generated report and the manifest beside it | `audit/generic_report.py` |
| Data layout | `data/recordings`, `data/samples`, `data/space/*`, `data/airspace`, `data/crisis`, `reports/`, `models/registry.json` | `docs/DATA_SOURCES.md` |

## What is not frozen

- Numbers: thresholds, model accuracies, benchmark figures and the posture index move with the evidence.
- Internal module layout under `aero_audit/` other than the public functions the CLI and API call.
- The HTML/JS of the local app (its routes and the API behind it are the contract, not the markup).
- Optional extras: `vision` (OpenCV, ultralytics, DracoPy) stays optional and its tests skip without it.

## Deprecation

A surface that must go is deprecated first: it keeps working for at least one minor release, prints
a warning naming the replacement, is listed under "Deprecated" in the changelog, and is removed only
in the next major version. The contract snapshot is retaken at each major version.

## Support matrix

Python 3.12 and 3.13; macOS and Linux (the CI runs Linux, the launch agent recipe is macOS);
Docker image from the repository's Dockerfile. Windows is untested.

## Security fixes

Security fixes ship as patch releases on the current minor version and are announced in
`SECURITY.md`'s advisory location; they never wait for a feature release.
