"""Source manager: one active traffic source (replay or live) that can be started, stopped, and
swapped at runtime without restarting the server. Designed to hold several later."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit.engine import AuditEngine
from ..audit.findings import Severity
from ..config import Region, get_region, parse_regions
from ..ingest import make_provider
from ..ingest.metar import fetch_metars, summarize_metar
from ..ingest.replay import iter_recording
from ..models import Batch
from ..stream import JsonlRecorder, stream_batches
from .state import LiveState

SETTINGS_FILE = Path("data/app/settings.json")
DEFAULT_SETTINGS: dict[str, Any] = {
    "demo": True, "alert_log": "logs/alerts.jsonl", "alert_webhook": "", "retention_days": 30,
    "model": "models/kinematic_iforest.joblib", "watchlist": "data/watchlist.json", "last_source": None,
}


def load_settings() -> dict[str, Any]:
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


def build_engine(settings: dict[str, Any]) -> AuditEngine:
    from ..alerts import Alerter, JsonlSink, WebhookSink
    from ..security import Watchlist

    ml = None
    mp = Path(settings.get("model") or "")
    if mp.is_file():
        from ..ml import KinematicAnomalyModel

        ml = KinematicAnomalyModel.load(mp)
    wl = None
    wp = Path(settings.get("watchlist") or "")
    if wp.is_file():
        wl = Watchlist.load(wp)
    sinks: list[Any] = []
    if settings.get("alert_webhook"):
        sinks.append(WebhookSink(settings["alert_webhook"]))
    if settings.get("alert_log"):
        sinks.append(JsonlSink(settings["alert_log"]))
    alerter = Alerter(sinks, Severity.HIGH) if sinks else None
    return AuditEngine(ml_model=ml, watchlist=wl, alerter=alerter)


class SourceManager:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.state: LiveState | None = None
        self.threads: list[threading.Thread] = []
        self.lock = threading.Lock()
        self.label = ""
        self.params: dict[str, Any] = {}

    # ---- lifecycle -------------------------------------------------------------------------
    def stop(self) -> None:
        with self.lock:
            if self.state:
                self.state.stop.set()
            self.state = None
            self.threads = []
            self.label = ""
            self.params = {}

    def start_replay(self, recording: str | Path, speed: float = 8.0, demo: bool | None = None) -> LiveState:
        self.stop()
        path = Path(recording)
        if not path.is_file():
            raise FileNotFoundError(f"recording not found: {path}")
        demo = self.settings["demo"] if demo is None else demo
        region = path.stem.split("_")[1] if "_" in path.stem else "?"
        state = LiveState(build_engine(self.settings), "replay", f"replay:{path.name}", region, demo)
        t = threading.Thread(target=self._replay_loop, args=(state, path, speed), daemon=True, name="src-replay")
        with self.lock:
            self.state, self.threads, self.label = state, [t], f"Replay {path.name} at {speed:g}x"
            self.params = {"mode": "replay", "recording": str(path), "speed": speed, "demo": demo}
        t.start()
        return state

    def start_live(self, provider: str, region: str, radius: float | None = None, interval: float = 12.0,
                   demo: bool | None = None, record: bool = True) -> LiveState:
        self.stop()
        demo = self.settings["demo"] if demo is None else demo
        regions = parse_regions(region, radius)
        label = "+".join(r.key for r in regions)
        state = LiveState(build_engine(self.settings), "live", provider, label, demo)
        rec = None
        if record:
            Path("data/recordings").mkdir(parents=True, exist_ok=True)
            rec = JsonlRecorder(Path("data/recordings") / f"{provider}_{label}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl")
        t = threading.Thread(target=self._live_loop, args=(state, provider, regions, interval, rec), daemon=True, name="src-live")
        m = threading.Thread(target=self._metar_loop, args=(state, regions), daemon=True, name="src-metar")
        fa = threading.Thread(target=self._faa_loop, args=(state,), daemon=True, name="src-faa")
        with self.lock:
            self.state, self.threads = state, [t, m, fa]
            self.label = f"Live {provider} over {label}" + (f" ({radius:g} nm)" if radius else "")
            self.params = {"mode": "live", "provider": provider, "region": region, "radius": radius, "interval": interval, "demo": demo}
        t.start()
        m.start()
        fa.start()
        return state

    @staticmethod
    def _faa_loop(state: LiveState, every_s: float = 300.0) -> None:
        from ..ingest.faa_status import fetch_status

        while not state.stop.is_set():
            try:
                st = asyncio.run(fetch_status())
                with state.lock:
                    state.faa_status = st
            except Exception as e:  # noqa: BLE001
                state.errors.append(f"faa status: {type(e).__name__}: {e}")
            state.stop.wait(every_s)

    # ---- loops -----------------------------------------------------------------------------
    @staticmethod
    def _replay_loop(state: LiveState, path: Path, speed: float) -> None:
        offset = 0.0
        while not state.stop.is_set():
            first = last = prev = None
            for b in iter_recording(path):
                if state.stop.is_set():
                    return
                if prev is not None:
                    time.sleep(max(0.0, min(30.0, (b.ts - prev) / max(speed, 0.1))))
                prev = b.ts
                first = b.ts if first is None else first
                last = b.ts
                shifted = Batch(ts=b.ts + offset, provider=b.provider, region=b.region,
                                states=[s.model_copy(update={"ts": s.ts + offset}) for s in b.states]) if offset else b
                state.ingest(shifted, latency_ms=None)
            if first is None:
                return
            offset += (last - first) + 60.0
            state.reset_tracks()

    @staticmethod
    def _live_loop(state: LiveState, provider_name: str, regions: list[Region], interval: float,
                   recorder: JsonlRecorder | None) -> None:
        async def main() -> None:
            p = make_provider(provider_name)
            try:
                async for b in stream_batches(p, regions, interval, None, recorder):
                    if state.stop.is_set():
                        break
                    state.ingest(b, latency_ms=max(0.0, (time.time() - b.ts) * 1000.0))
            except Exception as e:  # noqa: BLE001
                state.errors.append(f"live source stopped: {type(e).__name__}: {e}")
            finally:
                await p.aclose()
                if recorder:
                    recorder.close()

        asyncio.run(main())

    @staticmethod
    def _metar_loop(state: LiveState, regions: list[Region], every_s: float = 600.0) -> None:
        from ..knowledge.airports import MAJOR

        stations = [s for r in regions for s in r.metar_stations]
        if any(r.custom_bbox for r in regions):  # whole-country boxes: the busiest airports instead of a few presets
            stations = [a.icao for a in MAJOR]
        if not stations:
            return
        while not state.stop.is_set():
            try:
                ms = asyncio.run(fetch_metars(stations))
                with state.lock:
                    state.metars = [{"station": m.get("icaoId"), "summary": summarize_metar(m), "raw": m.get("rawOb"),
                                     "wind": f"{m.get('wdir', '?')}/{m.get('wspd', '?')}", "visib": m.get("visib"),
                                     "cover": m.get("cover"), "temp": m.get("temp")} for m in ms]
            except Exception as e:  # noqa: BLE001
                state.errors.append(f"metar: {type(e).__name__}: {e}")
            state.stop.wait(every_s)

    # ---- status ----------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        st = self.state
        if st is None:
            return {"active": False}
        with st.lock:
            b = st.last_batch
            return {
                "active": True, "mode": st.mode, "provider": st.provider, "region": st.region, "label": self.label,
                "params": self.params, "demo": st.demo, "batches": st.batches, "tracked": len(b.states) if b else 0,
                "batch_ts": b.ts if b else None,
                "last_ingest_age_s": round(time.time() - st.last_ingest_wall, 1) if st.last_ingest_wall else None,
                "uptime_s": round(time.time() - st.started_at), "errors": list(st.errors)[-3:],
                "findings": len(st.engine.findings),
            }


def region_catalog() -> list[dict[str, Any]]:
    """Regions and groups with a `kind` the UI uses to group the picker and choose defaults."""
    from ..config import GROUP_NAMES, GROUPS, REGIONS

    us_hubs = set(GROUPS["usa-hubs"]) | {"bos"}
    out = [{"key": k, "name": GROUP_NAMES[k], "kind": "group", "members": list(v), "providers": ["adsblol"],
            "interval": 10, "radius_nm": 250} for k, v in GROUPS.items()]
    for r in REGIONS.values():
        if r.custom_bbox:
            kind, providers, interval = "box", ["opensky"], 60
        elif r.endpoint:
            kind, providers, interval = "global", ["adsblol"], 15
        elif r.key in us_hubs:
            kind, providers, interval = "us", ["adsblol", "opensky"], 12
        else:
            kind, providers, interval = "world", ["adsblol", "opensky"], 12
        out.append({"key": r.key, "name": r.name, "lat": r.lat, "lon": r.lon, "radius_nm": r.radius_nm,
                    "metar_stations": list(r.metar_stations), "endpoint": r.endpoint, "kind": kind,
                    "providers": providers, "interval": interval, "bbox": r.custom_bbox})
    return out


__all__ = ["SourceManager", "build_engine", "get_region", "load_settings", "region_catalog", "save_settings"]
