"""Space-operations airspace against what actually flew: the published TFR geometry (ingest/tfr.py)
joined to recorded traffic and to launch windows.

Launch Library gives the window and the pad; the FAA gives the restricted volume and its effective
time; the recording gives the aircraft. Three questions follow. Did any aircraft fly inside an
active space-operations TFR (TFR-001, safety)? Is there a launch window at a US pad with no
space-operations TFR published for it (TFR-002, data quality: usually "not issued yet", sometimes
"the list is filtered", occasionally a coordination gap)? Is the TFR product itself stale while
one of its restrictions is in effect (TFR-003, data quality)?

The NOTAM text stays authoritative: ATC-authorised aircraft (range support, the launch operator's
own) may be inside a TFR legitimately, so TFR-001 lists the aircraft and leaves the judgement to
the facility. Passive only.
"""

from __future__ import annotations

import calendar
import time
from pathlib import Path
from typing import Any

from ..audit.findings import Category, Finding, Severity
from ..ingest import tfr as tfr_mod

LOOKAHEAD_S = 72 * 3600.0  # a launch this far out without a TFR is not yet a gap
PAD_SLACK_NM = 30.0  # a TFR whose centroid lies this close to a pad counts as covering it even if the pad is at the edge
_US_MARKERS = ("usa", "united states", "puerto rico", "guam", "marshall islands")


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def _geometry_features(payload: dict[str, Any], types: tuple[str, ...] | None) -> list[dict[str, Any]]:
    feats = [f for f in payload.get("features", []) if f.get("polygon") or f.get("circle")]
    if types:
        want = {t.upper() for t in types}
        feats = [f for f in feats if (f.get("type") or "").upper() in want]
    return feats


def _stale_finding(payload: dict[str, Any], feats: list[dict[str, Any]], ts_now: float, stream: str) -> Finding | None:
    fetched = payload.get("fetched_at")
    try:
        fetched_ts = calendar.timegm(time.strptime(fetched, "%Y%m%dT%H%M%SZ")) if fetched else None
    except (TypeError, ValueError):
        fetched_ts = None
    if fetched_ts is None or ts_now - fetched_ts <= tfr_mod.STALE_S:
        return None
    live = [f["notam_id"] for f in feats if tfr_mod.active(f, ts_now)]
    if not live:
        return None
    return Finding(rule_id="TFR-003", title=f"TFR product {(ts_now - fetched_ts) / 3600:.0f} h old while {len(live)} restriction(s) are in effect", severity=Severity.LOW,
                   category=Category.DATA_QUALITY, ts=ts_now, evidence={"stream": stream, "fetched_at": fetched, "active": live[:20]},
                   controls=["14 CFR 91.143"], recommendation="Refresh the TFR list; space-operations restrictions are amended and cancelled at short notice.")


def join_traffic(payload: dict[str, Any], recording: str | Path, now: float | None = None, max_batches: int | None = None,
                 types: tuple[str, ...] | None = tfr_mod.SPACE_TYPES) -> tuple[dict[str, Any], list[Finding]]:
    """Aircraft inside each TFR's geometry (and below its ceiling) while it was in effect, with the traffic inside the same
    geometry outside the effective time as the displacement baseline."""
    from ..ingest.replay import iter_recording

    ts_now = now if now is not None else time.time()
    feats = _geometry_features(payload, types)
    inside: dict[str, dict[str, Any]] = {}
    baseline: dict[str, set[str]] = {}
    rec_t0: float | None = None
    rec_t1: float | None = None
    batches = 0
    for b in iter_recording(recording):
        if max_batches and batches >= max_batches:
            break
        batches += 1
        for sv in b.states:
            if sv.lat is None or sv.lon is None or sv.on_ground:
                continue
            rec_t0 = sv.ts if rec_t0 is None else min(rec_t0, sv.ts)
            rec_t1 = sv.ts if rec_t1 is None else max(rec_t1, sv.ts)
            for f in feats:
                if not tfr_mod.inside(sv.lat, sv.lon, f, sv.baro_alt_ft):
                    continue
                key = f["notam_id"]
                if tfr_mod.active(f, sv.ts):
                    row = inside.setdefault(key, {"aircraft": {}})
                    ac = row["aircraft"].setdefault(sv.icao24, {"icao24": sv.icao24, "callsign": (sv.callsign or "").strip(), "first_ts": sv.ts, "last_ts": sv.ts, "alt_ft": sv.baro_alt_ft, "samples": 0})
                    ac["last_ts"] = max(ac["last_ts"], sv.ts)
                    ac["samples"] += 1
                    ac["alt_ft"] = sv.baro_alt_ft if sv.baro_alt_ft is not None else ac["alt_ft"]
                else:
                    baseline.setdefault(key, set()).add(sv.icao24)
    out: list[Finding] = []
    rows = []
    for f in feats:
        key = f["notam_id"]
        e0, e1 = f.get("effective_ts"), f.get("expire_ts")
        overlaps = rec_t0 is not None and rec_t1 is not None and (e0 is None or e0 <= rec_t1) and (e1 is None or e1 >= rec_t0)
        acs = sorted(inside.get(key, {}).get("aircraft", {}).values(), key=lambda a: -a["samples"])
        rows.append({"notam_id": key, "type": f.get("type"), "place": f.get("place"), "facility": f.get("facility"), "effective": f.get("effective"), "expire": f.get("expire"),
                     "upper_ft": f.get("upper_ft"), "overlaps_recording": overlaps, "aircraft_inside_while_active": len(acs), "aircraft_inside_outside_effective_time": len(baseline.get(key, set()))})
        if acs:
            out.append(Finding(rule_id="TFR-001", title=f"{len(acs)} aircraft inside space-operations TFR {key} ({f.get('place') or f.get('facility')}) while in effect", severity=Severity.MEDIUM,
                               category=Category.SAFETY, ts=acs[0]["first_ts"], icao24=acs[0]["icao24"], callsign=acs[0]["callsign"] or None,
                               evidence={"stream": Path(str(recording)).name, "notam_id": key, "type": f.get("type"), "effective": [f.get("effective"), f.get("expire")],
                                         "limits_ft": [f.get("lower_ft"), f.get("upper_ft")], "aircraft": acs[:15], "baseline_outside_effective_time": len(baseline.get(key, set()))},
                               controls=["14 CFR 91.143", "FAA JO 7210.3 (TFRs)"],
                               recommendation="Check each aircraft against the NOTAM's exemptions (range support, ATC-authorised); the rest are entries into a published space-operations restriction."))
    stale = _stale_finding(payload, feats, ts_now, Path(str(recording)).name)
    if stale:
        out.append(stale)
    summary = {"recording": str(recording), "tfr_features": len(payload.get("features", [])), "with_geometry": len(feats), "types": list(types) if types else None,
               "overlapping": sum(1 for r in rows if r["overlaps_recording"]), "rows": rows, "findings": len(out)}
    return summary, out


def _is_us(launch: dict[str, Any]) -> bool:
    loc = f"{launch.get('location') or ''} {launch.get('pad') or ''}".lower()
    return any(m in loc for m in _US_MARKERS)


def covering(feats: list[dict[str, Any]], launch: dict[str, Any], slack_nm: float = PAD_SLACK_NM) -> list[dict[str, Any]]:
    """Space-operations TFRs whose geometry contains the pad (or whose centroid is within the slack) and whose effective
    period overlaps the launch window."""
    w0, w1 = _ts(launch.get("window_start")) or _ts(launch.get("net")), _ts(launch.get("window_end")) or _ts(launch.get("net"))
    lat, lon = launch.get("pad_lat"), launch.get("pad_lon")
    if w0 is None or lat is None or lon is None:
        return []
    w1 = (w1 or w0) + 1.0
    out = []
    for f in feats:
        e0, e1 = f.get("effective_ts"), f.get("expire_ts")
        if (e0 is not None and e0 > w1) or (e1 is not None and e1 < w0):
            continue
        c = f.get("centroid")
        near = c is not None and tfr_mod._dist_nm(lat, lon, c[0], c[1]) <= slack_nm
        if tfr_mod.inside(lat, lon, f) or near:
            out.append(f)
    return out


def join_launches(payload: dict[str, Any], launches_payload: dict[str, Any], now: float | None = None,
                  lookahead_s: float = LOOKAHEAD_S) -> tuple[dict[str, Any], list[Finding]]:
    """Every launch with a window and a pad: which space-operations TFRs cover it; TFR-002 for a US launch inside the
    look-ahead that none does (a launch abroad is out of the FAA's airspace and is only reported)."""
    ts_now = now if now is not None else time.time()
    feats = _geometry_features(payload, tfr_mod.SPACE_TYPES)
    out: list[Finding] = []
    rows = []
    for launch in launches_payload.get("launches", []):
        w0 = _ts(launch.get("window_start")) or _ts(launch.get("net"))
        if w0 is None or launch.get("pad_lat") is None:
            continue
        w1 = (_ts(launch.get("window_end")) or w0) + 1.0
        cov = covering(feats, launch)
        us = _is_us(launch)
        soon = w1 >= ts_now and w0 - ts_now <= lookahead_s
        rows.append({"id": launch.get("id"), "name": launch.get("name"), "pad": launch.get("pad"), "location": launch.get("location"), "status": launch.get("status"),
                     "window_start": launch.get("window_start"), "window_end": launch.get("window_end"), "us_airspace": us, "within_lookahead": soon,
                     "tfrs": [{"notam_id": f["notam_id"], "place": f.get("place"), "effective": f.get("effective"), "expire": f.get("expire"), "upper_ft": f.get("upper_ft")} for f in cov]})
        if us and soon and not cov and (launch.get("status") or "").lower() not in ("hold", "tbd", "scrubbed", "failure", "success", "partial failure"):
            out.append(Finding(rule_id="TFR-002", title=f"{launch['name']}: no space-operations TFR published for {launch.get('pad') or 'the pad'} in its window", severity=Severity.LOW,
                               category=Category.DATA_QUALITY, ts=w0, evidence={"stream": "tfr", "launch": launch.get("name"), "pad": [launch.get("pad_lat"), launch.get("pad_lon")],
                                                                                 "window": [launch.get("window_start"), launch.get("window_end")], "space_tfrs_in_product": len(feats)},
                               controls=["14 CFR 91.143"],
                               recommendation="TFRs for launches are usually issued one to three days ahead; refetch closer to the window before reading this as a coordination gap."))
    stale = _stale_finding(payload, feats, ts_now, "tfr")
    if stale:
        out.append(stale)
    summary = {"launches": len(rows), "covered": sum(1 for r in rows if r["tfrs"]), "us_uncovered_soon": sum(1 for r in rows if r["us_airspace"] and r["within_lookahead"] and not r["tfrs"]),
               "space_tfrs": len(feats), "rows": rows, "findings": len(out)}
    return summary, out


def displacement(products: list[str | Path], recordings: list[str | Path], max_batches: int | None = None) -> dict[str, Any]:
    """How much traffic a space-operations restriction actually displaced: for every restriction seen in any product
    (newest geometry per NOTAM id) and every recording, the rate of distinct aircraft inside the volume per minute while it
    was in effect against the rate in the same volume outside its effective time. A ratio near zero means the airspace
    was clear; near one means the restriction was not observed to change traffic; None means one of the two windows was
    not recorded. This is a study over history, so it grows with every cached product and recording."""
    from ..ingest.replay import iter_recording

    feats: dict[str, dict[str, Any]] = {}
    for p in products:
        try:
            payload = tfr_mod.load(p)
        except (OSError, ValueError):
            continue
        for f in _geometry_features(payload, tfr_mod.SPACE_TYPES):
            feats[f["notam_id"]] = f  # products are read oldest to newest, so the newest geometry wins
    rows = []
    for rec in recordings:
        inside_during: dict[str, set[str]] = {k: set() for k in feats}
        inside_outside: dict[str, set[str]] = {k: set() for k in feats}
        t_during: dict[str, set[int]] = {k: set() for k in feats}
        t_outside: dict[str, set[int]] = {k: set() for k in feats}
        batches = 0
        for b in iter_recording(rec):
            if max_batches and batches >= max_batches:
                break
            batches += 1
            for sv in b.states:
                if sv.lat is None or sv.lon is None or sv.on_ground:
                    continue
                for key, f in feats.items():
                    minute = int(sv.ts // 60)
                    if tfr_mod.active(f, sv.ts):
                        t_during[key].add(minute)
                        if tfr_mod.inside(sv.lat, sv.lon, f, sv.baro_alt_ft):
                            inside_during[key].add(sv.icao24)
                    else:
                        t_outside[key].add(minute)
                        if tfr_mod.inside(sv.lat, sv.lon, f, sv.baro_alt_ft):
                            inside_outside[key].add(sv.icao24)
        for key, f in feats.items():
            md, mo = len(t_during[key]), len(t_outside[key])
            rd = len(inside_during[key]) / md if md else None
            ro = len(inside_outside[key]) / mo if mo else None
            ratio = None if rd is None or ro is None or ro == 0 else round(rd / ro, 3)
            rows.append({"notam_id": key, "place": f.get("place"), "recording": Path(str(rec)).name, "minutes_during": md, "minutes_outside": mo,
                         "aircraft_inside_during": len(inside_during[key]), "aircraft_inside_outside": len(inside_outside[key]),
                         "rate_during_per_min": None if rd is None else round(rd, 3), "rate_outside_per_min": None if ro is None else round(ro, 3), "displacement_ratio": ratio})
    scored = [r["displacement_ratio"] for r in rows if r["displacement_ratio"] is not None]
    return {"restrictions": len(feats), "products": len(products), "recordings": len(recordings), "rows": rows, "pairs_with_both_windows": len(scored),
            "median_displacement_ratio": sorted(scored)[len(scored) // 2] if scored else None}


__all__ = ["LOOKAHEAD_S", "PAD_SLACK_NM", "covering", "displacement", "join_launches", "join_traffic"]
