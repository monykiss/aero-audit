"""End-to-end live check of every keyless space path: fetch, parse, assess, in one command.

The credential probe (`aero accounts --probe`) proves a service answers; this proves the tool's own
clients work against it today: CelesTrak elements into the SGP4 screen, the SATCAT into identity and
decay lookups, NOAA scales into ICAO conditions, Launch Library into windows, DONKI into the cross-check.
Fetchers are injectable so the test suite runs it offline; the report lists what each step produced and
how long it took, and it never needs an account.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

STEPS = ("elements", "satcat", "space_weather", "launches", "tfr", "donki", "nws_alerts", "utm_contracts")


def run(fetchers: dict[str, Callable[[], Path]] | None = None, group: str = "stations", max_sets: int = 60) -> dict[str, Any]:
    from ..ingest import nws_alerts
    from ..ingest import tfr as tfr_mod
    from ..uas import utm
    from . import donki, launches, satcat, spaceweather
    from .orbital import fetch_group, parse_tle, screen

    f = {"elements": lambda: asyncio.run(fetch_group(group)), "satcat": lambda: asyncio.run(satcat.fetch()), "space_weather": lambda: asyncio.run(spaceweather.fetch()),
         "launches": lambda: asyncio.run(launches.fetch("upcoming", 10)), "donki": lambda: asyncio.run(donki.fetch(3)),
         "nws_alerts": lambda: asyncio.run(nws_alerts.fetch(("Flood Warning", "Flash Flood Warning"))),
         "tfr": lambda: asyncio.run(tfr_mod.fetch(tfr_mod.SPACE_TYPES, max_details=6)),
         "utm_contracts": lambda: asyncio.run(utm.fetch_domains())[0]} | (fetchers or {})
    rows: list[dict[str, Any]] = []
    ctx: dict[str, Any] = {}

    def step(name: str, work: Callable[[], dict[str, Any]]) -> None:
        t0 = time.perf_counter()
        try:
            out = work()
            rows.append({"step": name, "ok": True, "seconds": round(time.perf_counter() - t0, 2), **out})
        except Exception as e:  # noqa: BLE001 - one failing feed must not hide the others
            rows.append({"step": name, "ok": False, "seconds": round(time.perf_counter() - t0, 2), "error": f"{type(e).__name__}: {str(e)[:160]}"})

    def _elements() -> dict[str, Any]:
        p = f["elements"]()
        sets = parse_tle(Path(p).read_text())
        res = screen(sets, None, 2.0, 10.0, max_sets=max_sets)
        ctx["norad"] = [s.norad_id for s in sets[:max_sets]]
        return {"file": Path(p).name, "sets": len(sets), "pairs": res["pairs"], "approaches": len(res["approaches"]), "co_moving": len(res["co_moving"]), "keyless": True}

    def _satcat() -> dict[str, Any]:
        p = f["satcat"]()
        cat = satcat.load(p)
        ids = ctx.get("norad", [25544])
        named = sum(1 for n in ids if cat.get(n))
        decayed = len(satcat.findings_for_elements(ids, cat))
        return {"file": Path(p).name, "objects": len(cat), "named_of_screened": f"{named}/{len(ids)}", "orb_008": decayed, "recent_decays_30d": len(satcat.recent_decays(30, cat)), "keyless": True}

    def _weather() -> dict[str, Any]:
        p = f["space_weather"]()
        summary, fs = spaceweather.assess(json.loads(Path(p).read_text()))
        ctx["swx"] = summary
        return {"file": Path(p).name, "scales": summary["scales_now"], "kp": summary["kp"], "conditions": summary["icao_advisory_conditions"], "findings": [x.rule_id for x in fs], "keyless": True}

    def _launches() -> dict[str, Any]:
        p = f["launches"]()
        rows_ = json.loads(Path(p).read_text()).get("launches", [])
        return {"file": Path(p).name, "launches": len(rows_), "next": rows_[0].get("name") if rows_ else None, "keyless": True}

    def _tfr() -> dict[str, Any]:
        p = f["tfr"]()
        s = tfr_mod.summary(p)
        return {"file": Path(p).name, "space_ops_tfrs": s["features"], "with_geometry": s["with_geometry"], "listed_total": s["listed_total"], "keyless": True}

    def _donki() -> dict[str, Any]:
        p = f["donki"]()
        pay = json.loads(Path(p).read_text())
        cc = donki.crosscheck(ctx.get("swx", {"icao_advisory_conditions": {}}), pay.get("notifications", []))
        return {"file": Path(p).name, "notifications": len(pay.get("notifications", [])), "own_key": pay.get("own_key"), "agreement": {k: v["agreement"] for k, v in cc["effects"].items()}, "keyless": True}

    def _nws() -> dict[str, Any]:
        p = f["nws_alerts"]()
        s = nws_alerts.summary(p)
        return {"file": Path(p).name, "extents": s["features"], "by_event": s["by_event"], "keyless": True}

    def _utm() -> dict[str, Any]:
        p = f["utm_contracts"]()
        doc = utm.load_document(p)
        defs = doc.get("definitions") or (doc.get("components") or {}).get("schemas") or {}
        good = json.loads(Path("data/samples/utm_position_sample.json").read_text()) if Path("data/samples/utm_position_sample.json").is_file() else None
        errs = utm.validate(good, utm.schema_for(doc, "Position"), doc) if good is not None and "Position" in defs else None
        return {"file": Path(p).name, "definitions": len(defs), "sample_position_errors": None if errs is None else len(errs), "keyless": True}

    for name, work in (("elements", _elements), ("satcat", _satcat), ("space_weather", _weather), ("launches", _launches), ("tfr", _tfr), ("donki", _donki), ("nws_alerts", _nws), ("utm_contracts", _utm)):
        step(name, work)
    ok = sum(1 for r in rows if r["ok"])
    return {"steps": rows, "passed": ok, "total": len(rows), "all_keyless": True, "spacetrack_used": False, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


__all__ = ["STEPS", "run"]
