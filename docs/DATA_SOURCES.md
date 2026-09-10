# Data sources

All sources below are free and keyless. The feeds are community-run; poll politely, credit
them, and do not resell their data.

## adsb.lol (primary)

- Endpoint used: `GET https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}` (radius up to 250).
  Global feeds wired as pseudo-regions: `--region mil` (`/v2/mil`, military-flagged), `ladd`
  (FAA Limiting Aircraft Data Displayed programme), `pia` (privacy ICAO addresses). Also
  available: `/v2/hex/{icao}`, `/v2/callsign/{cs}`. `/v2/all` is not served (503).
- Format: readsb aircraft JSON. Fields mapped: `hex`, `flight`, `r` (registration), `t` (type),
  `alt_baro` (ft or `"ground"`), `alt_geom`, `gs`, `track`, `baro_rate`, `squawk`, `emergency`,
  `nav_altitude_mcp` (autopilot selected altitude), `lat/lon`, `seen_pos`, `nic`, `nac_p`, `sil`,
  `type` (`adsb_icao`, `mlat`, `tisb_*`, `adsc`, ...).
- Position timestamp: `now - seen_pos` (seconds since last position message).
- Rate limits (observed 2026-09-09): HTTP 429 when polled from several clients concurrently or
  faster than ~10 s. One client at 12 s with four 250-nm regions round-robin is stable.
- Payload: ~540 KB at 250 nm around New York (~950 aircraft).

## OpenSky Network (secondary / corroboration)

- Endpoint: `GET https://opensky-network.org/api/states/all?lamin&lomin&lamax&lomax&extended=1`.
- Anonymous: ~400 credits/day, 10 s resolution, observed latency ~19 s per request. A
  9x11 degree box (US Northeast) costs 2 credits and returns ~1,150 aircraft.
- OAuth2 client credentials (set `OPENSKY_CLIENT_ID/SECRET` in `.env`) raise limits and
  resolution. Token endpoint is wired in `ingest/opensky.py`.
- Units are SI in the API (m, m/s); the mapper converts to ft, kt, fpm.
- `position_source` 0-3 maps to adsb / asterix / mlat / flarm.
- Does **not** expose NIC/NACp/SIL; SEC-012 is silent on OpenSky data.
- Coverage differs from adsb.lol enough to be useful for corroboration: over New York roughly
  120 aircraft per round were OpenSky-only and 25 adsb.lol-only, with ~400 seen by both.

## NOAA Aviation Weather Center

- `GET https://aviationweather.gov/api/data/metar?ids=KJFK,KEWR&format=json`.
- Used as context: holding during thunderstorms is expected, holding in CAVOK is a process smell.

## Not wired

- airplanes.live: requires an emailed access request.
- FlightAware AeroAPI, Flightradar24: paid.
- OpenSky historical (Trino) database: requires an approved account; would unlock months of
  training data.

## ADS-B integrity fields (RTCA DO-260B)

| Field | Meaning | Rule airspace minimum (14 CFR 91.227) |
|---|---|---|
| NIC (Navigation Integrity Category) | Containment radius the position is guaranteed within (e.g. NIC 7 = < 0.2 nm) | >= 7 |
| NACp (Navigation Accuracy Category, position) | 95% accuracy bound (NACp 8 = < 0.05 nm) | >= 8 |
| SIL (Source Integrity Level) | Probability the true position is outside the NIC containment | 3 |

TIS-B and MLAT tracks legitimately report 0 for all three; SEC-012 therefore applies only to
`position_source` starting with `adsb`.

## Altitude convention

On the ground, adsb.lol reports the string `"ground"` and OpenSky often reports no barometric
altitude; the mappers keep `baro_alt_ft = None` rather than fabricating 0 ft. Zeroing it made every
departure from Salt Lake City (field elevation 4,227 ft) look like a 4,300 ft jump and produced
false altitude-forgery findings until the first Southwest capture exposed it.

## Recording format

One JSON object per line: `{"ts", "provider", "region", "states": [StateVector...]}`.
`raw` provider payloads are excluded to keep files small; the mapped fields are sufficient
for every rule. `aero data inventory` summarises what is on disk.
