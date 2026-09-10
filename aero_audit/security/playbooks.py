"""Response playbooks: what an analyst does when a rule fires.

A finding without a next action is noise. Each playbook gives triage steps (minutes), how to
verify it is real, when to escalate, and what containment looks like for a *passive* tool
(we never touch aircraft or ATC systems; containment means protecting downstream consumers).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Playbook:
    rule_id: str
    title: str
    triage: tuple[str, ...]
    verify: tuple[str, ...]
    escalate: str
    contain: tuple[str, ...]
    sla_minutes: int


_SQUAWK = Playbook(
    "SEC-00x", "Emergency / interference squawk",
    (
        (
            "The rule itself marks a single-fix code as unconfirmed and escalates on the second consecutive fix; "
            "a transient code between identical normal codes is usually a mis-dial (seen live: one poll of 7500 on a "
            "descending airliner, back to its assigned code on the next poll)."
        ),
     "Pull callsign, type, origin/destination from the feed and the flight plan if available.",
     "Check whether independent feeds (OpenSky vs adsb.lol) both report the code (SEC-015)."),
    ("7500 must be treated as real until ATC/AOC confirms otherwise.",
     "A spoofed squawk usually rides on a track that also fails SEC-010/SEC-015."),
    "7500: immediate notification to the responsible ATC unit / security duty officer. "
    "7700/7600: notify ops duty manager; log for safety reporting.",
    ("Do not broadcast or publish the finding externally.",
     "Mark the aircraft as 'under review' so downstream dashboards do not auto-alert repeatedly."),
    5,
)

PLAYBOOKS: dict[str, Playbook] = {
    "SEC-001": _SQUAWK, "SEC-002": _SQUAWK, "SEC-003": _SQUAWK, "SEC-004": _SQUAWK,
    "SEC-010": Playbook(
        "SEC-010", "Kinematically impossible position jump",
        ("Open the track: was there one bad fix or a sustained new position?",
         "Check position_source: MLAT outliers are common and benign; pure ADS-B jumps are not.",
         "Look for a duplicate ICAO24 (SEC-014) around the same time."),
        ("Run `aero corroborate` on the region: a real aircraft is seen at the same place by both feeds.",
         "If the feed shows a jump and then returns to the original track, suspect a receiver merge glitch."),
        "Escalate to the security lead when the jump is corroborated by only one receiver network "
        "and coincides with SEC-014/SEC-016 activity.",
        ("Drop the aircraft to low trust (TrustLedger) so analytics ignore it until cleared.",
         "Preserve the raw recording for forensics."),
        15,
    ),
    "SEC-011": Playbook(
        "SEC-011", "Reported vs implied speed mismatch",
        ("Check dt: mismatches at dt < 10 s are dominated by timestamp jitter.",
         "Compare over 3+ fixes: a persistent bias suggests forged velocity messages."),
        ("Cross-feed corroboration; MLAT-derived speed if available.",),
        "Escalate only if persistent and combined with another SEC finding.",
        ("Downgrade trust; exclude from speed-based analytics.",),
        30,
    ),
    "SEC-012": Playbook(
        "SEC-012", "Integrity / accuracy below minimums",
        ("Note NIC/NACp/SIL values and aircraft type; GA aircraft with older GPS are the usual case.",
         "Check persistence across the flight (occurrences)."),
        ("A single aircraft with SIL 0 all flight = equipment issue; many aircraft at once = receiver/feed issue.",),
        "Persistent SIL 0 / NIC < 5 on commercial traffic: report to the operator / regulator channel.",
        ("Downgrade trust for the aircraft; weight its positions lower in analytics.",),
        1440,
    ),
    "SEC-013": Playbook(
        "SEC-013", "No flight ID at altitude",
        ("Check registration / type from the feed; many GA and military flights legitimately omit Flight ID.",),
        ("Persistent across the flight and paired with SEC-012 suggests misconfiguration.",),
        "Not escalated alone.",
        ("Log only.",),
        1440,
    ),
    "SEC-014": Playbook(
        "SEC-014", "Duplicate ICAO24 address",
        ("Identify both positions and separation; check if one is MLAT/TIS-B.",
         "Look up the address in the registry: does the type/registration match either track?"),
        ("Two genuine aircraft with the same address = misconfigured transponder (happens after maintenance).",
         "One genuine + one ghost = T01/T08."),
        "Escalate if the duplicate persists > 5 min or is near sensitive airspace.",
        ("Split into two synthetic track ids for analytics; low trust on both.",),
        15,
    ),
    "SEC-015": Playbook(
        "SEC-015", "Cross-feed position disagreement",
        ("Check the time offset between feeds; the tool dead-reckons but large dt reduces confidence.",
         "Which feed is the outlier? Compare with a third source if available."),
        ("Consistent disagreement on one aircraft = spoof or bad feeder; on many aircraft = a feed-wide problem (T10).",),
        "Feed-wide disagreement: escalate to whoever owns the data pipeline immediately.",
        ("Prefer the feed with MLAT corroboration; quarantine the other until resolved.",),
        15,
    ),
    "SEC-016": Playbook(
        "SEC-016", "New-address burst",
        ("How many new addresses, over what area, in how many seconds?",
         "Do the new addresses have plausible registrations/types (feed enrichment) or none?"),
        (
            (
                "Genuine bursts happen when a receiver comes online or at shift changes at large hubs; "
                "they have realistic kinematics. Ghost floods usually do not."
            ),
        ),
        "Escalate as suspected flooding (T05) if the burst also trips SEC-010/SEC-011 on many aircraft.",
        ("Cap ingestion; raise trust threshold for alerts; preserve raw batches.",),
        10,
    ),
    "SEC-017": Playbook(
        "SEC-017", "Coverage collapse",
        ("Did the provider return an error/empty payload (tooling) or a real drop (RF)?",
         "Compare with the second provider: a drop on only one feed is a feeder outage, not jamming."),
        ("RF jamming affects all receivers in an area across feeds simultaneously.",),
        "Simultaneous collapse across independent feeds near an airport: escalate to the security lead.",
        ("Switch analytics to the healthy feed; annotate the gap in reports.",),
        10,
    ),
    "SEC-018": Playbook(
        "SEC-018", "Altitude inconsistent with vertical rate",
        ("Check position_source; MLAT/TIS-B altitude relays lag and jump.",
         "Compare implied vs reported vertical rate over the next fixes: a forgery persists, a glitch reverts."),
        ("Cross-feed corroboration of altitude; Mode C from a second receiver.",),
        "Escalate with SEC-010/011 on the same aircraft as a suspected modification (T02).",
        ("Lower trust; exclude the aircraft from vertical-separation analytics until cleared.",),
        15,
    ),
    "SEC-020": Playbook(
        "SEC-020", "Watchlist match",
        ("Read the watchlist reason; follow the handling instructions attached to the entry.",),
        ("Confirm the identity via registration + type, not just address.",),
        "Per the watchlist entry's severity.",
        ("Restrict reporting for *protection* entries (VIP/medical) to the authorised audience.",),
        5,
    ),
    "OPS-001": Playbook(
        "OPS-001", "Coverage gap", ("Map the gaps over a day; cluster by sector.",),
        ("Persistent gaps in the same sector = receiver hole, not an aircraft issue.",),
        "Not escalated; feeds into coverage planning.", ("None.",), 10080,
    ),
    "OPS-002": Playbook(
        "OPS-002", "Holding / orbiting",
        ("Check METAR for the destination: weather holding is expected.",
         "Aggregate minutes held per hour and per runway configuration."),
        ("Holding without weather cause across many arrivals = arrival-rate / flow-management issue.",),
        "Weekly review with ops / ATFM stakeholders.",
        ("None (process improvement, not containment).",), 10080,
    ),
    "OPS-003": Playbook(
        "OPS-003", "Low-altitude orbiting", ("Check type/registration: trainers, helicopters, survey aircraft.",),
        ("Recurring at the same airfield = pattern traffic; over a city = survey or law-enforcement.",),
        "Not escalated.", ("Log only; use for density / noise analysis.",), 10080,
    ),
    "OPS-004": Playbook(
        "OPS-004", "Persistent level-off away from selected altitude",
        ("Check whether the aircraft later moves to the selected altitude (pending clearance).",),
        ("A level bust shows as *reaching* an unselected altitude, not sitting at one; treat as low priority.",),
        "Only if combined with a TCAS/RA report from another source.",
        ("None.",), 1440,
    ),
    "OPS-005": Playbook(
        "OPS-005", "VFR code above FL180",
        ("Confirm the aircraft is in US airspace (rule is US-specific).",),
        ("Persistent 1200 at FL350 is almost always a transponder not re-set after departure.",),
        "Not escalated.", ("Log only.",), 1440,
    ),
    "SAF-003": Playbook(
        "SAF-003", "Excessive vertical rate",
        ("Compare reported vs implied vertical rate; disagreement means bad data, not a dive.",),
        ("Fighter / aerobatic types legitimately exceed thresholds.",),
        "If implied and reported agree and the type is commercial: notify safety office.",
        ("None.",), 60,
    ),
    "SAF-004": Playbook(
        "SAF-004", "Close proximity (indicative)",
        ("Check both fix ages and sources; stale or MLAT positions dead-reckon badly.",
         "Look at tracks: converging, parallel, or formation?"),
        ("ATC radar / TCAS are authoritative; ADS-B derived separation is a screening signal.",),
        "Only if both fixes are fresh ADS-B, tracks converge, and vertical spacing is under 600 ft: notify the safety office.",
        ("None (screening); aggregate by sector for airspace design review.",), 30,
    ),
    "ML-001": Playbook(
        "ML-001", "Kinematic anomaly (model)",
        ("Read top_deviations_z: which features drove the score?",
         "Check whether a hard rule also fired on the same aircraft."),
        ("Benign anomalies (helicopters, aerobatics, survey flights) recur by type; add them to training.",),
        "Never escalate on ML alone.",
        ("Retrain with the reviewed window; track precision over time in the model card.",), 1440,
    ),
    "OPS-VIS-001": Playbook(
        "OPS-VIS-001", "Apron zone over capacity",
        ("Confirm detections visually; COCO models miss small aircraft and box wings.",),
        ("Persistent congestion across frames, not one image.",),
        "Weekly review with apron management.", ("None.",), 10080,
    ),
}


def playbook_for(rule_id: str) -> Playbook | None:
    return PLAYBOOKS.get(rule_id)


def render_markdown() -> str:
    out: list[str] = []
    seen: set[int] = set()
    for pb in PLAYBOOKS.values():
        if id(pb) in seen:
            continue
        seen.add(id(pb))
        ids = [k for k, v in PLAYBOOKS.items() if v is pb]
        out += [f"## {', '.join(ids)}: {pb.title}", "", f"SLA to triage: {pb.sla_minutes} min", "", "Triage:"]
        out += [f"1. {s}" for s in pb.triage]
        out += ["", "Verify:"] + [f"- {s}" for s in pb.verify]
        out += ["", f"Escalate: {pb.escalate}", "", "Contain:"] + [f"- {s}" for s in pb.contain] + [""]
    return "\n".join(out)
