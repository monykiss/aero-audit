"""Replay JSONL recordings produced by the stream recorder. One batch per line.

Plain ``.jsonl`` and gzip-compressed ``.jsonl.gz`` (the bundled samples) are both accepted.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path

from ..models import Batch

RECORDING_SUFFIXES = (".jsonl", ".jsonl.gz")


def open_recording(path: str | Path):
    p = Path(path)
    return gzip.open(p, "rt", encoding="utf-8") if p.name.endswith(".gz") else open(p, encoding="utf-8")


def iter_recording(path: str | Path) -> Iterator[Batch]:
    with open_recording(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield Batch.model_validate(json.loads(line))


def recording_stem(path: str | Path) -> str:
    """File name without ``.jsonl`` / ``.jsonl.gz``."""
    name = Path(path).name
    for s in RECORDING_SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return Path(path).stem
