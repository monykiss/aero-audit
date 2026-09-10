# Demo script

Everything here works offline. The bundled samples are real adsb.lol traffic
(`data/samples/ATTRIBUTION.md`); the attacks are injected into the replay and marked as such
everywhere they appear, so a demo can never be mistaken for a real event.

## Sixty seconds

```bash
scripts/bootstrap.sh          # first time: .venv, hash-verified install, doctor, then the demo
.venv/bin/aero demo           # afterwards: one command
```

`aero demo` replays the 15-hub sample at 10x with the **scripted tour** running and opens
`http://127.0.0.1:8787`. If no anomaly model exists it trains one on the samples first (a few
seconds). Then:

1. Press **F2** (Live picture). Arrows are aircraft; colour is the worst finding in the last ten
   minutes. The amber banner narrates the tour: which attack is next, what should fire.
2. Click **SND** in the header (or type `SND` on the command line) to hear new high and critical
   findings: tones, or a second click for spoken announcements.
3. Watch the ticker under the header and the Findings panel: SEC-010 on the teleport, SEC-003
   unconfirmed then confirmed on the hijack code, SEC-018 on the altitude forgery, SEC-016 and
   SEC-017 on the flood and the collapse. The perfect ghost fires nothing, on purpose.
4. Press **F6** (Findings), click a row: evidence and the playbook. Press **F8** (Audit log): every
   injection the tour made, hash-chained, with **CHAIN VERIFIED** at the top.
5. Type `RPT`, click **Generate report from the current session**: JSON, Markdown, HTML and a
   manifest. Click **verify** on the report row to re-hash the files against the manifest.

Stop the tour with the link in the banner or `TOUR` on the command line; start it again the same
way. Injections can also be fired by hand from the demo bar on the Live page.

## The tour timeline

| After | Injection | What you should see |
|---|---|---|
| 6 s | Teleport 30 nm | SEC-010 critical on the aircraft's next report; its icon jumps and turns red; trust drops |
| 30 s | Squawk 7500 | SEC-003 high "single fix, unconfirmed", then critical on the second report, bypassing the cooldown |
| 54 s | Altitude +6,000 ft | SEC-018: barometric altitude inconsistent with the vertical rate |
| 78 s | Speed halved | SEC-011 when the mismatch clears 150 kt; often ML-001 too |
| 102 s | Ghost (jumpy) | Fabricated aircraft that jumps 20 nm every third report: SEC-010 within three polls; magenta ring |
| 126 s | Ghost (perfect) | Nothing fires. The known gap cross-feed corroboration (`aero corroborate`) exists for |
| 150 s | Flood 60 addresses | SEC-016 stream burst under Security > Stream health |
| 168 s | Coverage collapse | SEC-017: sixty percent of the picture vanishes for two polls |

The tour loops. On the round-robin sample a targeted injection waits until its region comes back
(about twelve seconds at 10x), which is why the steps are spaced as they are.

## What each panel means

| Area | Content | Why it matters for safe, efficient operations |
|---|---|---|
| Map | Every tracked aircraft as a heading-rotated icon; colour = worst finding in the last 10 min, purple = trust below 0.5, magenta ring = injected; click for the drawer with track, integrity fields, trust, findings | The surveillance picture, annotated with what the audit thinks of each track |
| KPI tiles | Aircraft now, airborne, seen total, findings, critical + high, medium, ADS-B integrity compliance, low-trust count | Posture at a glance |
| Findings | Newest and highest-risk findings with rule, aircraft, and first playbook step | The triage queue |
| Safety | Emergency codes, separation screen (SAF-004), vertical profile (SAF-003, OPS-004), METARs | The factors that hurt aircraft first |
| Security | Spoofing indicators (SEC-010/011/014/015/018), stream health (SEC-016/017), integrity compliance (SEC-012), low-trust aircraft, identity (SEC-013, SEC-020) | Whether the picture itself can be trusted |
| Operations | Holding with fuel, CO2 and delay cost; pattern work; coverage gaps; aircraft per poll; feed health | Where efficiency is being lost |
| Risk | Evidence-adjusted register and threat matrix with measured recall | What to tell the risk committee |
| Audit log | Every action, hash-chained | Proof of what was done to the picture |

## Manual injections

| Button | What happens | What you should see |
|---|---|---|
| Teleport 30 nm | Target's position shifted north on its next reports | SEC-010 critical; icon jumps and turns red; trust drops |
| Squawk 7500 | Target squawks the hijack code | SEC-003 high unconfirmed, then critical |
| Altitude +6,000 ft | Barometric altitude forged, vertical rate untouched | SEC-018 |
| Speed halved | Reported ground speed forged | SEC-011 (and often ML-001) past 150 kt mismatch |
| Ghost (jumpy) | Fabricated aircraft jumping 20 nm every third poll | SEC-010 within three polls; magenta ring |
| Ghost (perfect) | Fabricated aircraft with consistent physics | Nothing: the known gap |
| Flood | Sixty never-seen addresses at once | SEC-016 |
| Collapse | 60% of the picture vanishes for two polls | SEC-017 |

Select an aircraft first to target it; otherwise a suitable airborne aircraft is picked. Targeted
injections last N reports *of that aircraft*, so they survive round-robin feeds.

## Other ways to run it

```bash
.venv/bin/aero demo --no-tour --speed 4                    # quieter replay, inject by hand
.venv/bin/aero serve --replay data/recordings/<file>.jsonl  # any recording, no tour
.venv/bin/aero serve --live --region nyc --radius 150       # real traffic (also recorded)
.venv/bin/aero app                                          # empty app, choose a source on Home
docker run --rm -p 127.0.0.1:8787:8787 aero-audit           # the same demo in a container
```

Live mode records everything it ingests to `data/recordings/` so the session can be audited
afterwards. One live poller per host: adsb.lol rate-limits concurrent clients.

## Running it from the Claude desktop preview pane (developer note)

`.claude/launch.json` has an attached configuration that only opens `http://localhost:8790`; start
the server yourself with `nohup .venv/bin/aero demo --port 8790 --no-open > logs/demo_8790.log 2>&1 &`.
