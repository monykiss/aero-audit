"""Catalogue and playbooks for the space and UAS rule ids, next to the air rules in audit.rules.RULE_CATALOG.

The Help page, docs/generated/RULES.md, the control library's rule check and the traceability matrix all read
from here, so a rule that fires anywhere in aero_audit/space or aero_audit/uas has one description, one category
and (for the ones that demand action) one playbook. tests/test_coverage_scaffold.py cross-checks this catalogue
against the rule ids actually emitted in code, in both directions.
"""

from __future__ import annotations

from .security.playbook_model import Playbook

SPACE_RULE_CATALOG: dict[str, tuple[str, str]] = {
    # launch telemetry (space/telemetry.py)
    "SPC-001": ("security", "Implausible acceleration between telemetry samples"),
    "SPC-002": ("security", "Altitude change faster than the reported total speed allows"),
    "SPC-003": ("data-quality", "Telemetry dropout in an otherwise dense stream"),
    "SPC-004": ("security", "Telemetry time regression or duplicate sample (splice / replay)"),
    "SPC-005": ("data-quality", "Altitude discontinuity in one telemetry step"),
    # space data link security (space/sdls.py)
    "SPC-006": ("security", "Telemetry packet failed authentication (SDLS MAC mismatch)"),
    "SPC-007": ("data-quality", "Telemetry accepted without authentication (no MAC or no key for the SPI)"),
    "SPC-008": ("security", "Authenticated packet replays or regresses the sequence number"),
    # orbital (space/orbital.py, cdm.py, maneuvers.py)
    "ORB-001": ("data-quality", "Stale element set (older than the screening limit)"),
    "ORB-002": ("safety", "Close approach under the distance threshold (no covariance)"),
    "ORB-003": ("data-quality", "SGP4 propagation error (decayed or malformed set)"),
    "ORB-004": ("safety", "Conjunction probability of collision above the manoeuvre or watch threshold"),
    "ORB-005": ("data-quality", "Conjunction data message internally inconsistent"),
    "ORB-006": ("data-quality", "Manoeuvre-scale change between consecutive element sets"),
    "ORB-007": ("safety", "Decay imminent: low perigee or re-entry within the watch window"),
    "ORB-008": ("data-quality", "Element set in use for an object the catalogue records as decayed"),
    # debris mitigation (space/debris.py)
    "DEB-001": ("safety", "Post-mission orbital lifetime beyond the disposal limit"),
    "DEB-002": ("safety", "No passivation of stored energy at end of mission"),
    "DEB-003": ("safety", "No collision-avoidance capability in a populated shell"),
    "DEB-004": ("safety", "Reentry casualty risk above the limit"),
    "DEB-005": ("safety", "GEO disposal raise below the graveyard minimum"),
    "DEB-006": ("data-quality", "Object not trackable by the surveillance network"),
    "DEB-007": ("safety", "Planned release of mission-related objects"),
    "DEB-008": ("safety", "Large constellation without stated disposal reliability"),
    # UAS detect-and-avoid (uas/encounters.py, uas/risk.py)
    "DAA-001": ("safety", "Well-clear violation observed between airborne aircraft"),
    "DAA-002": ("safety", "Alert lead time below the warning time"),
    "DAA-003": ("safety", "Observed DAA risk ratio above the programme limit"),
    "DAA-004": ("safety", "Dense low-altitude airspace where small UAS operate"),
    "DAA-005": ("safety", "Well-clear violation rate rising across recordings"),
    # space weather (space/spaceweather.py)
    "SWX-001": ("operations", "Geomagnetic conditions at ICAO advisory level (GNSS, drag)"),
    "SWX-002": ("operations", "Radio blackout conditions at ICAO advisory level (HF)"),
    "SWX-003": ("operations", "Solar radiation storm at ICAO advisory level (flight-level radiation)"),
    "SWX-004": ("data-quality", "Space weather product stale"),
    "SWX-005": ("operations", "Aircraft observed at high latitude during advisory conditions"),
    # launch windows (space/launches.py)
    "LCH-001": ("safety", "Aircraft inside the hazard radius of a pad during its launch window"),
    "LCH-002": ("data-quality", "Launch record stale while its window is open"),
    "LCH-003": ("data-quality", "Launch window overlaps the recording but the pad is outside the recorded region"),
    # space-operations airspace (space/airspace.py, ingest/tfr.py)
    "TFR-001": ("safety", "Aircraft inside a space-operations TFR while it was in effect"),
    "TFR-002": ("data-quality", "US launch window without a published space-operations TFR covering the pad"),
    "TFR-003": ("data-quality", "TFR product stale while a restriction is in effect"),
    # reentry corridors (space/reentry.py)
    "REN-001": ("safety", "Aircraft under the ground track of a decaying object as it passed"),
    "REN-002": ("operations", "Airports under the corridor of a decaying object"),
    "REN-003": ("data-quality", "Element set too old for an object flagged decaying"),
}

SPACE_PLAYBOOKS: dict[str, Playbook] = {
    "ORB-004": Playbook(
        "ORB-004", "Conjunction probability of collision above threshold",
        ("Confirm the message is the newest for the pair (ledger event trend) and that both states carry covariance.",
         "Recompute Pc with the object's hard-body radius; note whether the number is the originator's or ours.",
         "Check ORB-005: an inconsistent message is a data problem before it is a safety one."),
        ("Compare with the originator's Pc and miss distance; agreement within an order of magnitude is expected.",
         "Rescreen with fresh elements (ORB-006 would void the older set)."),
        "Operator's flight dynamics team and the conjunction assessment provider; never manoeuvre on this tool's number alone.",
        ("Record the assessment and the decision in the audit log.", "Schedule the next CDM check before TCA minus the manoeuvre lead time."),
        60,
    ),
    "ORB-007": Playbook(
        "ORB-007", "Decay imminent",
        ("Confirm the object and its perigee from the newest element set.", "Check whether a TIP message exists from the tracking authority."),
        ("Compare the decay estimate with the tracking authority's; ours is a bound, not a prediction.",),
        "Tracking authority reentry desk; airspace authorities issue closures, not this tool.",
        ("Shorten the screening window for the object.", "Refresh elements daily until reentry."),
        240,
    ),
    "DEB-001": Playbook(
        "DEB-001", "Post-mission lifetime beyond the limit",
        ("Confirm the mission parameters (perigee, apogee, mass, area) and which rule applies (FCC 5-year, NASA 25-year).",
         "Run the lifetime estimate at both drag-coefficient bounds."),
        ("Compare with the operator's certified analysis if one exists.",),
        "Mission designer and the licensing authority's debris review.",
        ("Record the shortfall and the design option considered (lower disposal orbit, drag device, propulsive deorbit).",),
        1440,
    ),
    "DAA-001": Playbook(
        "DAA-001", "Well-clear violation observed",
        ("Pull both tracks around the violation; confirm the geometry is not a surveillance artefact (MLAT jump, position source).",
         "Check NMAC proximity and the alert lead time."),
        ("Replay the encounter with the well-clear definitions and compare with the recorded alert level.",
         "If one aircraft is a UAS, check the operator's DAA log."),
        "Safety office; a pattern of violations in one area becomes an airspace study (ST-07, ST-16).",
        ("Record the encounter in the study register.", "Add the cell to the density watch if it is dense at low altitude (DAA-004)."),
        120,
    ),
    "SWX-001": Playbook(
        "SWX-001", "Geomagnetic advisory conditions",
        ("Confirm the NOAA product time and Kp; check that the product is not stale (SWX-004).",
         "List the high-latitude traffic exposed (SWX-005)."),
        ("Look for ADS-B integrity drops (NACp / NIC) in the same window: weather, not spoofing, explains them.",
         "Rescreen conjunctions with fresh elements: drag increases element ageing."),
        "Operators with polar routes and the space weather centre's advisory; the tool only correlates.",
        ("Annotate the audit log with the advisory conditions for the window.",),
        60,
    ),
    "LCH-001": Playbook(
        "LCH-001", "Aircraft inside a launch hazard radius during the window",
        ("Retrieve the published TFR / NOTAM geometry and time for the launch; our radius is a default.",
         "List the closest aircraft with time, altitude and distance."),
        ("Only aircraft inside the real hazard area during the effective time are a coordination failure; the rest are outside the NOTAM.",),
        "Range safety and the ATC facility; after the fact, the launch operator's airspace coordination review.",
        ("Record the count inside the real area and the displacement baseline.",),
        60,
    ),
    "SPC-006": Playbook(
        "SPC-006", "Telemetry packet failed authentication",
        ("Confirm the key for the SPI (AERO_SDLS_KEY_<spi>) matches the link's current key; a re-key explains a burst of failures at one time.",
         "Compare the failed packets' physics (SPC-001..005) with their neighbours: forged content is usually implausible too."),
        ("One failure in a long verified stream is corruption; a run of failures with plausible physics is an injection attempt or a key mismatch.",),
        "The ground segment's link security owner; the mission's security officer for a suspected injection.",
        ("Quarantine the affected packets and rerun the audit on the verified subset.",),
        30,
    ),
    "TFR-001": Playbook(
        "TFR-001", "Aircraft inside a space-operations TFR while in effect",
        ("Read the NOTAM text for the exemptions (range support, ATC-authorised, the operator's own aircraft) and the exact vertical limits.",
         "List each aircraft with first and last time inside, altitude and the number of fixes; match callsigns against the exemptions."),
        ("An aircraft inside the volume during the effective time and not on the exemption list is an entry into a published restriction; a TFR at 'unlimited' ceiling catches overflights the NOTAM may not intend.",),
        "The controlling ARTCC named in the NOTAM and the launch operator's airspace coordinator; after the fact, the FAA's Office of Commercial Space Transportation.",
        ("Record the count inside, the exemption matches and the baseline outside the effective time.",),
        60,
    ),
    "REN-001": Playbook(
        "REN-001", "Aircraft under the track of a decaying object",
        ("Check the tracking authority's reentry prediction (TIP) and any reentry NOTAM; the corridor here is a ground track with a width, not a footprint.",
         "Refetch elements: a set older than two days no longer places a decaying object on the right pass."),
        ("Exposure to a possible footprint is informational until the authority publishes a window; the finding names who would be affected, not who is at risk.",),
        "Dispatch and the ANSP for the flight information regions under the corridor; the tracking authority owns the prediction.",
        ("Annotate the report with the authority's prediction once published and rerun with fresh elements.",),
        240,
    ),
}


def playbook_for(rule_id: str) -> Playbook | None:
    return SPACE_PLAYBOOKS.get(rule_id)


__all__ = ["SPACE_PLAYBOOKS", "SPACE_RULE_CATALOG", "playbook_for"]
