"""Footage intake: frames from a local video file, an event timeline from its captions, and the
existing tiled detector run over the frames.

Only local files are read. The NASA library provides ``.srt`` captions with its videos; the
caption timeline is parsed into launch events (liftoff, max-Q, MECO, stage separation, SECO,
deployment, landing) that give later telemetry checks their anchor points. Frame extraction needs
OpenCV from the ``[vision]`` extra; detection needs ultralytics. Both degrade to a clear error.

Honest baseline: the COCO detector knows "airplane" but not "rocket"; it is a placeholder until a
detector is fine-tuned on renders of the NASA 3D models and NASA library imagery.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FRAMES_DIR = Path("data/space/frames")

EVENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("liftoff", r"\b(lift[- ]?off|launch(?:ed)?|we have ignition|and liftoff)\b"),
    ("max_q", r"\bmax[- ]?q\b"),
    ("meco", r"\b(meco|main engine cut[- ]?off)\b"),
    ("stage_separation", r"\b(stage sep(?:aration)?|booster sep(?:aration)?|separation confirmed)\b"),
    ("fairing_separation", r"\bfairing (?:sep|separation|deploy)"),
    ("seco", r"\b(seco|second[- ]engine cut[- ]?off)\b"),
    ("boostback", r"\bboost[- ]?back\b"),
    ("entry_burn", r"\bentry burn\b"),
    ("landing_burn", r"\blanding burn\b"),
    ("landing", r"\b(landing confirmed|has landed|touchdown|landed)\b"),
    ("deploy", r"\b(deploy(?:ment|ed)? confirmed|payload deploy|spacecraft separation)\b"),
    ("abort", r"\b(abort|anomaly|hold hold hold)\b"),
)


@dataclass
class Caption:
    index: int
    start_s: float
    end_s: float
    text: str


@dataclass
class Event:
    kind: str
    t_s: float
    text: str


def _ts(s: str) -> float:
    h, m, rest = s.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_srt(text: str) -> list[Caption]:
    out: list[Caption] = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        idx_line, time_line = (lines[0], lines[1]) if "-->" in lines[1] else ("0", lines[0])
        m = re.match(r"\s*(\S+)\s*-->\s*(\S+)", time_line)
        if not m:
            continue
        body = " ".join(lines[2:] if "-->" in lines[1] else lines[1:])
        body = re.sub(r"<[^>]+>", "", body).strip()
        try:
            out.append(Caption(int(idx_line) if idx_line.isdigit() else len(out) + 1, _ts(m.group(1)), _ts(m.group(2)), body))
        except ValueError:
            continue
    return out


def events_from_captions(caps: list[Caption]) -> list[Event]:
    """First mention of each launch milestone, in caption order."""
    seen: set[str] = set()
    events: list[Event] = []
    for c in caps:
        low = c.text.lower()
        for kind, rx in EVENT_PATTERNS:
            if kind in seen:
                continue
            if re.search(rx, low):
                seen.add(kind)
                events.append(Event(kind, c.start_s, c.text))
    return events


@dataclass
class FrameManifest:
    video: str
    video_sha256: str
    every_s: float
    fps: float
    frames: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict[str, Any]:
        return {"video": self.video, "video_sha256": self.video_sha256, "every_s": self.every_s, "fps": self.fps,
                "created_at": self.created_at, "frames": self.frames}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_frames(video: str | Path, out_dir: str | Path | None = None, every_s: float = 1.0, max_frames: int = 600,
                   start_s: float = 0.0, end_s: float | None = None) -> FrameManifest:
    """Write JPEG frames every ``every_s`` seconds with a manifest (timestamp and SHA-256 per frame)."""
    try:
        import cv2
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("frame extraction needs OpenCV: uv pip install -e '.[vision]'") from e
    video = Path(video)
    if not video.is_file():
        raise FileNotFoundError(video)
    out = Path(out_dir) if out_dir else FRAMES_DIR / video.stem
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(round(every_s * fps), 1) if fps > 0 else 1
    manifest = FrameManifest(str(video), _sha256(video), every_s, fps)
    idx = int(start_s * fps) if fps > 0 else 0
    while len(manifest.frames) < max_frames and (total == 0 or idx < total):
        t_s = idx / fps if fps > 0 else float(len(manifest.frames))
        if end_s is not None and t_s > end_s:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        name = f"frame_{idx:07d}_{t_s:08.2f}s.jpg"
        p = out / name
        cv2.imwrite(str(p), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        manifest.frames.append({"file": str(p), "index": idx, "t_s": round(t_s, 3), "sha256": _sha256(p),
                                "width": int(frame.shape[1]), "height": int(frame.shape[0])})
        idx += step
    cap.release()
    (out / "frames.manifest.json").write_text(json.dumps(manifest.to_dict(), indent=1))
    return manifest


def detect_frames(manifest: FrameManifest | dict[str, Any], weights: str = "yolov8n.pt", conf: float = 0.15,
                  tile: int | None = 640, classes: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Run the tiled detector over every frame; returns per-frame detection summaries."""
    from ..vision.detect import detect, detect_tiled

    frames = manifest["frames"] if isinstance(manifest, dict) else manifest.frames
    out = []
    for f in frames:
        res = (detect_tiled(f["file"], weights=weights, tile=tile, conf=conf, only_aircraft=False) if tile
               else detect(f["file"], weights=weights, conf=conf, only_aircraft=False))
        dets = res[0] if isinstance(res, tuple) else res
        if classes:
            dets = [d for d in dets if d.label in classes]
        out.append({"file": f["file"], "t_s": f["t_s"], "detections": [d.to_dict() for d in dets],
                    "labels": sorted({d.label for d in dets})})
    return out


def timeline_summary(events: list[Event]) -> dict[str, Any]:
    """Milestone gaps that later telemetry checks anchor on (liftoff to MECO, etc.)."""
    by = {e.kind: e.t_s for e in events}
    gaps = {}
    for a, b in (("liftoff", "max_q"), ("liftoff", "meco"), ("meco", "stage_separation"), ("stage_separation", "seco"), ("liftoff", "landing")):
        if a in by and b in by:
            gaps[f"{a}->{b}_s"] = round(by[b] - by[a], 1)
    return {"events": [{"kind": e.kind, "t_s": e.t_s, "text": e.text[:120]} for e in events], "gaps": gaps}


__all__ = ["EVENT_PATTERNS", "FRAMES_DIR", "Caption", "Event", "FrameManifest", "detect_frames", "events_from_captions",
           "extract_frames", "parse_srt", "timeline_summary"]
