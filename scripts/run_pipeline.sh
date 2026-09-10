#!/usr/bin/env bash
# End-to-end: inventory -> train (grouped holdout + model card) -> audit every live recording with
# the model -> evidence-adjusted risk assessment -> holding impact -> regenerate code-owned docs.
# Usage: scripts/run_pipeline.sh [contamination]   (default 0.01)
set -euo pipefail
cd "$(dirname "$0")/.."
AERO=.venv/bin/aero
CONTAM="${1:-0.01}"
MODEL=models/kinematic_iforest.joblib

shopt -s nullglob
# Civil hub / bbox recordings train the "normal" model. Global feeds (mil, ladd, pia) are audited
# but never trained on: military kinematics would teach the model that tanker orbits are normal.
LIVE=() ; SPECIAL=()
for f in data/recordings/adsblol_*.jsonl data/recordings/opensky_*.jsonl; do
  case "$f" in *_mil_*|*_ladd_*|*_pia_*) SPECIAL+=("$f");; *) LIVE+=("$f");; esac
done
if [ ${#LIVE[@]} -eq 0 ]; then echo "no live recordings in data/recordings/"; exit 1; fi
if pgrep -f "aero stream" >/dev/null; then echo "a capture is still running; wait for it so no half-written file is read"; exit 1; fi

echo "== inventory =="; $AERO data inventory
echo "== train on ${#LIVE[@]} live recordings (contamination $CONTAM) =="
$AERO train "${LIVE[@]}" --out "$MODEL" --contamination "$CONTAM"
BIGGEST_OS=$(ls -S "${LIVE[@]}" 2>/dev/null | grep opensky | head -1 || true)
BIGGEST=$(ls -S "${LIVE[@]}" 2>/dev/null | grep adsblol | head -1 || true)
if [ -n "$BIGGEST_OS" ]; then
  echo "== evaluate on the fast-polling feed for comparison (background: $BIGGEST_OS) =="
  $AERO evaluate "$BIGGEST_OS" --model "$MODEL" --targets 25 --max-batches 60 | tail -22
fi
if [ -n "$BIGGEST" ]; then
  echo "== evaluate on the primary feed; this precision drives risk scoring (background: $BIGGEST) =="
  $AERO evaluate "$BIGGEST" --model "$MODEL" --targets 25 --max-batches 60 | tail -22
fi
echo "== audit each recording with the model =="
for f in "${LIVE[@]}"; do
  echo "-- $f"; $AERO audit --recording "$f" --model "$MODEL" --name "$(basename "${f%.jsonl}")" | grep -E "findings=|compliance|Reports"
done
for f in "${SPECIAL[@]}"; do
  echo "-- (special feed, not in training) $f"; $AERO audit --recording "$f" --model "$MODEL" --name "$(basename "${f%.jsonl}")" | grep -E "findings=|compliance|Reports"
done
echo "== risk assessment from all evidence (recordings + corroboration reports) =="
CORR=()
for c in reports/corroborate_*.json; do CORR+=(--corroboration "$c"); done
$AERO risk assess "${LIVE[@]}" --model "$MODEL" "${CORR[@]}" | tail -3
echo "== holding impact =="
$AERO impact "${LIVE[@]}"
echo "== regenerate code-owned docs =="
$AERO docs-build
echo "== done: model card at ${MODEL%.joblib}.md, reports in reports/ =="
