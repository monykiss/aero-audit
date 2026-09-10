# Contributing

Thanks for looking. This is a single-maintainer portfolio project, but issues and pull requests
are welcome, especially new detection rules with evidence, feed adapters, and evaluation scenarios.

## Setup

```bash
scripts/bootstrap.sh --no-demo      # .venv with hash-verified dependencies, then `aero doctor`
make test                            # pytest, fully offline
make lint                            # ruff
.venv/bin/aero docs-build            # regenerate docs/generated (CI fails if it is stale)
```

`make demo` runs the bundled sample with the scripted attack tour; `make app` starts the app empty.

## Ground rules

- **Evidence first.** A new rule needs a scenario in `aero_audit/ml/evaluate.py` (or a test on a
  recording) that shows recall and false-positive behaviour. Numbers in docs come from `aero evaluate`.
- **Feeds are shared.** One poller per host, intervals of 12 s or more against adsb.lol; never
  run load against a public feed to "test" anything.
- **Passive only.** Nothing in this repository transmits, connects to aircraft, ATC, or airline
  systems, or attempts to influence any of them. Pull requests that do will be closed.
- **Secrets never enter the tree.** `.env` is ignored; CI runs gitleaks over every push. Recordings,
  reports, model pickles and app state are ignored too.
- **Dependencies are pinned with hashes.** Change `pyproject.toml`, then `make lock` (needs network),
  and commit both. CI installs with `--require-hashes` and runs `pip-audit` (via `uvx`).
- **Docs are generated where they can be.** Threat matrix, playbooks, register and rule list come from
  code via `aero docs-build`; edit the source, not the generated file.

## Style

Python 3.12, ruff-clean, type hints on public functions, docstrings that say *why*. Keep the
front end dependency-free (vanilla JS, vendored Leaflet). Tests live in `tests/` and must run
without network access.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please do not open public issues for vulnerabilities.
