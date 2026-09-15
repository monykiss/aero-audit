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
