# Operations runbook

## Daily capture (one poller per host, please)

```bash
# 25 minutes, four 250-nm hubs round-robin, ~50 s revisit per region
PYTHONUNBUFFERED=1 nohup .venv/bin/aero stream --provider adsblol \
  --region nyc,ord,lax,lhr --radius 250 --interval 12 --seconds 1500 > logs/capture_adsblol.log 2>&1 &

# Independent second feed for corroboration (OpenSky anonymous budget ~400 credits/day)
PYTHONUNBUFFERED=1 nohup .venv/bin/aero stream --provider opensky \
  --bbox 36,-80,45,-69 --interval 20 --seconds 1200 > logs/capture_opensky.log 2>&1 &
```

Schedule with cron/launchd for continuous coverage; keep adsb.lol to a single client per host.

## Audit and alert

```bash
.venv/bin/aero audit --live --region nyc --radius 250 --seconds 600 \
  --model models/kinematic_iforest.joblib --watchlist data/watchlist.json \
  --alert-log logs/alerts.jsonl --alert-webhook https://hooks.example/... --alert-min-severity high
```

Every live audit also writes the recording, so the report can be reproduced with
`aero audit --recording <file>`.

## Corroborate two feeds

```bash
.venv/bin/aero corroborate --region nyc --radius 150 --interval 25 --seconds 100
```

Read the summary line: `disagree` should be near zero and `median_sep` under 0.5 nm. Many
disagreements at once means a feed-wide problem (T10), not many spoofers.

## Report formats

Each audit writes `reports/<name>_<ts>.json` (all findings and the summary), `.md` (executive summary,
KPIs, ranked findings with first playbook step), and `.html` (self-contained, safe to email or attach to
a ticket). The executive summary lists the register risks that rise above medium on this evidence and
the three findings to look at first.

## Triage loop

1. Open the newest `reports/*.md`; findings are ranked by `risk_score`.
2. For each finding, follow `aero security playbook <RULE>`; the report shows the first step.
3. Record the outcome (true / benign / false) in your tracker; feed benign ML-001 cases back
   into training windows.
4. Weekly: `aero risk assess data/recordings/*.jsonl --model models/kinematic_iforest.joblib`
   and review movements in the register.

## Evaluate detection (do this after any rule or model change)

```bash
.venv/bin/aero evaluate "data/recordings/<largest adsblol recording>.jsonl" --model models/kinematic_iforest.joblib --targets 25 --max-batches 60
```

Writes `models/evaluation.json` (rule precision used by risk scoring) and `reports/evaluation_*.md`.

## Tune thresholds without editing code

```bash
.venv/bin/aero config init      # writes aero.toml with every tunable commented at its default
.venv/bin/aero config show rules
```

Uncomment and change values; unknown keys fail loudly. Overrides apply to every command.

## Retention

```bash
.venv/bin/aero data prune --days 30          # dry run
.venv/bin/aero data prune --days 30 --apply
```

## One-shot pipeline

`scripts/run_pipeline.sh [contamination]` runs inventory, training with a grouped holdout and
model card, the injected-scenario evaluation, an audit of every live recording with the new
model, the evidence-adjusted risk assessment, the holding-impact estimate, and the docs regeneration.

## Retraining

```bash
.venv/bin/aero train data/recordings/adsblol_*.jsonl data/recordings/opensky_*.jsonl --contamination 0.01
```

Read the model card (`models/kinematic_iforest.md`). Retrain when the holdout flag rate drifts
above ~2x contamination or when new regions/seasons are added.

## If Python cannot connect but curl can

Per-application firewalls (LuLu, Little Snitch) and VPN extensions can silently block outbound
connections from unsigned binaries such as a pyenv Python or uv while Apple-signed `curl`
passes. The providers detect a connect-level failure and switch to a curl transport for the
rest of the process; force it up front with `AERO_HTTP_BACKEND=curl`, or force pure httpx with
`AERO_HTTP_BACKEND=httpx`. Approve the Python binary in the firewall to restore the faster path.

## Health checks

- `aero providers`: latency and aircraft counts per feed.
- `aero data inventory`: what is on disk, total unique aircraft.
- `logs/capture_*.log`: 429 sleeps and failures are logged with the region.

## Retention and privacy

Recordings contain public broadcast data only, but they enable tracking. Keep retention short
(suggest 30 days), restrict report access for `protect` watchlist entries, and never publish
tracks of protected aircraft.
