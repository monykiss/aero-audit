"""Launch telemetry audit: the same idea as the ADS-B physics rules, applied to a speed/altitude
stream from a webcast overlay, a flight-data export, or a simulation.

Input: rows of (t_s, speed, altitude) in seconds, metres per second and kilometres, straight
from a CSV (``t_s,speed_mps,altitude_km``; ``speed_kmh`` and ``altitude_m`` are accepted and
converted). Output: SPC-* findings that reuse the toolkit's Finding model, so they rank, report,
and map to controls like every other finding.

Rules (thresholds are module constants, tunable like the ADS-B ones):
- SPC-001 implausible acceleration: |dv/dt| beyond MAX_ACCEL_MPS2 over a sample pair.
- SPC-002 altitude / speed inconsistency: implied vertical speed exceeds the reported total speed
  (plus tolerance), which no trajectory can do.
- SPC-003 telemetry dropout: a gap longer than MAX_GAP_S in an otherwise dense stream.
- SPC-004 time regression or duplicate timestamp: replayed or spliced samples.
- SPC-005 altitude discontinuity: altitude jumps more than MAX_ALT_JUMP_KM in one step.

Every rule is a *signal*: overlays round, streams stutter, and staging produces sharp but real
changes. The evidence block carries the numbers so a reviewer can judge.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity

MAX_ACCEL_MPS2 = 60.0        # ~6 g sustained; crewed launches stay under ~4.5 g, boosters under ~6 g
MAX_GAP_S = 10.0             # webcast telemetry updates several times a second; 10 s is a real hole
MIN_DT_S = 0.05              # pairs closer than this are overlay jitter, not physics
MAX_ALT_JUMP_KM = 5.0        # per sample step
VS_TOLERANCE_MPS = 150.0     # overlay rounding + timing skew allowance for implied vertical speed
MIN_SPEED_FOR_VS_MPS = 100.0 # ignore the pad and the first seconds


@dataclass(frozen=True)
class TelemetryPoint:
    t_s: float
    speed_mps: float
    altitude_km: float


def load_csv(path: str | Path) -> list[TelemetryPoint]:
    rows: list[TelemetryPoint] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
        t_key = next((fields[k] for k in ("t_s", "t", "time", "time_s", "seconds") if k in fields), None)
        v_key = next((fields[k] for k in ("speed_mps", "speed_kmh", "speed", "velocity_mps", "velocity_kmh") if k in fields), None)
        a_key = next((fields[k] for k in ("altitude_km", "altitude_m", "altitude", "alt_km", "alt_m") if k in fields), None)
        if not (t_key and v_key and a_key):
            raise ValueError(f"need time, speed and altitude columns; got {reader.fieldnames}")
        for r in reader:
            try:
                t, v, a = float(r[t_key]), float(r[v_key]), float(r[a_key])
            except (TypeError, ValueError):
                continue
            if "kmh" in v_key.lower():
                v /= 3.6
            if a_key.lower().endswith("_m") or a_key.lower() == "altitude_m":
                a /= 1000.0
            rows.append(TelemetryPoint(t, v, a))
    return rows


def load_telemetry_json(path: str | Path) -> list[TelemetryPoint]:
    """The public launch-telemetry layout (shahar603/Telemetry-Data, Unlicense): parallel arrays ``time`` (s), ``velocity`` (m/s),
    ``altitude`` (km). Rows with a missing value are dropped, not interpolated."""
    d = json.loads(Path(path).read_text())
    t, v, a = d.get("time"), d.get("velocity"), d.get("altitude")
    if not (isinstance(t, list) and isinstance(v, list) and isinstance(a, list)):
        raise TypeError("expected parallel lists 'time', 'velocity', 'altitude'")
    out = []
    for ts, vel, alt in zip(t, v, a, strict=False):
        if ts is None or vel is None or alt is None:
            continue
        out.append(TelemetryPoint(float(ts), float(vel), float(alt)))
    return out


def load_any(path: str | Path) -> list[TelemetryPoint]:
    p = Path(path)
    return load_telemetry_json(p) if p.suffix.lower() == ".json" else load_csv(p)


def _finding(rule: str, sev: Severity, cat: Category, title: str, ts: float, evidence: dict[str, Any],
             controls: list[str], rec: str) -> Finding:
    return Finding(rule_id=rule, title=title, severity=sev, category=cat, ts=ts, evidence=evidence, controls=controls,
                   recommendation=rec, callsign=evidence.get("stream"))


def audit_telemetry(points: list[TelemetryPoint], stream: str = "telemetry") -> list[Finding]:
    out: list[Finding] = []
    if len(points) < 2:
        return out
    prev = points[0]
    for p in points[1:]:
        dt = p.t_s - prev.t_s
        ev: dict[str, Any] = {"stream": stream, "t_prev_s": prev.t_s, "t_s": p.t_s, "dt_s": round(dt, 3),
                              "speed_prev_mps": prev.speed_mps, "speed_mps": p.speed_mps,
                              "alt_prev_km": prev.altitude_km, "alt_km": p.altitude_km}
        if dt <= 0:
            out.append(_finding("SPC-004", Severity.HIGH, Category.SECURITY, "Telemetry time regression or duplicate sample", p.t_s, ev,
                                ["NIST SP 800-53 SI-7", "CCSDS 133.0-B (packet sequencing)"],
                                "Treat as a spliced or replayed stream until the source timeline is verified."))
            prev = p
            continue
        if dt > MAX_GAP_S:
            out.append(_finding("SPC-003", Severity.MEDIUM, Category.DATA_QUALITY, f"Telemetry dropout of {dt:.1f} s", p.t_s, ev,
                                ["CCSDS 133.0-B", "NIST SP 800-53 AU-12"],
                                "Do not interpolate across the gap; check the source for a feed switch or loss of signal."))
        if dt >= MIN_DT_S:
            accel = (p.speed_mps - prev.speed_mps) / dt
            ev["accel_mps2"] = round(accel, 2)
            if abs(accel) > MAX_ACCEL_MPS2:
                out.append(_finding("SPC-001", Severity.HIGH, Category.SECURITY, f"Implausible acceleration {accel:+.0f} m/s² ({accel / 9.80665:+.1f} g)", p.t_s, ev,
                                    ["NIST SP 800-53 SI-7", "vehicle structural limits"],
                                    "Verify against an independent source (range tracking, flight-data export); overlays can glitch at staging."))
            d_alt_m = (p.altitude_km - prev.altitude_km) * 1000.0
            implied_vs = d_alt_m / dt
            ev["implied_vertical_speed_mps"] = round(implied_vs, 1)
            if p.speed_mps >= MIN_SPEED_FOR_VS_MPS and abs(implied_vs) > p.speed_mps + VS_TOLERANCE_MPS:
                out.append(_finding("SPC-002", Severity.HIGH, Category.SECURITY, "Altitude change faster than the reported total speed allows", p.t_s, ev,
                                    ["NIST SP 800-53 SI-7"],
                                    "One of the two channels is wrong; compare with the caption timeline and any second source."))
            if abs(p.altitude_km - prev.altitude_km) > MAX_ALT_JUMP_KM:
                out.append(_finding("SPC-005", Severity.MEDIUM, Category.DATA_QUALITY, f"Altitude discontinuity of {p.altitude_km - prev.altitude_km:+.1f} km in one step", p.t_s, ev,
                                    ["CCSDS 133.0-B"], "Check for unit or decimal errors in the overlay reader."))
        prev = p
    return out


def summarize(points: list[TelemetryPoint], findings: list[Finding]) -> dict[str, Any]:
    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule_id] = by_rule.get(f.rule_id, 0) + 1
    speeds = [p.speed_mps for p in points]
    alts = [p.altitude_km for p in points]
    return {"samples": len(points), "t_start_s": points[0].t_s if points else None, "t_end_s": points[-1].t_s if points else None,
            "max_speed_mps": max(speeds) if speeds else None, "max_altitude_km": max(alts) if alts else None,
            "findings": len(findings), "by_rule": by_rule}


def write_report(points: list[TelemetryPoint], findings: list[Finding], out_dir: str | Path, name: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    s = summarize(points, findings)
    jp = out / f"{name}.json"
    jp.write_text(json.dumps({"summary": s, "findings": [f.model_dump() for f in findings]}, indent=2, default=str))
    lines = [f"# Launch telemetry audit: {name}", "", f"- Samples: {s['samples']} from t={s['t_start_s']} s to t={s['t_end_s']} s",
             f"- Max speed: {s['max_speed_mps']} m/s · max altitude: {s['max_altitude_km']} km", f"- Findings: **{s['findings']}** {s['by_rule']}", ""]
    for f in findings:
        lines += [f"## [{f.severity.value.upper()}] {f.rule_id} {f.title}", f"- t = {f.ts} s", f"- Evidence: `{json.dumps(f.evidence, default=str)}`",
                  f"- Recommendation: {f.recommendation}", ""]
    mp = out / f"{name}.md"
    mp.write_text("\n".join(lines))
    return jp, mp


__all__ = ["MAX_ACCEL_MPS2", "MAX_ALT_JUMP_KM", "MAX_GAP_S", "TelemetryPoint", "audit_telemetry", "load_csv", "summarize", "write_report"]
