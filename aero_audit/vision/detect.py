"""Aircraft detection on still images (apron cameras, satellite tiles, ramp photos).

Uses a COCO-pretrained YOLO (class "airplane") so it works out of the box; swap `weights`
for a fine-tuned model (e.g. trained on iSAID/DOTA aerial imagery) when you have labels.
Dependencies are imported lazily so the rest of the toolkit runs without torch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AIRCRAFT_LABELS = {"airplane", "aeroplane", "plane", "aircraft"}


@dataclass
class Detection:
    label: str
    conf: float
    x1: int
    y1: int
    x2: int
    y2: int
    cx: float  # normalized center x in [0, 1]
    cy: float  # normalized center y in [0, 1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _yolo(weights: str):
    try:
        from ultralytics import YOLO
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Vision extras not installed. Run: uv pip install -e '.[vision]'"
        ) from e
    return YOLO(weights)


def detect(
    image_path: str | Path,
    weights: str = "yolov8n.pt",
    conf: float = 0.25,
    only_aircraft: bool = True,
    imgsz: int = 1280,
) -> tuple[list[Detection], tuple[int, int]]:
    """Return (detections, (width, height))."""
    model = _yolo(weights)
    results = model.predict(str(image_path), conf=conf, imgsz=imgsz, verbose=False)
    r = results[0]
    h, w = r.orig_shape
    names = r.names
    dets: list[Detection] = []
    for box in r.boxes:
        label = names[int(box.cls[0])]
        if only_aircraft and label not in AIRCRAFT_LABELS:
            continue
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        dets.append(
            Detection(
                label=label,
                conf=float(box.conf[0]),
                x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                cx=((x1 + x2) / 2) / w,
                cy=((y1 + y2) / 2) / h,
            )
        )
    return dets, (int(w), int(h))


def iou(a: Detection, b: Detection) -> float:
    ix = max(0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union else 0.0


def nms(dets: list[Detection], iou_thresh: float = 0.5) -> list[Detection]:
    """Greedy non-maximum suppression: keep the highest-confidence box among overlaps."""
    keep: list[Detection] = []
    for d in sorted(dets, key=lambda d: -d.conf):
        if all(iou(d, k) < iou_thresh for k in keep):
            keep.append(d)
    return keep


def detect_tiled(
    image_path: str | Path,
    weights: str = "yolov8n.pt",
    conf: float = 0.15,
    tile: int = 320,
    overlap: float = 0.25,
    only_aircraft: bool = True,
) -> tuple[list[Detection], tuple[int, int]]:
    """Slice the image into overlapping tiles, detect on each, merge with NMS (SAHI-style).

    Aerial/apron imagery has many small objects; a 640-px whole-image pass shrinks a parked
    aircraft to a few pixels. Tiling keeps each object at a size the detector was trained on.
    On the bundled sample (12 parked transports) whole-image inference found none of them;
    320-px tiles at conf 0.10 find 4, plus a few false positives on the photographer's wing.
    That gap is the case for fine-tuning on aerial datasets (DOTA, iSAID, RarePlanes).
    """
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(image_path)
    h, w = img.shape[:2]
    model = _yolo(weights)
    step = max(1, int(tile * (1 - overlap)))
    dets: list[Detection] = []
    for y in range(0, max(1, h - tile + 1) + step, step):
        for x in range(0, max(1, w - tile + 1) + step, step):
            crop = img[y : y + tile, x : x + tile]
            if crop.shape[0] < 64 or crop.shape[1] < 64:
                continue
            r = model.predict(crop, conf=conf, imgsz=tile, verbose=False)[0]
            for box in r.boxes:
                label = r.names[int(box.cls[0])]
                if only_aircraft and label not in AIRCRAFT_LABELS:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                dets.append(
                    Detection(
                        label=label, conf=float(box.conf[0]),
                        x1=int(x + x1), y1=int(y + y1), x2=int(x + x2), y2=int(y + y2),
                        cx=(x + (x1 + x2) / 2) / w, cy=(y + (y1 + y2) / 2) / h,
                    )
                )
    return nms(dets), (int(w), int(h))


def annotate(image_path: str | Path, dets: list[Detection], out_path: str | Path) -> Path:
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(image_path)
    for d in dets:
        cv2.rectangle(img, (d.x1, d.y1), (d.x2, d.y2), (0, 200, 255), 2)
        cv2.putText(
            img, f"{d.label} {d.conf:.2f}", (d.x1, max(0, d.y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2,
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)
    return out_path
