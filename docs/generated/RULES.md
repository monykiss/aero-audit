# Rule ids (generated)

| Rule | Category | Description |
|---|---|---|
| SEC-001 | security | Squawk 7700 general emergency |
| SEC-002 | security | Squawk 7600 radio failure |
| SEC-003 | security | Squawk 7500 unlawful interference |
| SEC-004 | security | Emergency status subfield set |
| SEC-010 | security | Kinematically impossible position jump |
| SEC-011 | security | Reported vs implied ground speed mismatch |
| SEC-012 | data-quality | NIC/NACp/SIL below rule-airspace minimums (ADS-B sources only) |
| SEC-013 | security | Airborne above 10,000 ft without flight ID |
| SEC-014 | security | Same ICAO24 at two distant positions in one batch |
| SEC-015 | security | Cross-feed position disagreement (corroboration) |
| SEC-016 | security | New-address burst (flooding indicator) |
| SEC-017 | security | Coverage collapse (jamming / feed outage indicator) |
| SEC-018 | security | Altitude change inconsistent with reported vertical rate |
| SEC-020 | security | Watchlist match |
| OPS-001 | operations | Surveillance coverage gap (stale position) |
| OPS-002 | operations | Airline-style holding (>= 3,000 ft and >= 150 kt) |
| OPS-003 | operations | Low-altitude / low-speed orbiting (pattern work, survey, helicopter) |
| OPS-004 | safety | Persistent level flight away from selected altitude |
| OPS-005 | operations | VFR code 1200 above FL180 (US) |
| SAF-003 | safety | Excessive vertical rate |
| SAF-004 | safety | Close proximity between airborne aircraft (indicative separation check) |
| ML-001 | ml | IsolationForest kinematic anomaly |
| OPS-VIS-001 | operations | Apron zone over planned capacity |
| OPS-VIS-002 | operations | Apron zone unoccupied |
| SPC-001 | security | Implausible acceleration between telemetry samples |
| SPC-002 | security | Altitude change faster than the reported total speed allows |
| SPC-003 | data-quality | Telemetry dropout in an otherwise dense stream |
| SPC-004 | security | Telemetry time regression or duplicate sample (splice / replay) |
| SPC-005 | data-quality | Altitude discontinuity in one telemetry step |
| SPC-006 | security | Telemetry packet failed authentication (SDLS MAC mismatch) |
| SPC-007 | data-quality | Telemetry accepted without authentication (no MAC or no key for the SPI) |
| SPC-008 | security | Authenticated packet replays or regresses the sequence number |
| ORB-001 | data-quality | Stale element set (older than the screening limit) |
| ORB-002 | safety | Close approach under the distance threshold (no covariance) |
| ORB-003 | data-quality | SGP4 propagation error (decayed or malformed set) |
| ORB-004 | safety | Conjunction probability of collision above the manoeuvre or watch threshold |
| ORB-005 | data-quality | Conjunction data message internally inconsistent |
| ORB-006 | data-quality | Manoeuvre-scale change between consecutive element sets |
| ORB-007 | safety | Decay imminent: low perigee or re-entry within the watch window |
| ORB-008 | data-quality | Element set in use for an object the catalogue records as decayed |
| DEB-001 | safety | Post-mission orbital lifetime beyond the disposal limit |
| DEB-002 | safety | No passivation of stored energy at end of mission |
| DEB-003 | safety | No collision-avoidance capability in a populated shell |
| DEB-004 | safety | Reentry casualty risk above the limit |
| DEB-005 | safety | GEO disposal raise below the graveyard minimum |
| DEB-006 | data-quality | Object not trackable by the surveillance network |
| DEB-007 | safety | Planned release of mission-related objects |
| DEB-008 | safety | Large constellation without stated disposal reliability |
| DAA-001 | safety | Well-clear violation observed between airborne aircraft |
| DAA-002 | safety | Alert lead time below the warning time |
| DAA-003 | safety | Observed DAA risk ratio above the programme limit |
| DAA-004 | safety | Dense low-altitude airspace where small UAS operate |
| DAA-005 | safety | Well-clear violation rate rising across recordings |
| SWX-001 | operations | Geomagnetic conditions at ICAO advisory level (GNSS, drag) |
| SWX-002 | operations | Radio blackout conditions at ICAO advisory level (HF) |
| SWX-003 | operations | Solar radiation storm at ICAO advisory level (flight-level radiation) |
| SWX-004 | data-quality | Space weather product stale |
| SWX-005 | operations | Aircraft observed at high latitude during advisory conditions |
| LCH-001 | safety | Aircraft inside the hazard radius of a pad during its launch window |
| LCH-002 | data-quality | Launch record stale while its window is open |
| LCH-003 | data-quality | Launch window overlaps the recording but the pad is outside the recorded region |
| TFR-001 | safety | Aircraft inside a space-operations TFR while it was in effect |
| TFR-002 | data-quality | US launch window without a published space-operations TFR covering the pad |
| TFR-003 | data-quality | TFR product stale while a restriction is in effect |
| REN-001 | safety | Aircraft under the ground track of a decaying object as it passed |
| REN-002 | operations | Airports under the corridor of a decaying object |
| REN-003 | data-quality | Element set too old for an object flagged decaying |
