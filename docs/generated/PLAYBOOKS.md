# Response playbooks (generated)

## SEC-001, SEC-002, SEC-003, SEC-004: Emergency / interference squawk

SLA to triage: 5 min

Triage:
1. The rule itself marks a single-fix code as unconfirmed and escalates on the second consecutive fix; a transient code between identical normal codes is usually a mis-dial (seen live: one poll of 7500 on a descending airliner, back to its assigned code on the next poll).
1. Pull callsign, type, origin/destination from the feed and the flight plan if available.
1. Check whether independent feeds (OpenSky vs adsb.lol) both report the code (SEC-015).

Verify:
- 7500 must be treated as real until ATC/AOC confirms otherwise.
- A spoofed squawk usually rides on a track that also fails SEC-010/SEC-015.

Escalate: 7500: immediate notification to the responsible ATC unit / security duty officer. 7700/7600: notify ops duty manager; log for safety reporting.

Contain:
- Do not broadcast or publish the finding externally.
- Mark the aircraft as 'under review' so downstream dashboards do not auto-alert repeatedly.

## SEC-010: Kinematically impossible position jump

SLA to triage: 15 min

Triage:
1. Open the track: was there one bad fix or a sustained new position?
1. Check position_source: MLAT outliers are common and benign; pure ADS-B jumps are not.
1. Look for a duplicate ICAO24 (SEC-014) around the same time.

Verify:
- Run `aero corroborate` on the region: a real aircraft is seen at the same place by both feeds.
- If the feed shows a jump and then returns to the original track, suspect a receiver merge glitch.

Escalate: Escalate to the security lead when the jump is corroborated by only one receiver network and coincides with SEC-014/SEC-016 activity.

Contain:
- Drop the aircraft to low trust (TrustLedger) so analytics ignore it until cleared.
- Preserve the raw recording for forensics.

## SEC-011: Reported vs implied speed mismatch

SLA to triage: 30 min

Triage:
1. Check dt: mismatches at dt < 10 s are dominated by timestamp jitter.
1. Compare over 3+ fixes: a persistent bias suggests forged velocity messages.

Verify:
- Cross-feed corroboration; MLAT-derived speed if available.

Escalate: Escalate only if persistent and combined with another SEC finding.

Contain:
- Downgrade trust; exclude from speed-based analytics.

## SEC-012: Integrity / accuracy below minimums

SLA to triage: 1440 min

Triage:
1. Note NIC/NACp/SIL values and aircraft type; GA aircraft with older GPS are the usual case.
1. Check persistence across the flight (occurrences).

Verify:
- A single aircraft with SIL 0 all flight = equipment issue; many aircraft at once = receiver/feed issue.

Escalate: Persistent SIL 0 / NIC < 5 on commercial traffic: report to the operator / regulator channel.

Contain:
- Downgrade trust for the aircraft; weight its positions lower in analytics.

## SEC-013: No flight ID at altitude

SLA to triage: 1440 min

Triage:
1. Check registration / type from the feed; many GA and military flights legitimately omit Flight ID.

Verify:
- Persistent across the flight and paired with SEC-012 suggests misconfiguration.

Escalate: Not escalated alone.

Contain:
- Log only.

## SEC-014: Duplicate ICAO24 address

SLA to triage: 15 min

Triage:
1. Identify both positions and separation; check if one is MLAT/TIS-B.
1. Look up the address in the registry: does the type/registration match either track?

Verify:
- Two genuine aircraft with the same address = misconfigured transponder (happens after maintenance).
- One genuine + one ghost = T01/T08.

Escalate: Escalate if the duplicate persists > 5 min or is near sensitive airspace.

Contain:
- Split into two synthetic track ids for analytics; low trust on both.

## SEC-015: Cross-feed position disagreement

SLA to triage: 15 min

Triage:
1. Check the time offset between feeds; the tool dead-reckons but large dt reduces confidence.
1. Which feed is the outlier? Compare with a third source if available.

Verify:
- Consistent disagreement on one aircraft = spoof or bad feeder; on many aircraft = a feed-wide problem (T10).

Escalate: Feed-wide disagreement: escalate to whoever owns the data pipeline immediately.

Contain:
- Prefer the feed with MLAT corroboration; quarantine the other until resolved.

## SEC-016: New-address burst

SLA to triage: 10 min

Triage:
1. How many new addresses, over what area, in how many seconds?
1. Do the new addresses have plausible registrations/types (feed enrichment) or none?

Verify:
- Genuine bursts happen when a receiver comes online or at shift changes at large hubs; they have realistic kinematics. Ghost floods usually do not.

Escalate: Escalate as suspected flooding (T05) if the burst also trips SEC-010/SEC-011 on many aircraft.

Contain:
- Cap ingestion; raise trust threshold for alerts; preserve raw batches.

## SEC-017: Coverage collapse

SLA to triage: 10 min

Triage:
1. Did the provider return an error/empty payload (tooling) or a real drop (RF)?
1. Compare with the second provider: a drop on only one feed is a feeder outage, not jamming.

Verify:
- RF jamming affects all receivers in an area across feeds simultaneously.

Escalate: Simultaneous collapse across independent feeds near an airport: escalate to the security lead.

Contain:
- Switch analytics to the healthy feed; annotate the gap in reports.

## SEC-018: Altitude inconsistent with vertical rate

SLA to triage: 15 min

Triage:
1. Check position_source; MLAT/TIS-B altitude relays lag and jump.
1. Compare implied vs reported vertical rate over the next fixes: a forgery persists, a glitch reverts.

Verify:
- Cross-feed corroboration of altitude; Mode C from a second receiver.

Escalate: Escalate with SEC-010/011 on the same aircraft as a suspected modification (T02).

Contain:
- Lower trust; exclude the aircraft from vertical-separation analytics until cleared.

## SEC-020: Watchlist match

SLA to triage: 5 min

Triage:
1. Read the watchlist reason; follow the handling instructions attached to the entry.

Verify:
- Confirm the identity via registration + type, not just address.

Escalate: Per the watchlist entry's severity.

Contain:
- Restrict reporting for *protection* entries (VIP/medical) to the authorised audience.

## OPS-001: Coverage gap

SLA to triage: 10080 min

Triage:
1. Map the gaps over a day; cluster by sector.

Verify:
- Persistent gaps in the same sector = receiver hole, not an aircraft issue.

Escalate: Not escalated; feeds into coverage planning.

Contain:
- None.

## OPS-002: Holding / orbiting

SLA to triage: 10080 min

Triage:
1. Check METAR for the destination: weather holding is expected.
1. Aggregate minutes held per hour and per runway configuration.

Verify:
- Holding without weather cause across many arrivals = arrival-rate / flow-management issue.

Escalate: Weekly review with ops / ATFM stakeholders.

Contain:
- None (process improvement, not containment).

## OPS-003: Low-altitude orbiting

SLA to triage: 10080 min

Triage:
1. Check type/registration: trainers, helicopters, survey aircraft.

Verify:
- Recurring at the same airfield = pattern traffic; over a city = survey or law-enforcement.

Escalate: Not escalated.

Contain:
- Log only; use for density / noise analysis.

## OPS-004: Persistent level-off away from selected altitude

SLA to triage: 1440 min

Triage:
1. Check whether the aircraft later moves to the selected altitude (pending clearance).

Verify:
- A level bust shows as *reaching* an unselected altitude, not sitting at one; treat as low priority.

Escalate: Only if combined with a TCAS/RA report from another source.

Contain:
- None.

## OPS-005: VFR code above FL180

SLA to triage: 1440 min

Triage:
1. Confirm the aircraft is in US airspace (rule is US-specific).

Verify:
- Persistent 1200 at FL350 is almost always a transponder not re-set after departure.

Escalate: Not escalated.

Contain:
- Log only.

## SAF-003: Excessive vertical rate

SLA to triage: 60 min

Triage:
1. Compare reported vs implied vertical rate; disagreement means bad data, not a dive.

Verify:
- Fighter / aerobatic types legitimately exceed thresholds.

Escalate: If implied and reported agree and the type is commercial: notify safety office.

Contain:
- None.

## SAF-004: Close proximity (indicative)

SLA to triage: 30 min

Triage:
1. Check both fix ages and sources; stale or MLAT positions dead-reckon badly.
1. Look at tracks: converging, parallel, or formation?

Verify:
- ATC radar / TCAS are authoritative; ADS-B derived separation is a screening signal.

Escalate: Only if both fixes are fresh ADS-B, tracks converge, and vertical spacing is under 600 ft: notify the safety office.

Contain:
- None (screening); aggregate by sector for airspace design review.

## ML-001: Kinematic anomaly (model)

SLA to triage: 1440 min

Triage:
1. Read top_deviations_z: which features drove the score?
1. Check whether a hard rule also fired on the same aircraft.

Verify:
- Benign anomalies (helicopters, aerobatics, survey flights) recur by type; add them to training.

Escalate: Never escalate on ML alone.

Contain:
- Retrain with the reviewed window; track precision over time in the model card.

## OPS-VIS-001: Apron zone over capacity

SLA to triage: 10080 min

Triage:
1. Confirm detections visually; COCO models miss small aircraft and box wings.

Verify:
- Persistent congestion across frames, not one image.

Escalate: Weekly review with apron management.

Contain:
- None.

## ORB-004: Conjunction probability of collision above threshold

SLA to triage: 60 min

Triage:
1. Confirm the message is the newest for the pair (ledger event trend) and that both states carry covariance.
1. Recompute Pc with the object's hard-body radius; note whether the number is the originator's or ours.
1. Check ORB-005: an inconsistent message is a data problem before it is a safety one.

Verify:
- Compare with the originator's Pc and miss distance; agreement within an order of magnitude is expected.
- Rescreen with fresh elements (ORB-006 would void the older set).

Escalate: Operator's flight dynamics team and the conjunction assessment provider; never manoeuvre on this tool's number alone.

Contain:
- Record the assessment and the decision in the audit log.
- Schedule the next CDM check before TCA minus the manoeuvre lead time.

## ORB-007: Decay imminent

SLA to triage: 240 min

Triage:
1. Confirm the object and its perigee from the newest element set.
1. Check whether a TIP message exists from the tracking authority.

Verify:
- Compare the decay estimate with the tracking authority's; ours is a bound, not a prediction.

Escalate: Tracking authority reentry desk; airspace authorities issue closures, not this tool.

Contain:
- Shorten the screening window for the object.
- Refresh elements daily until reentry.

## DEB-001: Post-mission lifetime beyond the limit

SLA to triage: 1440 min

Triage:
1. Confirm the mission parameters (perigee, apogee, mass, area) and which rule applies (FCC 5-year, NASA 25-year).
1. Run the lifetime estimate at both drag-coefficient bounds.

Verify:
- Compare with the operator's certified analysis if one exists.

Escalate: Mission designer and the licensing authority's debris review.

Contain:
- Record the shortfall and the design option considered (lower disposal orbit, drag device, propulsive deorbit).

## DAA-001: Well-clear violation observed

SLA to triage: 120 min

Triage:
1. Pull both tracks around the violation; confirm the geometry is not a surveillance artefact (MLAT jump, position source).
1. Check NMAC proximity and the alert lead time.

Verify:
- Replay the encounter with the well-clear definitions and compare with the recorded alert level.
- If one aircraft is a UAS, check the operator's DAA log.

Escalate: Safety office; a pattern of violations in one area becomes an airspace study (ST-07, ST-16).

Contain:
- Record the encounter in the study register.
- Add the cell to the density watch if it is dense at low altitude (DAA-004).

## SWX-001: Geomagnetic advisory conditions

SLA to triage: 60 min

Triage:
1. Confirm the NOAA product time and Kp; check that the product is not stale (SWX-004).
1. List the high-latitude traffic exposed (SWX-005).

Verify:
- Look for ADS-B integrity drops (NACp / NIC) in the same window: weather, not spoofing, explains them.
- Rescreen conjunctions with fresh elements: drag increases element ageing.

Escalate: Operators with polar routes and the space weather centre's advisory; the tool only correlates.

Contain:
- Annotate the audit log with the advisory conditions for the window.

## LCH-001: Aircraft inside a launch hazard radius during the window

SLA to triage: 60 min

Triage:
1. Retrieve the published TFR / NOTAM geometry and time for the launch; our radius is a default.
1. List the closest aircraft with time, altitude and distance.

Verify:
- Only aircraft inside the real hazard area during the effective time are a coordination failure; the rest are outside the NOTAM.

Escalate: Range safety and the ATC facility; after the fact, the launch operator's airspace coordination review.

Contain:
- Record the count inside the real area and the displacement baseline.

## SPC-006: Telemetry packet failed authentication

SLA to triage: 30 min

Triage:
1. Confirm the key for the SPI (AERO_SDLS_KEY_<spi>) matches the link's current key; a re-key explains a burst of failures at one time.
1. Compare the failed packets' physics (SPC-001..005) with their neighbours: forged content is usually implausible too.

Verify:
- One failure in a long verified stream is corruption; a run of failures with plausible physics is an injection attempt or a key mismatch.

Escalate: The ground segment's link security owner; the mission's security officer for a suspected injection.

Contain:
- Quarantine the affected packets and rerun the audit on the verified subset.

## TFR-001: Aircraft inside a space-operations TFR while in effect

SLA to triage: 60 min

Triage:
1. Read the NOTAM text for the exemptions (range support, ATC-authorised, the operator's own aircraft) and the exact vertical limits.
1. List each aircraft with first and last time inside, altitude and the number of fixes; match callsigns against the exemptions.

Verify:
- An aircraft inside the volume during the effective time and not on the exemption list is an entry into a published restriction; a TFR at 'unlimited' ceiling catches overflights the NOTAM may not intend.

Escalate: The controlling ARTCC named in the NOTAM and the launch operator's airspace coordinator; after the fact, the FAA's Office of Commercial Space Transportation.

Contain:
- Record the count inside, the exemption matches and the baseline outside the effective time.

## REN-001: Aircraft under the track of a decaying object

SLA to triage: 240 min

Triage:
1. Check the tracking authority's reentry prediction (TIP) and any reentry NOTAM; the corridor here is a ground track with a width, not a footprint.
1. Refetch elements: a set older than two days no longer places a decaying object on the right pass.

Verify:
- Exposure to a possible footprint is informational until the authority publishes a window; the finding names who would be affected, not who is at risk.

Escalate: Dispatch and the ANSP for the flight information regions under the corridor; the tracking authority owns the prediction.

Contain:
- Annotate the report with the authority's prediction once published and rerun with fresh elements.
