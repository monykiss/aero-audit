# Demo script

The app (`aero app`, see docs/APP.md) has a Live picture page with demo controls. This document
is the walkthrough: what to click and what you should see.

```bash
.venv/bin/aero serve                                   # replay the newest civil recording at 8x, port 8787
.venv/bin/aero serve --replay data/recordings/<file>.jsonl --speed 8
.venv/bin/aero serve --live --region nyc --radius 150 --interval 12 --port 8788   # real traffic, also recorded
.venv/bin/aero serve --live --region lhr,fra --radius 250 --no-demo             # round-robin, no injection controls
```

Open `http://127.0.0.1:8787`. The page polls the server every 3 seconds; no build step, no
external services beyond map tiles and the Leaflet library from a CDN.

## What you are looking at

| Area | Content | Why it matters for safe, efficient operations |
|---|---|---|
| Map | Every tracked aircraft as a heading-rotated icon; colour = worst finding in the last 10 min, purple = trust below 0.5, dashed/magenta = injected; click for the aircraft drawer with track, integrity fields, trust, and its findings | The surveillance picture, annotated with what the audit thinks of each track |
| KPI tiles | Aircraft now, airborne, seen total, findings, critical + high, medium, ADS-B integrity compliance, low-trust count | Posture at a glance |
| Findings | Newest findings and highest-risk findings, each with rule, aircraft, and the first playbook step | The triage queue |
| Safety | Emergency / interference codes in the current picture, separation screen (SAF-004), vertical profile (SAF-003, OPS-004), emergency squawks this session, METARs for the region's stations (live mode) | The factors that hurt aircraft first: emergencies, proximity, vertical excursions, weather |
| Security | Spoofing indicators (SEC-010/011/014/015/018), stream health (flooding SEC-016, jamming SEC-017), integrity compliance (SEC-012), low-trust aircraft, identity (SEC-013, watchlist SEC-020) | Whether the picture itself can be trusted |
| Operations | Holding with fuel, CO2, and delay cost; pattern-work and coverage-gap counts; aircraft-per-poll sparkline per region; feed health | Where efficiency is being lost and whether the feed is healthy |
| Risk | Evidence-adjusted register (inherent, residual, evidence rate) and the threat matrix with measured recall | What to tell the risk committee |
| Model | Registry entry (rows, aircraft, holdout rate, checksum), injected-scenario recall and time-to-detect, rule precision | Why the ranking can be trusted, and where it cannot |

## Demo controls (demo mode, on by default)

Buttons inject an attack into the stream for a few polls; the banner lists active injections and
`Clear injections` stops them. Select an aircraft first to target it, otherwise a suitable
airborne aircraft is picked.

| Button | What happens | What you should see |
|---|---|---|
| Teleport 30 nm | Target's position shifted north from the next poll | SEC-010 critical on the next poll; the icon jumps and turns red; trust drops |
| Squawk 7500 | Target squawks the hijack code | SEC-003 high "single fix, unconfirmed" on the first poll, escalated to critical on the second; aircraft appears under Safety > Emergency codes |
| Altitude +6,000 ft | Barometric altitude forged, vertical rate untouched | SEC-018 on the next poll |
| Speed halved | Reported ground speed forged | SEC-011 (and often ML-001) when the mismatch exceeds 150 kt |
| Ghost (jumpy) | Fabricated aircraft that jumps 20 nm every third poll | SEC-010 within three polls; the ghost shows with a magenta ring |
| Ghost (perfect) | Fabricated aircraft with consistent physics | Nothing fires. This is the known gap that cross-feed corroboration exists for |
| Flood 60 addresses | Sixty never-seen addresses appear at once | SEC-016 burst under Security > Stream health |
| Coverage collapse | 60% of the picture vanishes for two polls | SEC-017 under Security > Stream health |

Injected aircraft are flagged in every finding and in the drawer so a demo is never mistaken for
a real event. Demo mode can be disabled with `--no-demo`.

## Replay mode notes

Replay loops the recording; at each loop boundary the timestamps shift forward and the track
memory is reset, so the second pass starts from a fresh picture instead of every aircraft
appearing to jump twenty minutes. Speed 8x turns a 20-minute recording into a 2.5-minute loop
with a poll every 2.5 seconds.

## Live mode notes

Live mode records everything it ingests to `data/recordings/` so the session can be audited
afterwards with `aero audit --recording`. One live poller per host: adsb.lol rate-limits
concurrent clients. METARs refresh every 10 minutes for the region's stations.

## Running it from the Claude desktop preview pane (developer note)

`.claude/launch.json` has three configurations: `aero-dashboard` (replay), `aero-dashboard-live`
(New York, port 8788), and `aero-dashboard-attached`, which only opens `http://localhost:8790` and
expects a server you started yourself:

```bash
PYTHONUNBUFFERED=1 nohup .venv/bin/aero serve --replay data/recordings/<file>.jsonl --speed 8 --port 8790 > logs/dashboard_8790.log 2>&1 &
```

On this machine the launcher-started process did not bind its port, so the attached
configuration is the reliable path.
