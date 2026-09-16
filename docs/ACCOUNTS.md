# Accounts and credentials

Everything in this programme works keyless at some level. Accounts raise quotas or open one extra
source each. `aero accounts` prints the table below for this machine with a configured / keyless /
missing column and never prints a value; `aero doctor` adds one line summarising it.

## Rules

- Credentials live only in the environment. The local convention is a git-ignored `.env` that you
  `source` (or `export` lines in your shell profile). Never on a command line, never in `aero.toml`,
  never in a report.
- Nothing here transmits to an aviation or space system. Every account below is read-only data access.
- Create the accounts yourself; the tool cannot and should not sign up on your behalf.

## Services

| Service | Env | Sign up | Unlocks | Without it |
|---|---|---|---|---|
| adsb.lol | none | none | primary ADS-B feed | fully keyless |
| OpenSky Network | `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | opensky-network.org, then an API client under your profile | higher quota; second feed for corroboration (ST-10) | anonymous quota |
| CelesTrak | none | none | GP elements for conjunction screening | keyless; cache for hours |
| Space-Track.org | `SPACETRACK_USER`, `SPACETRACK_PASS` | space-track.org/auth/createAccount (free, approval takes a day or two; agree to their user agreement) | `cdm_public` conjunction summaries, GP history, decay and TIP messages (`aero space spacetrack`, `spacetrack_pull` job) | none; CelesTrak covers elements |
| api.nasa.gov | `NASA_API_KEY` (optional) | api.nasa.gov (instant, by email) | DONKI notifications, Mars rover photos, APOD, EPIC at 1,000 requests per hour | `DEMO_KEY` at 30 per hour; the image library and 3D resources need no key |
| NOAA SWPC | none | none | space weather scales, Kp, alerts (`aero space weather`) | fully keyless |
| The Space Devs Launch Library 2 | none | thespacedevs.com for paid tiers | launch windows and pads (`aero space launches`) | 15 requests per hour keyless; the scheduler default is one per hour |
| GitHub API | `GITHUB_TOKEN` (optional) | github.com/settings/tokens, fine-grained, public repositories read-only | NASA-3D-Resources tree at 5,000 requests per hour | 60 per hour anonymous |
| NOAA Aviation Weather Center | none | none | METAR/TAF | fully keyless |
| FAA NAS status | none | none | airport programmes and delays | fully keyless |

## Two-minute path for Space-Track (the one account worth having)

1. Create the account at https://www.space-track.org/auth/createAccount with your email; accept their
   user agreement. Approval usually arrives within a day or two.
2. `cp .env.example .env`, fill `SPACETRACK_USER` and `SPACETRACK_PASS`, `chmod 600 .env`, `source .env`.
3. `aero accounts --probe`: the Space-Track row should read "login accepted; boxscore query returned 1 row(s)".
4. From then on: the Space page shows a "Pull Space-Track summaries" button instead of the call-out,
   `aero space watch` adds `spacetrack_pull=3600` to its schedule by itself, and `AERO_SCHEDULE` can
   include `spacetrack_pull=3600` for the web app. Nothing is transmitted to Space-Track beyond the
   login and read queries.

The tool never creates accounts or types credentials for you; that is deliberate.

**Read the user agreement before you tick the box.** It says the user "agrees not to transfer any data or
technical information received from this website, or other U.S. Government source, including the
analysis of data, to any other entity without prior express approval" (10 USC 2274(c)(2)). The tool
honours that mechanically: every ledger row that came from Space-Track carries a `restricted` marker,
`aero log bundle` leaves any report carrying that marker out of the evidence zip, and publish-check
PUB-11 fails if Space-Track material is ever tracked in git. Keep Space-Track-derived screenshots and
numbers out of anything you share, including this project's public repository, unless they approve it.

## Probing what you configured

`aero accounts --probe` makes one harmless read per service (authenticated where credentials
exist): Space-Track login plus a one-row boxscore query, an OpenSky token request, an api.nasa.gov
call with your key or `DEMO_KEY`, and the keyless endpoints. It prints OK / skip / FAIL with an
HTTP status or error class, never a value.

## NASA DONKI without a key

`aero space weather --donki` (and the `space_weather` job with `donki: true`) fetches DONKI
notifications with `NASA_API_KEY`, or `DEMO_KEY` when unset, and cross-checks them against the SWPC
assessment per effect: both, swpc-only, donki-only or quiet. It is listed on the Space page, not scored.

## Setting them

```bash
cat > .env <<'EOF'
export SPACETRACK_USER='you@example.org'
export SPACETRACK_PASS='...'
export OPENSKY_CLIENT_ID='...'
export OPENSKY_CLIENT_SECRET='...'
export NASA_API_KEY='...'
EOF
chmod 600 .env
source .env
aero accounts
```

`.env` is in `.gitignore`; the gitleaks step in CI and the pre-commit hook refuse commits that look
like they carry a secret anyway.

## What each account changes in the reports

- Space-Track: the CDM ledger fills from public summaries as well as files you drop in the inbox,
  so events and Pc trends cover objects you do not own. Summaries carry the originator's Pc; the
  tool never recomputes it without a covariance.
- OpenSky: corroboration studies compare two independent feeds; without it the second feed is
  rate-limited and short.
- NASA API key: not needed for anything on the current branch; reserved for DONKI cross-checks of
  the SWPC assessment.
