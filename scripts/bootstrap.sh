#!/usr/bin/env bash
# One-command local setup for macOS / Linux: hash-verified dependencies, a health check, then the demo.
#
#   scripts/bootstrap.sh            # set up, check, and open the demo in your browser
#   scripts/bootstrap.sh --no-demo  # set up and check only
#
# Needs Python 3.12+ (or `uv`, which will fetch one). Nothing is installed outside ./.venv.
# Every third-party package is verified against the SHA-256 hashes in requirements.lock.txt.
set -euo pipefail
cd "$(dirname "$0")/.."

NO_DEMO=0
for a in "$@"; do
  case "$a" in
    --no-demo) NO_DEMO=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

find_python() {
  for c in python3.13 python3.12 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    echo "==> creating .venv with uv"
    uv venv --python 3.12 .venv
  else
    PY=$(find_python) || { echo "Python 3.12 or newer is required (or install uv: https://docs.astral.sh/uv/)"; exit 1; }
    echo "==> creating .venv with $PY"
    "$PY" -m venv .venv
  fi
fi

echo "==> installing hash-pinned dependencies (requirements.lock.txt)"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python --require-hashes -r requirements.lock.txt
  uv pip install --python .venv/bin/python --no-deps -e .
else
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --require-hashes -r requirements.lock.txt
  .venv/bin/python -m pip install --no-deps -e .
fi

echo "==> health check"
.venv/bin/aero doctor || echo "(doctor reported failures; the offline demo may still work)"

if [ "$NO_DEMO" = 1 ]; then
  echo "==> ready. Next: .venv/bin/aero demo   (or: make demo)"
else
  echo "==> starting the demo (Ctrl+C to stop)"
  exec .venv/bin/aero demo
fi
