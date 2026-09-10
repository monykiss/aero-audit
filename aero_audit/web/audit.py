"""Append-only, hash-chained audit log of user actions and system events (data/app/audit.jsonl).

Every source change, injection, settings edit, and job is recorded with a timestamp and actor.
Each entry carries a sequence number, the SHA-256 of the previous entry, and its own SHA-256 over
the canonical JSON of everything else. Editing, deleting, or reordering a line breaks the chain,
and ``verify()`` says exactly where. This is tamper-evident, not tamper-proof: the goal is that a
reviewer can prove the record they were handed is the record that was written.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

AUDIT_FILE = Path("data/app/audit.jsonl")
GENESIS = "0" * 64


def _canonical(entry: dict[str, Any]) -> bytes:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(entry)).hexdigest()


def verify_file(path: str | Path) -> dict[str, Any]:
    """Walk a log file and check every link. Entries written before chaining (no ``hash``) are
    counted as legacy and skipped; the chain restarts at genesis after them."""
    path = Path(path)
    out: dict[str, Any] = {"ok": True, "entries": 0, "chained": 0, "legacy": 0, "head": GENESIS,
                           "first_bad": None, "error": None, "path": str(path)}
    prev, seq = GENESIS, 0
    try:
        lines = path.read_text().splitlines()
    except OSError:
        out["error"] = "no log file"
        return out
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        out["entries"] += 1
        try:
            e = json.loads(line)
        except ValueError:
            out.update(ok=False, first_bad=n, error=f"line {n}: not JSON")
            return out
        if "hash" not in e:
            out["legacy"] += 1
            continue
        if e.get("prev") != prev:
            out.update(ok=False, first_bad=n, error=f"line {n}: previous-hash link broken (deleted or reordered entry)")
            return out
        if e.get("seq") != seq + 1:
            out.update(ok=False, first_bad=n, error=f"line {n}: sequence gap ({e.get('seq')} after {seq})")
            return out
        if digest(e) != e["hash"]:
            out.update(ok=False, first_bad=n, error=f"line {n}: content does not match its hash (edited entry)")
            return out
        prev, seq = e["hash"], e["seq"]
        out["chained"] += 1
    out["head"] = prev
    return out


class AuditLog:
    def __init__(self, path: str | Path = AUDIT_FILE, keep: int = 5000) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=keep)
        self._head = GENESIS
        self._seq = 0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as fh:
                for line in fh:
                    if line.strip():
                        e = json.loads(line)
                        self._recent.append(e)
                        if "hash" in e:
                            self._head, self._seq = e["hash"], int(e.get("seq") or self._seq)
        except (OSError, ValueError):
            pass  # no log yet, or a corrupt line: verify() reports it; recording continues from genesis

    def record(self, action: str, actor: str = "user", **details: Any) -> dict[str, Any]:
        with self.lock:
            entry: dict[str, Any] = {"seq": self._seq + 1, "ts": time.time(), "actor": actor, "action": action,
                                     "details": details, "prev": self._head}
            entry["hash"] = digest(entry)
            self._recent.append(entry)
            self._head, self._seq = entry["hash"], entry["seq"]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
            except OSError:
                pass  # a read-only disk must not break the app; the in-memory chain still advances
        return entry

    def verify(self) -> dict[str, Any]:
        with self.lock:
            return verify_file(self.path)

    @property
    def head(self) -> str:
        return self._head

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
        w.writerow(["seq", "time", "actor", "action", "details", "prev", "hash"])
        for e in self.entries(limit=100000):
            w.writerow([e.get("seq", ""), time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(e["ts"])), e["actor"], e["action"],
                        json.dumps(e["details"], default=str), e.get("prev", ""), e.get("hash", "")])
        return buf.getvalue()

    def __len__(self) -> int:
        return len(self._recent)


__all__ = ["AUDIT_FILE", "GENESIS", "AuditLog", "digest", "verify_file"]
