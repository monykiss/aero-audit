"""Background jobs (capture, audit, train, evaluate, prune, docs) with status, log, and results.

Each job runs in its own thread, appends human-readable log lines, and stores a JSON-able result.
Finished jobs are persisted to data/app/jobs.json so the Reports and Data pages can show history
across restarts. Job types are a registry, so a new long-running task is one function.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JOBS_FILE = Path("data/app/jobs.json")


@dataclass
class Job:
    id: str
    type: str
    params: dict[str, Any]
    status: str = "queued"  # queued | running | done | failed | cancelled
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    progress: float | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=300))
    result: dict[str, Any] | None = None
    error: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def say(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {msg}")

    def to_dict(self, with_log: bool = True) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "params": self.params, "status": self.status, "created": self.created,
            "started": self.started, "finished": self.finished, "progress": self.progress, "result": self.result,
            "error": self.error, "log": list(self.log) if with_log else list(self.log)[-3:],
        }


JobFn = Callable[[Job, dict[str, Any]], dict[str, Any]]


class JobManager:
    def __init__(self, registry: dict[str, JobFn], persist: Path = JOBS_FILE, on_finish: Callable[[Job], None] | None = None) -> None:
        self.registry = registry
        self.persist = persist
        self.on_finish = on_finish
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._load()

    def submit(self, type_: str, params: dict[str, Any]) -> Job:
        if type_ not in self.registry:
            raise KeyError(f"unknown job type '{type_}'; known: {', '.join(self.registry)}")
        job = Job(id=uuid.uuid4().hex[:10], type=type_, params=params)
        with self.lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{type_}").start()
        return job

    def _run(self, job: Job) -> None:
        job.status, job.started = "running", time.time()
        job.say(f"started {job.type} {json.dumps(job.params, default=str)}")
        try:
            job.result = self.registry[job.type](job, job.params)
            job.status = "cancelled" if job.stop.is_set() else "done"
            job.say("finished" if job.status == "done" else "cancelled")
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            job.say(f"failed: {job.error}")
            job.log.append(traceback.format_exc()[-1500:])
        finally:
            job.finished = time.time()
            self._save()
            if self.on_finish:
                self.on_finish(job)

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        job.stop.set()
        job.say("cancel requested")
        return True

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)[:limit]
        return [j.to_dict(with_log=False) for j in jobs]

    def _save(self) -> None:
        try:
            self.persist.parent.mkdir(parents=True, exist_ok=True)
            with self.lock:
                done = [j.to_dict() for j in self.jobs.values() if j.status in ("done", "failed", "cancelled")]
            done = sorted(done, key=lambda d: d["created"])[-100:]
            self.persist.write_text(json.dumps(done, indent=1, default=str))
        except OSError:
            pass

    def _load(self) -> None:
        try:
            for d in json.loads(self.persist.read_text()):
                j = Job(id=d["id"], type=d["type"], params=d.get("params", {}), status=d["status"], created=d["created"],
                        started=d.get("started"), finished=d.get("finished"), progress=d.get("progress"),
                        result=d.get("result"), error=d.get("error"))
                j.log.extend(d.get("log", []))
                self.jobs[j.id] = j
        except (OSError, ValueError, KeyError):
            pass
