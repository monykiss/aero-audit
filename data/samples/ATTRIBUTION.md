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
