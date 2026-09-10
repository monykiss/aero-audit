"""Scripted demo tour: injects the attack scenarios into the running source on a timeline so a
viewer sees detection, escalation, and the known gaps without touching a button.

The timeline is data (``DEFAULT_SCRIPT``); each step waits, injects one scenario, and narrates
what should happen. The tour loops until stopped, skips steps while no demo-enabled source is
running, and records every injection in the audit log like a manual one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .state import LiveState


@dataclass(frozen=True)
class Step:
    wait_s: float
    kind: str
    batches: int
    narration: str


DEFAULT_SCRIPT: tuple[Step, ...] = (
    Step(6, "teleport", 8, "An aircraft's position is replaced 30 nm north. SEC-010 should fire on its next report and its trust should fall."),
    Step(24, "squawk_7500", 8, "The same feed now shows a hijack code. First report: unconfirmed HIGH. Second: CRITICAL, bypassing the cooldown."),
    Step(24, "altitude_forge", 8, "Barometric altitude forged +6,000 ft while the vertical rate stays flat: SEC-018."),
    Step(24, "velocity_forge", 10, "Reported ground speed halved: SEC-011 when the mismatch clears 150 kt, often ML-001 too."),
    Step(24, "ghost_jumpy", 12, "A fabricated aircraft appears and jumps 20 nm every third report: SEC-010 within three polls."),
    Step(24, "ghost_perfect", 12, "A fabricated aircraft with perfect physics. Nothing fires: this is the known gap cross-feed corroboration closes."),
    Step(24, "flood", 3, "Sixty never-seen addresses appear at once: SEC-016 stream burst."),
    Step(18, "collapse", 2, "Sixty percent of the picture vanishes for two polls: SEC-017 coverage collapse."),
)


class DemoTour:
    def __init__(self, get_state: Callable[[], LiveState | None], on_inject: Callable[[str, str | None, int, str], None] | None = None,
                 script: tuple[Step, ...] = DEFAULT_SCRIPT) -> None:
        self.get_state = get_state
        self.on_inject = on_inject
        self.script = script
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.index = -1
        self.loops = 0
        self.next_at: float | None = None
        self.last: dict[str, Any] | None = None
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        with self.lock:
            if self.running:
                return
            self._stop = threading.Event()
            self.index, self.loops, self.last = -1, 0, None
            self.started_at = time.time()
            self._thread = threading.Thread(target=self._run, daemon=True, name="demo-tour")
            self._thread.start()

    def stop(self) -> None:
        with self.lock:
            self._stop.set()
            self.next_at = None

    def _run(self) -> None:
        while not self._stop.is_set():
            for i, step in enumerate(self.script):
                self.index = i
                self.next_at = time.time() + step.wait_s
                if self._stop.wait(step.wait_s):
                    return
                st = self.get_state()
                if st is None or not st.demo:
                    self.last = {"kind": step.kind, "skipped": "no demo-enabled source", "ts": time.time()}
                    continue
                try:
                    inj = st.inject(step.kind, None, step.batches)
                except ValueError as e:
                    self.last = {"kind": step.kind, "skipped": str(e), "ts": time.time()}
                    continue
                self.last = {"kind": inj.kind, "icao24": inj.icao24, "label": inj.label, "narration": step.narration, "ts": time.time()}
                if self.on_inject:
                    self.on_inject(inj.kind, inj.icao24, inj.remaining, step.narration)
            self.loops += 1

    def status(self) -> dict[str, Any]:
        running = self.running
        step = self.script[self.index] if 0 <= self.index < len(self.script) else None
        return {
            "running": running, "step": self.index + 1 if running and step else 0, "steps": len(self.script),
            "loops": self.loops, "next_kind": step.kind if running and step else None,
            "next_in_s": max(0.0, round(self.next_at - time.time(), 1)) if running and self.next_at else None,
            "last": self.last, "started_at": self.started_at if running else None,
            "script": [{"kind": s.kind, "wait_s": s.wait_s, "narration": s.narration} for s in self.script],
        }


__all__ = ["DEFAULT_SCRIPT", "DemoTour", "Step"]
