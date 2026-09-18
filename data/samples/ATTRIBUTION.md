# Sample data attribution

## Traffic recordings (`*.jsonl.gz`)

Short captures from the [adsb.lol](https://adsb.lol) community feed, recorded with `aero stream`
on 2026-09-10 and gzip-compressed so the demo and the test-suite fixtures work offline:

| File | Coverage | Polls | Aircraft |
|---|---|---|---|
| `adsblol_usa-hubs_20260910T130638Z.jsonl.gz` | 15 US hubs (SEA, SFO, LAX, PHX, SLC, DEN, DFW, IAH, MSP, ORD, MCI, ATL, MIA, DCA, NYC) at 250 nm, polled in turn | 56 | 3,938 |
| `adsblol_nyc_20260910T115129Z.jsonl.gz` | New York at 250 nm, consecutive polls | 8 | ~900 |

adsb.lol publishes its data under the
[Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/). These files
are a derivative database: attribution is required and any redistribution of modified versions
must stay under the ODbL. The recordings hold public ADS-B broadcast fields only (address,
callsign, registration, type, position, altitude, velocity, squawk, integrity indicators); no
personal data beyond what every aircraft transmits in the clear.

## Image

- `apron_hohn.jpg`: "Lufttransportgeschwader 63 der Bundeswehr auf dem Fliegerhorst Hohn (August 2021)",
  Wikimedia Commons, licensed CC BY-SA 4.0. 1920 px thumbnail. Used only as a computer-vision demo input.
  https://commons.wikimedia.org/wiki/File:Lufttransportgeschwader_63_der_Bundeswehr_auf_dem_Fliegerhorst_Hohn_(August_2021).jpg

## Space and UAS samples (private branch)

- `swpc_scales_sample.json`: synthetic, in the shape of NOAA SWPC's `noaa-scales.json` and `planetary_k_index_1m.json`
  products (a severe geomagnetic storm day). Live products are US Government works in the public domain; cite
  NOAA/NWS/SWPC when publishing derived results.
- `ll2_launches_sample.json`: synthetic, in the reduced shape this tool keeps from The Space Devs' Launch Library 2
  (`ll.thespacedevs.com`). Live data: free tier, attribution requested ("Data from The Space Devs").
- `synthetic_conjunction.cdm`, `synthetic_mission.json`: synthetic CCSDS 508 message and mission description written for
  the tests; no real objects.
- CelesTrak element sets fetched by `aero space conjunctions` are cached under `data/space/elements/` (git-ignored) with
  a provenance sidecar; CelesTrak asks to be cited (Dr. T.S. Kelso).
- NASA-3D-Resources previews and NASA image library items are cached under `data/space/` (git-ignored) with their
  terms in each provenance sidecar (NOSA 1.3 and the NASA media guidelines).
- `gps3sv01_telemetry.json`: the analysed ascent telemetry of the GPS III SV01 Falcon 9 launch from
  https://github.com/shahar603/Telemetry-Data (Unlicense, public domain), parallel arrays of time (s), velocity (m/s)
  and altitude (km) transcribed from the webcast. Used as a genuine launch for the SPC rules and the demo.
- `utm_position_sample.json`, `utm_position_bad.json`: our own synthetic UTM Position messages; the contract they are
  checked against (nasa/utm-apis) is fetched on demand and never bundled.
- `tfr_sample.json`: synthetic, in the reduced shape `aero space tfr` keeps from the FAA's TFR list (`tfr.faa.gov`, list JSON
  plus one XNOTAM XML document per restriction): a launch hazard polygon around the sample Wallops launch and a capsule
  recovery circle placed inside the New York recording so the traffic join has something to find. Both are labelled
  synthetic in their ids and text. Live products are US Government works in the public domain.
- `decaying_sample.tle`: a synthetic element set (NORAD 99999, perigee ~185 km) placed so that its pass crosses the New
  York recording; checksums valid; no real object.
