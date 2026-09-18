"""Mesh loaders for the formats NASA-3D-Resources ships: synthetic byte streams for every format, real NASA files when cached."""

import struct
from pathlib import Path

import numpy as np
import pytest

from aero_audit.space import mesh, render

NASA = Path("data/space/nasa3d")
QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]


def _3ds_chunk(cid: int, body: bytes) -> bytes:
    return struct.pack("<HI", cid, 6 + len(body)) + body


def _iff(cid: bytes, body: bytes) -> bytes:
    return cid + struct.pack(">I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def test_3ds_two_objects_offset_indices():
    verts = struct.pack("<H", 4) + b"".join(struct.pack("<3f", *p) for p in QUAD)
    faces = struct.pack("<H", 2) + struct.pack("<8H", 0, 1, 2, 0, 0, 2, 3, 0)
    obj = _3ds_chunk(0x4000, b"quad\x00" + _3ds_chunk(0x4100, _3ds_chunk(0x4110, verts) + _3ds_chunk(0x4120, faces)))
    data = _3ds_chunk(0x4D4D, _3ds_chunk(0x0002, struct.pack("<I", 3)) + _3ds_chunk(0x3D3D, obj + obj))
    v, f = mesh.load_3ds(data)
    assert v.shape == (8, 3) and f.shape == (4, 3) and f[2:].min() == 4  # second object's faces point at its own vertices
    with pytest.raises(ValueError):
        mesh.load_3ds(b"\x00\x00\x06\x00\x00\x00")


def test_lwo2_and_lwob_quads_fan_to_triangles():
    pnts = _iff(b"PNTS", b"".join(struct.pack(">3f", *p) for p in QUAD))
    lwo2 = b"LWO2" + pnts + _iff(b"POLS", b"FACE" + struct.pack(">H", 4) + struct.pack(">4H", 0, 1, 2, 3)) + _iff(b"POLS", b"PTCH" + struct.pack(">H", 3) + struct.pack(">3H", 0, 1, 2))
    v, f = mesh.load_lwo(b"FORM" + struct.pack(">I", len(lwo2)) + lwo2)
    assert v.shape == (4, 3) and f.tolist() == [[0, 1, 2], [0, 2, 3]]  # PTCH polygons are not flat faces and are skipped
    big = b"LWO2" + pnts + _iff(b"POLS", b"FACE" + struct.pack(">H", 3) + struct.pack(">I", 0xFF000000 | 0) + struct.pack(">2H", 1, 2))
    v, f = mesh.load_lwo(b"FORM" + struct.pack(">I", len(big)) + big)
    assert f.tolist() == [[0, 1, 2]]  # 4-byte VX index form
    lwob = b"LWOB" + pnts + _iff(b"POLS", struct.pack(">H", 4) + struct.pack(">4H", 0, 1, 2, 3) + struct.pack(">h", 1))
    v, f = mesh.load_lwo(b"FORM" + struct.pack(">I", len(lwob)) + lwob)
    assert f.shape == (2, 3)
    with pytest.raises(ValueError, match="LWO3"):
        mesh.load_lwo(b"FORM" + struct.pack(">I", 4) + b"LWO3")


def test_stl_binary_and_ascii():
    tri = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    rec = np.zeros(2, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["v"][0] = tri
    rec["v"][1] = tri + 1
    data = b"\x00" * 80 + struct.pack("<I", 2) + rec.tobytes()
    v, f = mesh.load_stl(data)
    assert v.shape == (6, 3) and f.tolist() == [[0, 1, 2], [3, 4, 5]]
    ascii_stl = b"solid t\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid t\n"
    v, f = mesh.load_stl(ascii_stl)
    assert v.shape == (3, 3) and f.shape == (1, 3)
    with pytest.raises(ValueError):
        mesh.load_stl(b"junk")


def test_glb_uncompressed_with_node_transform():
    import json

    pos = np.array(QUAD, dtype=np.float32).tobytes()
    idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16).tobytes()
    bin_ = pos + idx
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "translation": [10, 0, 0], "scale": [2, 2, 2]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"}, {"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)}, {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)}],
           "buffers": [{"byteLength": len(bin_)}]}
    js = json.dumps(doc).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bin_
    data = b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body
    v, f = mesh.load_glb(data)
    assert f.shape == (2, 3) and np.allclose(v[1], [12, 0, 0]) and np.allclose(v[2], [12, 2, 0])  # translation and scale applied
    with pytest.raises(ValueError):
        mesh.load_glb(b"nope")


def test_dispatch_and_render_of_supported_formats(tmp_path):
    (tmp_path / "x.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    _v, f = mesh.load_mesh(tmp_path / "x.obj")
    assert f.shape == (1, 3) and set(mesh.SUPPORTED) >= {".obj", ".stl", ".glb", ".3ds", ".lwo"}
    with pytest.raises(ValueError, match="unsupported"):
        mesh.load_mesh(tmp_path / "x.fbx")


@pytest.mark.parametrize("pattern", ["*.3ds", "*.lwo", "*.stl", "*.glb"])
def test_real_nasa_models_when_cached(pattern):
    files = list(NASA.rglob(pattern)) if NASA.is_dir() else []
    if not files:
        pytest.skip(f"no cached NASA {pattern} model; run aero space fetch")
    for p in files[:2]:
        try:
            v, f = mesh.load_mesh(p)
        except ValueError as e:
            if "Draco" in str(e):
                pytest.skip(str(e))
            raise
        s = mesh.mesh_summary(v, f)
        assert s["triangles"] > 0 and all(x > 0 for x in s["extent"])
        img = render.rasterise(v, f, 96, 30, 20)
        assert 0.02 < float((img > 0.06).mean()) < 0.9, p.name  # a silhouette, not a blank or a fill
