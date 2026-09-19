"""Scheduled intake: submit named jobs at fixed intervals while the app runs.

Configured by ``AERO_SCHEDULE`` (``job=seconds,job=seconds``; for example
``cdm_inbox=600,space_weather=900,launches=3600``) or by ``[schedule]`` in aero.toml. Every run
is an ordinary job, so it shows in the job list, the audit log and the metrics like any other
work, and the scheduler itself is one thread that only submits. Network jobs are skipped, with a
log line, while a schedule is marked ``offline``; nothing here ever posts to a remote system.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from .. import observability as obs

ENV = "AERO_SCHEDULE"
MIN_INTERVAL_S = 60.0
NETWORK_JOBS = {"space_weather", "launches", "spacetrack_pull", "conjunctions", "satcat", "tfr", "launch_capture"}
# politeness floors per job: Launch Library 2 allows 15 requests/hour keyless, Space-Track asks for restraint, CelesTrak caches for hours
MIN_INTERVALS: dict[str, float] = {"launches": 300.0, "spacetrack_pull": 600.0, "conjunctions": 300.0, "space_weather": 120.0, "satcat": 3600.0, "digest": 3600.0, "tfr": 300.0, "reentry": 300.0, "mission": 300.0, "launch_capture": 300.0}
MAX_BACKOFF_FACTOR = 8


def parse_schedule(text: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, secs = part.partition("=")
        name = name.strip()
        try:
            out[name] = max(float(secs), MIN_INTERVAL_S, MIN_INTERVALS.get(name, 0.0))
        except ValueError:
            continue
    return out


class Scheduler:
    def __init__(self, submit: Any, known: set[str], schedule: dict[str, float] | None = None, offline: bool = False, is_running: Any = None) -> None:
        self.submit = submit
        self.is_running = is_running or (lambda name: False)
        self.failures: dict[str, int] = {}
        self.deferred: dict[str, int] = {}
        self.schedule = {k: v for k, v in (schedule if schedule is not None else parse_schedule(os.getenv(ENV))).items() if k in known}
        self.unknown = sorted(k for k in (schedule if schedule is not None else parse_schedule(os.getenv(ENV))) if k not in known)
        self.offline = offline
        self.next_run: dict[str, float] = {k: time.time() + 5.0 for k in self.schedule}
        self.last_run: dict[str, float] = {}
        self.runs: dict[str, int] = dict.fromkeys(self.schedule, 0)
        self.skipped: dict[str, int] = dict.fromkeys(self.schedule, 0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.schedule or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="aero-schedule", daemon=True)
        self._thread.start()
        obs.log_event("schedule.start", jobs={k: int(v) for k, v in self.schedule.items()}, offline=self.offline)

    def stop(self) -> None:
        self._stop.set()

    def tick(self, now: float | None = None) -> list[str]:
        """Submit whatever is due; returns the job types submitted (used directly by tests and by the loop)."""
        now = time.time() if now is None else now
        fired: list[str] = []
        for name, every in self.schedule.items():
            if now < self.next_run.get(name, 0.0):
                continue
            if self.is_running(name):  # never stack a second instance of a job that is still running (a slow feed must not pile up)
                self.deferred[name] = self.deferred.get(name, 0) + 1
                self.next_run[name] = now + min(every, 60.0)
                obs.log_event("schedule.defer", "info", job=name, reason="still running")
                continue
            self.next_run[name] = now + every * min(2 ** self.failures.get(name, 0), MAX_BACKOFF_FACTOR)
            if self.offline and name in NETWORK_JOBS:
                self.skipped[name] += 1
                obs.log_event("schedule.skip", "info", job=name, reason="offline")
                continue
            try:
                self.submit(name, {"scheduled": True})
                self.runs[name] += 1
                self.last_run[name] = now
                fired.append(name)
                obs.METRICS.inc("aero_scheduled_jobs_total", job=name)
            except Exception as e:  # noqa: BLE001 - a bad submission must not kill the scheduler thread
                obs.log_event("schedule.error", "warning", job=name, error=f"{type(e).__name__}: {str(e)[:120]}")
        return fired

    def report(self, name: str, ok: bool) -> None:
        """Outcome feedback from the job manager: consecutive failures double the interval (capped), success resets it."""
        if name not in self.schedule:
            return
        if ok:
            self.failures.pop(name, None)
        else:
            self.failures[name] = min(self.failures.get(name, 0) + 1, 3)
            factor = min(2 ** self.failures[name], MAX_BACKOFF_FACTOR)
            self.next_run[name] = max(self.next_run.get(name, 0.0), time.time() + self.schedule[name] * factor)  # takes effect now, not at the next fire
            obs.log_event("schedule.backoff", "warning", job=name, failures=self.failures[name], factor=factor)

    def _loop(self) -> None:
        while not self._stop.wait(5.0):
            self.tick()

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {"env": ENV, "offline": self.offline, "network_jobs": sorted(NETWORK_JOBS), "unknown": self.unknown,
                "min_intervals": MIN_INTERVALS,
                "entries": [{"job": k, "every_s": int(v), "effective_s": int(v * min(2 ** self.failures.get(k, 0), MAX_BACKOFF_FACTOR)), "next_in_s": max(0, int(self.next_run.get(k, now) - now)),
                             "runs": self.runs.get(k, 0), "skipped_offline": self.skipped.get(k, 0), "deferred_running": self.deferred.get(k, 0), "failures": self.failures.get(k, 0),
                             "last_run": self.last_run.get(k)} for k, v in self.schedule.items()]}


__all__ = ["ENV", "MAX_BACKOFF_FACTOR", "MIN_INTERVALS", "MIN_INTERVAL_S", "NETWORK_JOBS", "Scheduler", "parse_schedule"]
