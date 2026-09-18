"""Space intake: catalogue parsing and blob verification, library search parsing, captions, telemetry rules."""

import csv
import hashlib
import json
import math

import pytest

from aero_audit.space import footage, nasa3d, nasa_images, telemetry

TREE = {
    "sha": "abc", "truncated": False,
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "r" * 40, "size": 100},
        {"path": "3D Models", "type": "tree", "sha": "t" * 40},
        {"path": "3D Models/International Space Station (ISS) (A)/International Space Station (ISS) (A).glb", "type": "blob", "sha": "a" * 40, "size": 39708},
        {"path": "3D Models/International Space Station (ISS) (A)/International Space Station (ISS) (A).png", "type": "blob", "sha": "b" * 40, "size": 429092},
        {"path": "3D Models/Orion/Orion.7z.001", "type": "blob", "sha": "c" * 40, "size": 41943040},
        {"path": "3D Printing/Hurricane Sandy/readme.pdf", "type": "blob", "sha": "d" * 40, "size": 5000},
        {"path": "Images and Textures/Earth/earth_8k.tif", "type": "blob", "sha": "e" * 40, "size": 90000000},
    ],
}


def test_catalog_parse_filter_roundtrip(tmp_path):
    cat = nasa3d.parse_tree(TREE, "master", 1.0)
    assert len(cat.assets) == 5 and cat.summary()["by_kind"] == {"model": 1, "image": 2, "archive": 1, "doc": 1}
    iss = cat.filter(kind="image", subject="ISS")
    assert len(iss) == 1 and iss[0].subject.startswith("International Space Station") and iss[0].category == "3D Models"
    assert iss[0].raw_url().startswith("https://raw.githubusercontent.com/nasa/NASA-3D-Resources/master/3D%20Models/")
    assert cat.filter(max_bytes=10_000) == [a for a in cat.assets if a.size <= 10_000]
    p = nasa3d.save_catalog(cat, tmp_path / "cat.json")
    back = nasa3d.load_catalog(p)
    assert back.assets == cat.assets and back.ref == "master" and "NASA" in back.licence
    assert nasa3d.kind_of("x/y.GLB") == "model" and nasa3d.kind_of("x/y.7z.002") == "archive" and nasa3d.kind_of("x/y.xyz") == "other"


def test_blob_verification_and_path_confinement(tmp_path):
    data = b"hello nasa\n"
    sha = hashlib.sha1(b"blob 11\0" + data).hexdigest()
    assert nasa3d.blob_sha1(data) == sha and nasa3d.verify_blob(data, sha) and not nasa3d.verify_blob(data + b"x", sha)
    ok = nasa3d.Asset("3D Models/X/x.png", 11, sha, "image", "3D Models", "X")
    assert nasa3d.safe_local_path(tmp_path, ok) == tmp_path / "3D Models" / "X" / "x.png"
    bad = nasa3d.Asset("../../etc/passwd", 1, sha, "other", "..", "..")
    with pytest.raises(PermissionError):
        nasa3d.safe_local_path(tmp_path, bad)


def test_tree_truncated_is_refused(monkeypatch):
    async def fake_get_json(client, url, params=None, headers=None):
        return {"truncated": True, "tree": []}

    monkeypatch.setattr(nasa3d, "get_json", fake_get_json)
    import asyncio

    with pytest.raises(RuntimeError, match="truncated"):
        asyncio.run(nasa3d.fetch_catalog())


SEARCH = {"collection": {"metadata": {"total_hits": 2}, "items": [
    {"href": "https://images-assets.nasa.gov/video/KSC-1/collection.json",
     "data": [{"nasa_id": "KSC-1", "title": "Crew launch highlights", "media_type": "video", "date_created": "2022-04-27T00:00:00Z",
               "center": "KSC", "description": "d", "keywords": ["launch"]}],
     "links": [{"rel": "preview", "href": "https://images-assets.nasa.gov/video/KSC-1/KSC-1~thumb.jpg"}]},
    {"href": "https://images-assets.nasa.gov/image/IMG-2/collection.json",
     "data": [{"nasa_id": "IMG-2", "title": "Photo", "media_type": "image", "date_created": "2020-01-01T00:00:00Z",
               "copyright": "Someone", "photographer": "P"}]},
]}}


def test_library_search_parse_and_variants():
    items, total = nasa_images.parse_search(SEARCH)
    assert total == 2 and items[0].nasa_id == "KSC-1" and items[0].thumbnail.endswith("~thumb.jpg") and items[1].copyright == "Someone"
    urls = ["https://images-assets.nasa.gov/video/KSC-1/KSC-1~orig.mp4", "https://images-assets.nasa.gov/video/KSC-1/KSC-1.srt",
            "https://images-assets.nasa.gov/video/KSC-1/KSC-1~medium.mp4", "https://images-assets.nasa.gov/video/KSC-1/metadata.json"]
    assert nasa_images.pick(urls, "medium").endswith("~medium.mp4") and nasa_images.pick(urls, "captions").endswith(".srt")
    assert nasa_images.pick(urls, "metadata").endswith("metadata.json") and nasa_images.pick(urls, "thumb") is None
    with pytest.raises(ValueError):
        nasa_images.pick(urls, "giant")


SRT = """1
00:00:01,000 --> 00:00:03,000
T-minus ten seconds

2
00:00:12,500 --> 00:00:14,000
And liftoff of the Falcon 9 and Crew Dragon!

3
00:01:20,000 --> 00:01:22,000
Vehicle is supersonic, approaching <i>max Q</i>

4
00:02:40,000 --> 00:02:42,000
MECO. Stage separation confirmed.

5
00:09:00,000 --> 00:09:03,000
SECO. Nominal orbit insertion. Landing burn... and the booster has landed.
"""


def test_captions_to_event_timeline():
    caps = footage.parse_srt(SRT)
    assert len(caps) == 5 and caps[2].start_s == 80.0 and "max Q" in caps[2].text and "<i>" not in caps[2].text
    ev = footage.events_from_captions(caps)
    kinds = [e.kind for e in ev]
    assert kinds[:4] == ["liftoff", "max_q", "meco", "stage_separation"] and "seco" in kinds and "landing" in kinds
    s = footage.timeline_summary(ev)
    assert s["gaps"]["liftoff->meco_s"] == pytest.approx(147.5) and s["gaps"]["liftoff->max_q_s"] == pytest.approx(67.5)


def _ascent(n=200, dt=0.5):
    """Smooth, plausible Falcon-like ascent: ~30 m/s² until MECO, altitude from integrated vertical speed."""
    pts = []
    v = 0.0
    alt = 0.0
    for i in range(n):
        t = i * dt
        a = 30.0 if t < 150 else 9.0
        v += a * dt
        pitch = math.radians(max(20.0, 90.0 - t * 0.45))
        alt += v * math.sin(pitch) * dt / 1000.0
        pts.append(telemetry.TelemetryPoint(round(t, 3), round(v, 2), round(alt, 4)))
    return pts


def test_telemetry_rules_fire_on_injected_faults(tmp_path):
    clean = _ascent()
    assert telemetry.audit_telemetry(clean) == []
    pts = list(clean)
    # SPC-001: a 900 m/s jump in half a second
    pts[100] = telemetry.TelemetryPoint(pts[100].t_s, pts[100].speed_mps + 900.0, pts[100].altitude_km)
    # SPC-003: a 30 s hole
    pts = pts[:150] + [telemetry.TelemetryPoint(p.t_s + 30.0, p.speed_mps, p.altitude_km) for p in pts[150:]]
    # SPC-004: a duplicated timestamp
    pts.insert(60, pts[59])
    # SPC-002 + SPC-005: altitude leaps 8 km in one step
    pts[180] = telemetry.TelemetryPoint(pts[180].t_s, pts[180].speed_mps, pts[180].altitude_km + 8.0)
    findings = telemetry.audit_telemetry(pts, stream="test")
    rules = {f.rule_id for f in findings}
    assert {"SPC-001", "SPC-002", "SPC-003", "SPC-004", "SPC-005"} <= rules
    assert all(f.callsign == "test" and "dt_s" in f.evidence for f in findings)
    jp, mp = telemetry.write_report(pts, findings, tmp_path, "t")
    assert json.loads(jp.read_text())["summary"]["findings"] == len(findings) and "SPC-001" in mp.read_text()


def test_telemetry_csv_units(tmp_path):
    p = tmp_path / "t.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "speed_kmh", "altitude_m"])
        w.writerow([0, 0, 0])
        w.writerow([1, 36, 15])
        w.writerow(["x", "y", "z"])
    pts = telemetry.load_csv(p)
    assert len(pts) == 2 and pts[1].speed_mps == pytest.approx(10.0) and pts[1].altitude_km == pytest.approx(0.015)
    with pytest.raises(ValueError):
        telemetry.load_csv(tmp_path / "bad.csv") if (tmp_path / "bad.csv").write_text("a,b\n1,2\n") else None


def test_frame_extraction_from_synthetic_video(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    video = tmp_path / "clip.mp4"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    for i in range(50):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        frame[:, : min(63, i), :] = 255
        w.write(frame)
    w.release()
    m = footage.extract_frames(video, tmp_path / "frames", every_s=1.0, max_frames=10)
    assert m.fps == pytest.approx(10.0) and 4 <= len(m.frames) <= 6 and m.frames[1]["t_s"] == pytest.approx(1.0)
    assert (tmp_path / "frames" / "frames.manifest.json").is_file() and len(m.video_sha256) == 64
    assert all(len(f["sha256"]) == 64 and f["width"] == 64 for f in m.frames)
