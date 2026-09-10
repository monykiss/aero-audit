"""ADS-B / surveillance threat catalog and detection-coverage matrix.

ADS-B (1090 MHz Extended Squitter) has no authentication and no encryption; a $30 SDR receives
it and a few hundred dollars of transmit hardware can forge it. This catalog enumerates what an
adversary (or a fault) can do, which audit rules would see it, and what actually mitigates it.
Rule ids referenced here are validated against the engine's known rules by the test suite so
the coverage matrix cannot silently drift from the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Coverage(StrEnum):
    COVERED = "covered"  # at least one rule directly detects the behaviour
    PARTIAL = "partial"  # detectable only in some variants / with corroboration
    GAP = "gap"  # nothing in the toolkit detects it today


@dataclass(frozen=True)
class Threat:
    id: str
    name: str
    tactic: str  # injection | modification | deletion | misuse | integrity | supply-chain | privacy
    description: str
    capability_required: str
    impact: str
    likelihood: int  # 1-5 baseline (before observed evidence)
    severity: int  # 1-5 impact if realised
    detected_by: tuple[str, ...]
    coverage: Coverage
    mitigations: tuple[str, ...]
    references: tuple[str, ...] = ()
    scenarios: tuple[str, ...] = ()  # `aero evaluate` scenarios that simulate this threat


THREATS: list[Threat] = [
    Threat(
        "T01", "Ghost aircraft injection", "injection",
        "Adversary transmits ES messages for an aircraft that does not exist, creating a phantom "
        "target on ATC displays, TCAS-like tools, or analytics.",
        "SDR transmitter, line of sight to receivers (~$300 and public code).",
        "False alerts, ATC workload, forced separation manoeuvres, analytics poisoning.",
        2, 4, ("SEC-010", "SEC-014", "SEC-015", "SEC-016", "ML-001"), Coverage.PARTIAL,
        ("Multi-receiver / MLAT corroboration (TDOA physics cannot be forged from one antenna)",
         "Cross-feed corroboration (SEC-015)", "Primary radar fusion where available",
         "New-address burst detection (SEC-016)"),
        ("Costin & Francillon 2012, 'Ghost in the Air(Traffic)'", "Strohmeier et al. 2015 survey"),
        scenarios=("teleport", "ghost_perfect",),
    ),
    Threat(
        "T02", "Position modification of a real aircraft", "modification",
        "Adversary overshadows or replays messages for a genuine ICAO address with altered "
        "position, so the aircraft appears somewhere it is not.",
        "Higher-power transmitter than the aircraft at the receiver, or selective jamming + replay.",
        "Misleading surveillance picture, wrong conflict detection, misdirected response.",
        1, 5, ("SEC-010", "SEC-011", "SEC-014", "SEC-015", "SEC-018"), Coverage.PARTIAL,
        ("Kinematic consistency checks", "Cross-feed and MLAT corroboration",
         "Track continuity checks against filed flight plan"),
        scenarios=("teleport", "altitude_forge", "slow_drift",),
    ),
    Threat(
        "T03", "Velocity / heading falsification", "modification",
        "Only the airborne-velocity message is forged, so reported speed and heading disagree "
        "with what successive positions imply.",
        "Same as T01; simpler because position messages are left alone.",
        "Corrupted trajectory prediction, mis-sequencing, analytics errors.",
        2, 3, ("SEC-011", "SEC-018", "ML-001"), Coverage.COVERED,
        ("Reported-vs-implied speed comparison (SEC-011)", "Sequence-level ML on tracks"),
        scenarios=("velocity_forge",),
    ),
    Threat(
        "T04", "Emergency / hijack squawk spoofing", "injection",
        "Forged 7500/7600/7700 or emergency-status subfield for a real aircraft to trigger "
        "security response, or to mask a real emergency with noise.",
        "SDR transmitter; trivial once T01 works.",
        "Law-enforcement / military response, airspace closure, alert fatigue.",
        1, 5, ("SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-015"), Coverage.COVERED,
        ("Always corroborate via voice/ACARS/CPDLC before response",
         "Cross-feed check that the squawk is seen by independent receivers"),
        scenarios=("squawk_hijack",),
    ),
    Threat(
        "T05", "Aircraft flooding (many ghosts)", "injection",
        "Hundreds of fabricated targets saturate displays, receivers, and downstream systems.",
        "SDR transmitter with message generator.",
        "Denial of surveillance, ATC overload, tooling crashes.",
        1, 5, ("SEC-016", "SEC-017"), Coverage.PARTIAL,
        ("New-address burst detection (SEC-016)", "Rate limiting / sanity caps in consumers",
         "Receiver-level signal metrics (RSSI clustering) for future work"),
    ),
    Threat(
        "T06", "Jamming / message deletion", "deletion",
        "RF jamming or destructive interference removes real aircraft from the picture.",
        "Jammer within range of receivers; illegal and detectable by RF monitoring.",
        "Loss of surveillance, safety degradation.",
        1, 5, ("SEC-017", "OPS-001"), Coverage.PARTIAL,
        ("Coverage-collapse detection (SEC-017)", "Independent receiver networks",
         "Fallback to primary/secondary radar"),
    ),
    Threat(
        "T07", "Replay attack", "injection",
        "Previously recorded genuine messages are re-transmitted later, possibly time-shifted.",
        "Record-and-replay with an SDR.",
        "Stale or duplicated tracks, identity confusion.",
        1, 3, ("SEC-010", "SEC-014", "ML-001"), Coverage.PARTIAL,
        ("Timestamp / track continuity checks", "Cross-feed corroboration"),
        scenarios=("replay",),
    ),
    Threat(
        "T08", "Identity spoofing / impersonation", "misuse",
        "A transponder is configured with another aircraft's ICAO address or a false callsign "
        "(deliberately or by maintenance error).",
        "Physical access to avionics config, or a forged transmitter.",
        "Wrong aircraft tracked, registry mismatches, evasion of monitoring.",
        2, 3, ("SEC-013", "SEC-014", "SEC-020"), Coverage.PARTIAL,
        ("Registry cross-check of ICAO24 vs registration vs type (future work)",
         "Watchlist (SEC-020)", "Duplicate-address detection (SEC-014)"),
    ),
    Threat(
        "T09", "Degraded integrity equipment / misconfiguration", "integrity",
        "Aircraft transmits positions with NIC/NACp/SIL below what the airspace requires; not an "
        "attack, but it lowers the trustworthiness of everything derived from it.",
        "None (fault or non-compliance).",
        "Separation assurance degraded; false anomaly alerts downstream.",
        4, 2, ("SEC-012",), Coverage.COVERED,
        ("Integrity thresholds per 14 CFR 91.227 / EU 1207/2011 (SEC-012)",
         "Trust ledger downgrades positions from low-integrity sources"),
        scenarios=("integrity_degrade",),
    ),
    Threat(
        "T10", "Upstream feed compromise or poisoning", "supply-chain",
        "An aggregator or receiver feeding this tool is compromised, mis-merged, or fed bad data.",
        "Compromise of a community feeder or API; MITM without TLS.",
        "Every downstream decision inherits the poisoned picture.",
        2, 4, ("SEC-015", "SEC-010", "SEC-017"), Coverage.PARTIAL,
        ("Ingest from >= 2 independent feeds and corroborate (SEC-015)", "TLS to all providers",
         "Record raw batches for forensic replay"),
    ),
    Threat(
        "T11", "Privacy misuse of surveillance data", "privacy",
        "Tracking of specific individuals' aircraft (VIP, law enforcement, medical) using the same "
        "open data this tool consumes.",
        "None; the data is public.",
        "Personal safety, operational security of sensitive flights.",
        3, 3, ("SEC-020",), Coverage.PARTIAL,
        ("Respect PIA/LADD programmes; do not publish tracks of protected aircraft",
         "Watchlist as a *protection* list with restricted reporting", "Data retention limits"),
    ),
    Threat(
        "T12", "Toolchain supply chain (dependencies, model weights)", "supply-chain",
        "Malicious or vulnerable dependencies, or tampered model weights, alter detections.",
        "Package registry compromise, typosquatting, unsigned weights.",
        "Silent false negatives or code execution on the analyst host.",
        2, 4, (), Coverage.GAP,
        ("Pinned lockfile (uv.lock)", "Verify weight checksums", "Model card + regression tests",
         "Least-privilege execution; no secrets in recordings"),
    ),
]


def measured_recall(evaluation: dict | None) -> dict[str, dict[str, float]]:
    """{threat_id: {scenario: recall}} from an `aero evaluate` report dict (models/evaluation.json)."""
    if not evaluation:
        return {}
    recall = {r["name"]: float(r["recall"]) for r in evaluation.get("scenarios", [])}
    return {t.id: {sc: recall[sc] for sc in t.scenarios if sc in recall} for t in THREATS if t.scenarios}


def coverage_matrix(evaluation: dict | None = None) -> list[dict[str, str]]:
    measured = measured_recall(evaluation)
    rows = []
    for t in THREATS:
        m = measured.get(t.id, {})
        rows.append({
            "id": t.id,
            "threat": t.name,
            "tactic": t.tactic,
            "coverage": t.coverage.value,
            "rules": ", ".join(t.detected_by) or "-",
            "L": str(t.likelihood),
            "S": str(t.severity),
            "score": str(t.likelihood * t.severity),
            "measured": ", ".join(f"{sc} {v:.0%}" for sc, v in m.items()) or "-",
        })
    return rows


def render_markdown(evaluation: dict | None = None) -> str:
    lines = ["| ID | Threat | Tactic | Coverage | Detecting rules | Measured recall (aero evaluate) | L | S | L*S |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in coverage_matrix(evaluation):
        lines.append(f"| {r['id']} | {r['threat']} | {r['tactic']} | {r['coverage']} | {r['rules']} | {r['measured']} | {r['L']} | {r['S']} | {r['score']} |")
    if evaluation:
        lines.append("")
        lines.append(f"Measured on `{evaluation.get('recording')}` ({evaluation.get('created_at')}); median revisit "
                     f"{(evaluation.get('median_revisit_s') or 0):.0f} s. Recall for one-off manipulations rises with polling rate.")
    return "\n".join(lines)


def load_evaluation(path: str = "models/evaluation.json") -> dict | None:
    import json
    from pathlib import Path

    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
