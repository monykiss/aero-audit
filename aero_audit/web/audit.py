"""Append-only audit log of user actions and system events (data/app/audit.jsonl).

Every source change, injection, settings edit, and job is recorded with a timestamp and actor,
so a session can be reconstructed and a reviewer can see who did what to the picture.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

AUDIT_FILE = Path("data/app/audit.jsonl")


class AuditLog:
    def __init__(self, path: str | Path = AUDIT_FILE, keep: int = 5000) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=keep)
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as fh:
                for line in fh:
                    if line.strip():
                        self._recent.append(json.loads(line))
        except (OSError, ValueError):
            pass

    def record(self, action: str, actor: str = "user", **details: Any) -> dict[str, Any]:
        entry = {"ts": time.time(), "actor": actor, "action": action, "details": details}
        with self.lock:
            self._recent.append(entry)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
            except OSError:
                pass
        return entry

    def entries(self, limit: int = 500, action: str | None = None, actor: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            rows = list(self._recent)
        out = []
        ql = (q or "").lower()
        for e in reversed(rows):
            if action and e["action"] != action:
                continue
            if actor and e["actor"] != actor:
                continue
            if ql and ql not in json.dumps(e, default=str).lower():
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def actions(self) -> list[str]:
        with self.lock:
            return sorted({e["action"] for e in self._recent})

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["time", "actor", "action", "details"])
        for e in self.entries(limit=100000):
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(e["ts"])), e["actor"], e["action"], json.dumps(e["details"], default=str)])
        return buf.getvalue()

    def __len__(self) -> int:
        return len(self._recent)
