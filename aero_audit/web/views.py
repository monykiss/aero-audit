"""Read-only summaries for the Space and UAS pages: what is on disk, how fresh it is, and the
latest results of each analysis. Everything is derived from files the CLI and jobs write, so the
pages tell the truth about the evidence rather than recomputing it on every request."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

REPORTS = Path("reports")
CACHE_TTL_S = 5.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _memo(name: str, fn: Any) -> dict[str, Any]:
    """The pages poll; a summary rescans reports and reassesses cached products, so results are held for a few seconds."""
    now = time.time()
    hit = _cache.get(name)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    val = fn()
    _cache[name] = (now, val)
    return val


def _load(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _latest_report(prefix: str) -> tuple[Path | None, dict[str, Any] | None]:
    files = sorted(REPORTS.glob(f"{prefix}_*.json")) if REPORTS.is_dir() else []
    files = [f for f in files if not f.name.endswith(".manifest.json")]
    if not files:
        return None, None
    return files[-1], _load(files[-1])


def _report_rows(prefix: str, limit: int = 8) -> list[dict[str, Any]]:
    files = sorted(REPORTS.glob(f"{prefix}_*.json"), key=lambda f: f.stat().st_mtime, reverse=True) if REPORTS.is_dir() else []
    out = []
    for f in [x for x in files if not x.name.endswith(".manifest.json")][:limit]:
        d = _load(f) or {}
        out.append({"name": f.stem, "mtime": f.stat().st_mtime, "findings": len(d.get("findings", [])), "url": f"/reports/{f.name}"})
    return out


def _findings_of(d: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [{k: f.get(k) for k in ("rule_id", "severity", "title", "callsign", "ts")} for f in (d or {}).get("findings", [])][:40]


def space_summary() -> dict[str, Any]:
    return _memo("space", _space_summary)


def _space_summary() -> dict[str, Any]:
    from ..space import cdm_inbox, launches, orbital, spaceweather

    now = time.time()
    # elements on disk with ages
    elements = []
    if orbital.ELEMENTS_DIR.is_dir():
        for f in sorted(orbital.ELEMENTS_DIR.glob("*.tle"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            prov = _load(f.with_suffix(".tle.provenance.json")) or {}
            elements.append({"file": f.name, "sets": prov.get("sets"), "fetched_at": prov.get("fetched_at"), "age_h": round((now - f.stat().st_mtime) / 3600, 1)})
    conj_path, conj = _latest_report("conjunctions")
    cdm_path, cdm = _latest_report("cdm")
    debris_path, debris = _latest_report("debris")
    mv_path, mv = _latest_report("maneuvers")
    # CDM ledger and events
    ledger_rows = 0
    events: list[dict[str, Any]] = []
    if cdm_inbox.LEDGER.is_file():
        try:
            ledger_rows = sum(1 for _ in cdm_inbox.LEDGER.open())
            events = cdm_inbox.events(cdm_inbox.LEDGER, now=now)[:20]
        except (OSError, ValueError):
            ledger_rows, events = -1, []  # unreadable ledger: shown as -1 rows rather than hiding the section
    # space weather (cached product)
    swx: dict[str, Any] | None = None
    swp = spaceweather.latest()
    if swp:
        payload = _load(swp)
        if payload:
            summ, fs = spaceweather.assess(payload, now=now)
            swx = {"file": swp.name, **summ, "findings_list": [{"rule_id": f.rule_id, "severity": f.severity.value, "title": f.title} for f in fs]}
            from ..space import donki as dk

            dpath = dk.latest()
            if dpath:
                dpay = _load(dpath) or {}
                swx["donki"] = dk.crosscheck(summ, dpay.get("notifications", []), now=now) | {"file": dpath.name, "own_key": dpay.get("own_key")}
    # launches (cached)
    lch: dict[str, Any] | None = None
    lp = launches.latest()
    if lp:
        payload = _load(lp) or {}
        rows = payload.get("launches", [])
        lch = {"file": lp.name, "fetched_at": payload.get("fetched_at"), "mode": payload.get("mode"), "count": len(rows),
               "rows": [{k: r.get(k) for k in ("name", "provider", "status", "net", "window_start", "window_end", "pad", "location")} for r in rows[:15]]}
    # assets, dataset, classifier
    cat = _load(Path("data/space/nasa3d_catalog.json")) or {}
    media = _load(Path("data/space/nasa_media/manifest.json"))
    dataset = _load(Path("data/space/dataset/manifest.json")) or {}
    reg = _load(Path("models/registry.json")) or []
    clf = next((e for e in reversed(reg) if isinstance(e, dict) and "scene_classifier" in str(e.get("model_path", ""))), None) if isinstance(reg, list) else None
    feeds = []
    for name, folder, pattern in (("celestrak elements", orbital.ELEMENTS_DIR, "*.tle"), ("celestrak satcat", Path("data/space/satcat"), "satcat_*.csv"), ("noaa swpc", spaceweather.CACHE_DIR, "swpc_*.json"),
                                  ("launch library 2", launches.CACHE_DIR, "ll2_*.json"), ("faa tfr", Path("data/airspace"), "tfr_*.json"), ("cdm inbox", cdm_inbox.INBOX, "*")):
        files = [f for f in Path(folder).glob(pattern) if f.is_file() and not f.name.endswith(".provenance.json")] if Path(folder).is_dir() else []
        newest = max((f.stat().st_mtime for f in files), default=None)
        feeds.append({"source": name, "cached": len(files), "newest_age_h": None if newest is None else round((now - newest) / 3600, 1), "folder": str(folder)})
    degraded = [k for k, (pth, rep) in {"space_weather": (swp, _latest_report("space_weather")[1]), "launches": (lp, _latest_report("launches")[1])}.items()
                if rep and (rep.get("summary") or {}).get("degraded")]
    from ..space import satcat as sc

    scp = sc.latest()
    satcat_block = None
    if scp:
        cat = sc.load(scp)
        satcat_block = {**sc.summary(cat), "recent_decays": sc.recent_decays(30.0, cat)[:15]}
    from ..ingest import tfr as tfr_mod

    tp = tfr_mod.latest()
    tfr_block = None
    if tp:
        try:
            ts_ = tfr_mod.summary(tp)
            tfr_block = {k: ts_.get(k) for k in ("file", "fetched_at", "features", "with_geometry", "listed_total", "listed_by_type")} | {"active_now": sum(1 for f in tfr_mod.load(tp).get("features", []) if tfr_mod.active(f, now))}
        except (OSError, ValueError):
            tfr_block = {"file": tp.name, "error": "unreadable"}
    return {
        "generated_at": now,
        "tfr": tfr_block,
        "satcat": satcat_block,
        "feeds": feeds,
        "degraded_last_run": degraded,
        "elements": elements,
        "conjunctions": {"report": conj_path.name if conj_path else None, "mtime": conj_path.stat().st_mtime if conj_path else None,
                         "approaches": len((conj or {}).get("screen", {}).get("approaches", [])), "pairs": (conj or {}).get("screen", {}).get("pairs"),
                         "findings": _findings_of(conj)},
        "cdm": {"report": cdm_path.name if cdm_path else None, "assessment": (cdm or {}).get("assessment") or (cdm or {}).get("summary"), "findings": _findings_of(cdm),
                "ledger_rows": ledger_rows, "events": events},
        "debris": {"report": debris_path.name if debris_path else None, "summary": (debris or {}).get("summary"), "findings": _findings_of(debris)},
        "maneuvers": {"report": mv_path.name if mv_path else None, "changes": (mv or {}).get("summary", {}).get("changes", [])[:20], "decaying": (mv or {}).get("summary", {}).get("decaying", [])[:20],
                      "findings": _findings_of(mv)},
        "space_weather": swx,
        "launches": lch,
        "assets": {"nasa3d_files": len(cat.get("files", [])) if isinstance(cat.get("files"), list) else cat.get("count"), "nasa3d_subjects": cat.get("subjects") if not isinstance(cat.get("subjects"), list) else len(cat["subjects"]),
                   "media_items": len(media) if isinstance(media, list) else (len(media.get("items", [])) if isinstance(media, dict) else 0),
                   "dataset_items": len(dataset.get("items", [])), "dataset_classes": dataset.get("counts"),
                   "classifier": None if not clf else {k: clf.get(k) for k in ("trained_at", "sha256", "rows")} | {"accuracy": (clf.get("evaluation") or {}).get("accuracy")}},
        "reports": {k: _report_rows(k) for k in ("conjunctions", "cdm", "debris", "space_weather", "launches", "maneuvers", "tfr", "reentry", "mission")},
    }


def uas_summary() -> dict[str, Any]:
    return _memo("uas", _uas_summary)


def _uas_summary() -> dict[str, Any]:
    wc_path, wc = _latest_report("wellclear")
    risk_path, risk = _latest_report("uas_risk")
    utm_path, utm = _latest_report("utm_check")
    em_path, em = _latest_report("encounter_model")
    s = (wc or {}).get("summary", {})
    return {
        "generated_at": time.time(),
        "wellclear": {"report": wc_path.name if wc_path else None, "mtime": wc_path.stat().st_mtime if wc_path else None,
                      "kpis": {k: s.get(k) for k in ("aircraft_airborne", "flight_hours", "encounter_pairs", "violations", "violations_per_flight_hour", "nmac_proximate", "pairs_with_alert", "median_lead_time_s")},
                      "pairs": (s.get("pairs") or [])[:30], "findings": _findings_of(wc)},
        "risk": {"report": risk_path.name if risk_path else None, "summary": (risk or {}).get("summary"), "findings": _findings_of(risk)},
        "utm": {"report": utm_path.name if utm_path else None, "summary": (utm or {}).get("summary"), "findings": _findings_of(utm)},
        "encounter_model": {"report": em_path.name if em_path else None, "model": ((em or {}).get("summary") or {}).get("model"), "simulation": ((em or {}).get("summary") or {}).get("simulation")},
        "definitions": {"well_clear": "DO-365 Phase 1: DTHR 4000 ft, ZTHR 450 ft, TTHR 35 s", "nmac": "500 ft horizontal / 100 ft vertical",
                        "alert_levels": "preventive (700 ft, 55 s) · corrective (450 ft, 55 s) · warning (450 ft, 25 s)", "risk_ratio": "observed bound; programme limit 0.2"},
        "reports": {k: _report_rows(k) for k in ("wellclear", "uas_risk", "utm_check", "encounter_model")},
    }


__all__ = ["space_summary", "uas_summary"]
