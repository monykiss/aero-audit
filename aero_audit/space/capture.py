"""Launch-window capture: record the airspace around a pad while its window is open, then run the
joins on what was recorded.

The seam analyses (LCH-001, TFR-001, the displacement study) are only as real as the recordings
that overlap actual launch windows, and a live session records wherever the operator happens to be
looking. This module closes that gap without anyone watching: given the cached launch list, it
finds a launch whose window is open (or opens within the lead time), records the adsb.lol feed
around the pad until the window closes (plus a tail), and then writes the pad-radius join, the
space-operations TFR join and the mission dossier for that launch. A state file under
`data/recordings/` remembers what was captured so a launch is not recorded twice, and a capture is
capped in duration so a scrubbed launch with a day-long window cannot hold a worker forever.

Passive only: the feed is read; nothing is transmitted. adsb.lol is keyless; the pad radius is
bounded by the feed's 250 nm limit.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Region

LEAD_S = 2 * 3600.0
TAIL_S = 3600.0
RADIUS_NM = 100.0
INTERVAL_S = 15.0
MAX_DURATION_S = 4 * 3600.0
RECORDINGS_DIR = Path("data/recordings")
STATE_PATH = RECORDINGS_DIR / "launch_captures.json"
SKIP_STATUS = ("scrubbed", "failure", "success", "partial failure", "tbd", "tbc")


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def slug(launch: dict[str, Any]) -> str:
    base = str(launch.get("id") or launch.get("name") or "launch")
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-")[:48].lower()


def window(launch: dict[str, Any]) -> tuple[float, float] | None:
    w0 = _ts(launch.get("window_start")) or _ts(launch.get("net"))
    w1 = _ts(launch.get("window_end")) or _ts(launch.get("net"))
    if w0 is None:
        return None
    return w0, max(w1 or w0, w0)


def due(launches: list[dict[str, Any]], now: float, lead_s: float = LEAD_S, tail_s: float = TAIL_S) -> list[dict[str, Any]]:
    """Launches with a pad whose window is open, opens within the lead time, or closed less than the tail ago."""
    out = []
    for launch in launches:
        if launch.get("pad_lat") is None or launch.get("pad_lon") is None:
            continue
        if (launch.get("status") or "").lower() in SKIP_STATUS:
            continue
        w = window(launch)
        if w and w[0] - lead_s <= now <= w[1] + tail_s:
            out.append(launch)
    return sorted(out, key=lambda r: window(r)[0])  # type: ignore[index]


def region_for(launch: dict[str, Any], radius_nm: float = RADIUS_NM) -> Region:
    return Region(f"launch-{slug(launch)}", f"launch window: {launch.get('name')} ({launch.get('pad')})", float(launch["pad_lat"]), float(launch["pad_lon"]), min(max(radius_nm, 20.0), 250.0))


def load_state(path: str | Path = STATE_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def save_state(state: dict[str, Any], path: str | Path = STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1, sort_keys=True))


def pick(launches: list[dict[str, Any]], state: dict[str, Any], now: float, lead_s: float = LEAD_S, tail_s: float = TAIL_S) -> dict[str, Any] | None:
    """The earliest due launch that is not already fully captured: a launch whose last segment ended after its window
    closed (plus tail) is done; one whose segment was cut by the duration cap can get another segment."""
    for launch in due(launches, now, lead_s, tail_s):
        rec = state.get(slug(launch)) or {}
        w = window(launch)
        if rec.get("segments") and w and rec["segments"][-1].get("ended_ts", 0) >= w[1] + tail_s - 1:
            continue
        if rec.get("running"):
            continue
        return launch
    return None


async def _record(provider: Any, region: Region, until_ts: float, interval_s: float, path: Path, stop: Any = None, max_batches: int | None = None) -> dict[str, Any]:
    from ..stream.poller import JsonlRecorder, stream_batches

    rec = JsonlRecorder(path)
    batches = 0
    states = 0
    try:
        async for b in stream_batches(provider, region, interval_s, max(until_ts - time.time(), 1.0), rec):
            batches += 1
            states += len(b.states)
            if (stop is not None and stop.is_set()) or (max_batches and batches >= max_batches):
                break
    finally:
        rec.close()
    return {"batches": batches, "state_vectors": states}


def run(now: float | None = None, launches_payload: dict[str, Any] | None = None, provider_factory: Any = None, lead_s: float = LEAD_S, tail_s: float = TAIL_S,
        radius_nm: float = RADIUS_NM, interval_s: float = INTERVAL_S, max_duration_s: float = MAX_DURATION_S, stop: Any = None, dry_run: bool = False,
        max_batches: int | None = None, state_path: str | Path = STATE_PATH, out_dir: str | Path = "reports", say: Any = None) -> dict[str, Any]:
    """One scheduler tick: pick a due launch, record its window, then join. Returns what happened, including nothing."""
    from ..ingest import make_provider
    from . import launches as ll

    ts_now = now if now is not None else time.time()
    if launches_payload is None:
        p = ll.latest()
        launches_payload = json.loads(Path(p).read_text()) if p else {"launches": []}
    launches = launches_payload.get("launches", [])
    state = load_state(state_path)
    due_now = due(launches, ts_now, lead_s, tail_s)
    launch = pick(launches, state, ts_now, lead_s, tail_s)
    summary: dict[str, Any] = {"launches_cached": len(launches), "due": [{"name": r.get("name"), "pad": r.get("pad"), "window_start": r.get("window_start"), "window_end": r.get("window_end")} for r in due_now],
                               "picked": launch.get("name") if launch else None, "dry_run": dry_run}
    if launch is None or dry_run:
        return summary
    w = window(launch)
    assert w is not None
    until = min(w[1] + tail_s, ts_now + max_duration_s)
    key = slug(launch)
    region = region_for(launch, radius_nm)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts_now))
    path = RECORDINGS_DIR / f"adsblol_{region.key}_{stamp}.jsonl"
    entry = state.setdefault(key, {"launch": launch.get("name"), "id": launch.get("id"), "pad": launch.get("pad"), "segments": []})
    entry["running"] = True
    save_state(state, state_path)
    if say:
        say(f"capturing {launch.get('name')} around {launch.get('pad')} ({region.radius_nm:g} nm) until {datetime.fromtimestamp(until, UTC).isoformat()}")
    provider = (provider_factory or make_provider)("adsblol")
    try:
        stats = asyncio.run(_record(provider, region, until, interval_s, path, stop, max_batches))
    finally:
        entry["running"] = False
        entry["segments"].append({"recording": str(path), "started_ts": ts_now, "ended_ts": time.time(), "batches": None})
        save_state(state, state_path)
    entry["segments"][-1]["batches"] = stats["batches"]
    save_state(state, state_path)
    reports = _join(launch, path, launches_payload, out_dir) if stats["batches"] else {}
    entry["segments"][-1]["reports"] = reports
    save_state(state, state_path)
    summary.update({"recording": str(path), **stats, "region": {"lat": region.lat, "lon": region.lon, "radius_nm": region.radius_nm}, "until": until, "reports": reports})
    if say:
        say(f"captured {stats['batches']} batches, {stats['state_vectors']} state vectors; reports {list(reports)}")
    return summary


def _join(launch: dict[str, Any], recording: Path, launches_payload: dict[str, Any], out_dir: str | Path) -> dict[str, str]:
    """The payoff: the pad-radius join, the TFR join (newest product) and the mission dossier, each with a manifest."""
    from ..audit.generic_report import write_generic
    from ..ingest import tfr as tfr_mod
    from . import airspace, mission, satcat, spaceweather
    from . import launches as ll

    out: dict[str, str] = {}
    key = slug(launch)
    single = {"launches": [launch]}
    summary, fs = ll.join_traffic(single, recording, ll.HAZARD_NM)
    out["launches"] = str(write_generic(out_dir, f"launches_capture_{key}", "summary", summary, fs, inputs={"launches": None, "recording": recording})["json"])
    tp = tfr_mod.latest()
    tfr_payload = tfr_mod.load(tp) if tp else None
    if tfr_payload:
        s2, f2 = airspace.join_traffic(tfr_payload, recording)
        out["tfr"] = str(write_generic(out_dir, f"tfr_capture_{key}", "summary", {"traffic": s2}, f2, inputs={"tfr": tp, "recording": recording})["json"])
    sp = spaceweather.latest()
    swx = json.loads(Path(sp).read_text()) if sp else None
    d, f3 = mission.dossier(launch, recording, tfr_payload, swx, satcat.load() or None, ll.HAZARD_NM)
    out["mission"] = str(write_generic(out_dir, f"mission_{key}", "dossier", d, f3, inputs={k: v for k, v in {"tfr": tp, "product": sp, "recording": recording}.items() if v})["json"])
    return out


__all__ = ["INTERVAL_S", "LEAD_S", "MAX_DURATION_S", "RADIUS_NM", "STATE_PATH", "TAIL_S", "due", "load_state", "pick", "region_for", "run", "save_state", "slug", "window"]
