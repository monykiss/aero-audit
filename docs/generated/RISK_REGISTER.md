# Risk register (baseline, generated)

Inherent score = likelihood x impact (1-5 each); rating bands: >=15 critical, >=10 high, >=5 medium. Residual = inherent x (1 - detective control effectiveness from threat coverage). Evidence hits are weighted by measured rule precision and converted to a Wilson 95% lower-bound rate before moving likelihood.

| ID | Risk | Threats | L (base->obs) | I | Inherent | Rating | Ctrl eff. | Residual | Res. rating | Hits (exp. true) | rate / 1,000 (lower bound) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R01 | Surveillance picture poisoned by injected or modified ADS-B | T01, T02, T07 | 2->2 | 5 | 10 | **high** | 0.35 | 7 | medium | 0 (0.0) | 0.0 (0.0) |
| R07 | Privacy harm from tracking sensitive flights | T11 | 3->3 | 3 | 9 | **medium** | 0.35 | 6 | medium | 0 (0) | 0.0 (0.0) |
| R04 | Decisions built on low-integrity positions | T09 | 4->4 | 2 | 8 | **medium** | 0.60 | 3 | low | 0 (0.0) | 0.0 (0.0) |
| R06 | Upstream feed compromise propagates to every consumer | T10 | 2->2 | 4 | 8 | **medium** | 0.35 | 5 | medium | 0 (0.0) | 0.0 (0.0) |
| R08 | Toolchain compromise silently degrades detection | T12 | 2->2 | 4 | 8 | **medium** | 0.00 | 8 | medium | 0 (0) | 0.0 (0.0) |
| R09 | Operational inefficiency (holding, taxi, apron congestion) goes unmeasured | T09 | 4->4 | 2 | 8 | **medium** | 0.60 | 3 | low | 0 (0.0) | 0.0 (0.0) |
| R05 | Identity confusion (wrong aircraft attributed) | T08 | 2->2 | 3 | 6 | **medium** | 0.35 | 4 | low | 0 (0.0) | 0.0 (0.0) |
| R02 | False security response triggered by spoofed emergency codes | T04 | 1->1 | 5 | 5 | **medium** | 0.60 | 2 | low | 0 (0.0) | 0.0 (0.0) |
| R03 | Loss of surveillance through flooding or jamming | T05, T06 | 1->1 | 5 | 5 | **medium** | 0.35 | 3 | low | 0 (0.0) | 0.0 (0.0) |

## Inherent heat map (rows = likelihood, columns = impact)

| L \ I | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 5 |   |   |   |   |   |
| 4 |   | R04, R09 |   |   |   |
| 3 |   |   | R07 |   |   |
| 2 |   |   | R05 | R06, R08 | R01 |
| 1 |   |   |   |   | R02, R03 |

## Controls and mitigations

### R01 Surveillance picture poisoned by injected or modified ADS-B
- Owner: security lead (unassigned)
- Existing controls: Kinematic rules SEC-010/011/014; Cross-feed corroboration SEC-015; Trust ledger
- Planned mitigations: Ingest a third independent feed / MLAT; Sequence models over full tracks; Receiver-level RSSI analysis

### R07 Privacy harm from tracking sensitive flights
- Owner: security lead (unassigned)
- Existing controls: Watchlist protect mode; Passive-only design
- Planned mitigations: Retention limits on recordings; Access control on reports

### R04 Decisions built on low-integrity positions
- Owner: security lead (unassigned)
- Existing controls: SEC-012 integrity thresholds; Trust ledger weighting
- Planned mitigations: Per-operator integrity scorecards; Exclude low-trust tracks from KPIs

### R06 Upstream feed compromise propagates to every consumer
- Owner: security lead (unassigned)
- Existing controls: Two independent feeds; TLS; Raw batch recordings for forensics
- Planned mitigations: Feed health SLOs; Automatic quarantine of a disagreeing feed

### R08 Toolchain compromise silently degrades detection
- Owner: security lead (unassigned)
- Existing controls: uv lockfile; Test suite pins rule behaviour; Model card
- Planned mitigations: Weight checksum verification; Dependency audit in CI; Signed releases

### R09 Operational inefficiency (holding, taxi, apron congestion) goes unmeasured
- Owner: security lead (unassigned)
- Existing controls: OPS-002 holding; OPS-VIS-001 apron capacity; METAR context
- Planned mitigations: Airport geometry for taxi/runway occupancy; Fine-tuned aerial detector

### R05 Identity confusion (wrong aircraft attributed)
- Owner: security lead (unassigned)
- Existing controls: SEC-013 identity gap; SEC-014 duplicate address; SEC-020 watchlist
- Planned mitigations: Registry cross-check ICAO24 <-> registration <-> type

### R02 False security response triggered by spoofed emergency codes
- Owner: security lead (unassigned)
- Existing controls: SEC-001..004 with corroboration guidance; Playbook mandates voice/ACARS confirmation
- Planned mitigations: Automated cross-feed check on every emergency code before alerting

### R03 Loss of surveillance through flooding or jamming
- Owner: security lead (unassigned)
- Existing controls: SEC-016 new-address burst; SEC-017 coverage collapse; OPS-001 stale contact
- Planned mitigations: Alert routing to RF monitoring; Second feed as automatic fallback
