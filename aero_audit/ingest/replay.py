"""Replay JSONL recordings produced by the stream recorder. One batch per line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from ..models import Batch


def iter_recording(path: str | Path) -> Iterator[Batch]:
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield Batch.model_validate(json.loads(line))
