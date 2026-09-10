# Convenience targets. `make setup` then `make demo` is the whole onboarding.
VENV ?= .venv
PY   := $(VENV)/bin/python
AERO := $(VENV)/bin/aero

.PHONY: help setup demo app doctor test lint audit lock docs docker docker-run clean

help:
	@echo "make setup       create .venv and install hash-pinned dependencies (no demo)"
	@echo "make demo        offline demo: bundled sample + scripted attack tour, opens the browser"
	@echo "make app         the app with no source running"
	@echo "make doctor      environment, integrity and feed checks"
	@echo "make test        pytest (offline)"
	@echo "make lint        ruff"
	@echo "make audit       pip-audit against the lock file"
	@echo "make lock        regenerate requirements.lock.txt with hashes (needs network)"
	@echo "make docs        regenerate docs/generated from code"
	@echo "make docker      build the container image"
	@echo "make docker-run  run the demo in a container, port published on loopback only"

setup:
	scripts/bootstrap.sh --no-demo

demo:
	$(AERO) demo

app:
	$(AERO) app

doctor:
	$(AERO) doctor

test:
	$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check aero_audit tests

audit:
	uvx pip-audit -r requirements.lock.txt --strict --desc on

lock:
	uv pip compile --universal --generate-hashes --extra dev --python-version 3.12 -o requirements.lock.txt pyproject.toml

docs:
	$(AERO) docs-build

docker:
	docker build -t aero-audit:local .

docker-run:
	docker run --rm -p 127.0.0.1:8787:8787 --name aero-audit aero-audit:local

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
