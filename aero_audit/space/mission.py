"""One launch, every domain: the mission dossier.

A launch is the moment air and space travel share the same volume of sky. This module folds what
the rest of the package already knows about one launch record into a single report with one
manifest: the pad and its spaceport, the airports next door, the space-operations TFRs that cover
the window, the aircraft that were inside the hazard radius and inside the TFR while it was in
effect, the space-weather conditions of the newest product, the objects the catalogue lists from
that launch, and which of those are already decaying. Every section names the module that produced
it, so the dossier is a join, not a new source of truth, and its findings are the joins' findings
(LCH, TFR, SWX, ORB-008) with no new rule id of its own.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit.findings import Finding
from ..knowledge.spaceports import SATCAT_SITES, airports_near, nearest_spaceport

AIRPORT_RADIUS_NM = 50.0


def find_launch(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    """A launch by id, or by a case-insensitive substring of its name, pad or location; the earliest window wins a tie."""
    rows = payload.get("launches", [])
    k = key.lower()
    exact = [r for r in rows if str(r.get("id")) == key]
    if exact:
        return exact[0]
    hits = [r for r in rows if k in f"{r.get('name') or ''} {r.get('pad') or ''} {r.get('location') or ''}".lower()]
    return min(hits, key=lambda r: r.get("window_start") or r.get("net") or "") if hits else None


def _window_date(launch: dict[str, Any]) -> str | None:
    w = launch.get("window_start") or launch.get("net")
    return w[:10] if w else None


def dossier(launch: dict[str, Any], recording: str | Path | None = None, tfr_payload: dict[str, Any] | None = None, swx_payload: dict[str, Any] | None = None,
            satcat: dict[int, dict[str, Any]] | None = None, hazard_nm: float = 50.0, now: float | None = None, max_batches: int | None = None) -> tuple[dict[str, Any], list[Finding]]:
    from . import airspace, launches, spaceweather
    from . import satcat as sc

    ts_now = now if now is not None else time.time()
    fs: list[Finding] = []
    lat, lon = launch.get("pad_lat"), launch.get("pad_lon")
    out: dict[str, Any] = {"launch": {k: launch.get(k) for k in ("id", "name", "provider", "status", "pad", "location", "pad_lat", "pad_lon", "window_start", "window_end", "net", "last_updated")},
                           "generated_at": datetime.fromtimestamp(ts_now, UTC).isoformat(), "sections": []}
    # ground: spaceport and airports
    if lat is not None and lon is not None:
        sp = nearest_spaceport(lat, lon)
        out["spaceport"] = None if sp is None else {"code": sp[0].code, "name": sp[0].name, "country": sp[0].country, "kind": sp[0].kind, "satcat_site": sp[0].satcat_site, "distance_nm": round(sp[1], 1), "note": sp[0].note}
        out["airports_near"] = [{"icao": a.icao, "name": a.name, "major": a.major, "distance_nm": d} for a, d in airports_near(lat, lon, AIRPORT_RADIUS_NM)]
        out["sections"].append("knowledge/spaceports.py")
    # airspace: TFR coverage and traffic inside it
    if tfr_payload is not None:
        cov_summary, cov_fs = airspace.join_launches(tfr_payload, {"launches": [launch]}, now=ts_now)
        out["airspace"] = {"tfrs_covering_window": cov_summary["rows"][0]["tfrs"] if cov_summary["rows"] else [], "us_airspace": cov_summary["rows"][0]["us_airspace"] if cov_summary["rows"] else None,
                           "space_tfrs_in_product": cov_summary["space_tfrs"], "product_fetched_at": tfr_payload.get("fetched_at")}
        fs += cov_fs
        out["sections"].append("space/airspace.py")
        if recording is not None and out["airspace"]["tfrs_covering_window"]:
            ids = {t["notam_id"] for t in out["airspace"]["tfrs_covering_window"]}
            sub = {**tfr_payload, "features": [f for f in tfr_payload.get("features", []) if f.get("notam_id") in ids]}
            tr_summary, tr_fs = airspace.join_traffic(sub, recording, now=ts_now, max_batches=max_batches)
            out["airspace"]["traffic_inside_tfr"] = tr_summary["rows"]
            fs += [f for f in tr_fs if f.rule_id != "TFR-003"]  # the staleness of the product is already reported once above
    # traffic in the hazard radius (the pad-centred join)
    if recording is not None and lat is not None:
        lj_summary, lj_fs = launches.join_traffic({"launches": [launch]}, recording, hazard_nm, now=ts_now, max_batches=max_batches)
        out["traffic"] = {"hazard_nm": hazard_nm, "recording": str(recording), **(lj_summary["rows"][0] if lj_summary["rows"] else {})}
        fs += lj_fs
        out["sections"].append("space/launches.py")
    # space weather of the newest product (its own timestamp says how far it is from the window)
    if swx_payload is not None:
        sw_summary, sw_fs = spaceweather.assess(swx_payload, now=ts_now)
        out["space_weather"] = {k: sw_summary.get(k) for k in ("scales_now", "kp", "icao_advisory_conditions", "product_time", "stale")}
        fs += sw_fs
        out["sections"].append("space/spaceweather.py")
    # catalogued objects from this launch: same day, and the site code when the spaceport has one
    if satcat:
        day = _window_date(launch)
        site = (out.get("spaceport") or {}).get("satcat_site")
        objs = [{"norad": nid, **{k: r.get(k) for k in ("name", "intl", "type", "owner", "launch_site", "decay_date", "perigee_km", "apogee_km", "inclination_deg")}}
                for nid, r in satcat.items() if day and r.get("launch_date") == day and (not site or not r.get("launch_site") or r.get("launch_site") == site)]
        objs.sort(key=lambda r: r["norad"])
        decayed = [o for o in objs if o.get("decay_date")]
        low = [o for o in objs if o.get("perigee_km") is not None and o["perigee_km"] < 200.0 and not o.get("decay_date")]
        out["objects"] = {"count": len(objs), "site_code": site, "site_spaceport": SATCAT_SITES.get(site) if site else None, "rows": objs[:60], "decayed": len(decayed), "low_perigee_on_orbit": low[:20]}
        out["sections"].append("space/satcat.py")
        if objs:
            fs += sc.findings_for_elements([o["norad"] for o in objs], satcat, stream="mission")
    out["findings"] = len(fs)
    out["by_rule"] = {}
    for f in fs:
        out["by_rule"][f.rule_id] = out["by_rule"].get(f.rule_id, 0) + 1
    return out, fs


def load_inputs(launches_file: str | Path | None = None, tfr_file: str | Path | None = None, swx_file: str | Path | None = None, satcat_file: str | Path | None = None) -> dict[str, Any]:
    """Newest cached product for anything not given; None where nothing is cached (the dossier then skips that section)."""
    from ..ingest import tfr as tfr_mod
    from . import launches as ll
    from . import satcat as sc
    from . import spaceweather

    def _json(p: str | Path | None) -> dict[str, Any] | None:
        return json.loads(Path(p).read_text()) if p and Path(p).is_file() else None

    lp = launches_file or ll.latest()
    tp = tfr_file or tfr_mod.latest()
    sp = swx_file or spaceweather.latest()
    cp = satcat_file or sc.latest()
    return {"launches": _json(lp), "tfr": _json(tp), "swx": _json(sp), "satcat": sc.load(cp) if cp else {}, "files": {"launches": lp, "tfr": tp, "swx": sp, "satcat": cp}}


__all__ = ["AIRPORT_RADIUS_NM", "dossier", "find_launch", "load_inputs"]
