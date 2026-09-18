"""Mesh loaders for the formats NASA-3D-Resources actually ships: STL (342 models), glTF binary (257),
3DS (4), LightWave LWO2 / LWOB (4), plus OBJ. The catalogue holds no OBJ files at all, so a renderer that
reads only OBJ renders nothing from NASA. All of these are simple containers and the renderer needs just
vertices and faces, so a few dozen lines each replace a Blender or assimp dependency (Blender's own
.blend files and FBX stay out of scope: 15 models).

- STL: binary (80-byte header, uint32 count, 50 bytes per facet) or ASCII facets.
- GLB / glTF: JSON + BIN chunks; POSITION and index accessors per triangle primitive, node TRS or
  matrix transforms applied down the scene graph.

- 3DS: little-endian chunks (uint16 id, uint32 length). MAIN 0x4D4D > EDITOR 0x3D3D > OBJECT 0x4000
  (C string name) > TRIMESH 0x4100 > VERTICES 0x4110 (uint16 n, n × float32×3) and FACES 0x4120
  (uint16 n, n × (uint16×3 + flags)). Vertices are stored in world space; the pivot matrix is not
  needed for a silhouette. Several objects concatenate with index offsets.
- LWO2 (LightWave 6+): IFF, big-endian. FORM size 'LWO2', chunks (4-char id, uint32 size, even
  padded): PNTS (float32×3 each), POLS with type 'FACE' (uint16 count with flags in the top 6 bits,
  then variable-length VX indices: uint16, or uint32 & 0x00FFFFFF when the first byte is 0xFF),
  LAYR starting a new point index base.
- LWOB (LightWave 5): PNTS as above; POLS as uint16 count, count × uint16 indices, int16 surface.

Polygons with more than three vertices are fanned. Anything unreadable raises ValueError with the
reason rather than rendering garbage.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def load_mesh(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) float64 and triangles (m, 3) int64 for .obj, .3ds, .lwo (LWO2 or LWOB)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".obj":
        return load_obj(p)
    if ext == ".3ds":
        return load_3ds(p.read_bytes())
    if ext == ".lwo":
        return load_lwo(p.read_bytes())
    if ext == ".stl":
        return load_stl(p.read_bytes())
    if ext in (".glb", ".gltf"):
        return load_glb(p.read_bytes()) if ext == ".glb" else load_gltf_json(p.read_text(), p.parent)
    raise ValueError(f"unsupported mesh format {ext!r} (obj, 3ds, lwo, stl, glb, gltf)")


SUPPORTED = (".obj", ".3ds", ".lwo", ".stl", ".glb", ".gltf")


def load_obj(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) and triangle indices (m, 3); polygons with more than three vertices are fanned."""
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    for raw in Path(path).read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                v = tok.split("/")[0]
                if not v:
                    continue
                i = int(v)
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not verts or not faces:
        raise ValueError(f"no geometry in {path}")
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if f.max() >= len(v) or f.min() < 0:
        raise ValueError(f"face index out of range in {path}")
    return v, f


def _finish(verts: list[np.ndarray], faces: list[np.ndarray], what: str) -> tuple[np.ndarray, np.ndarray]:
    if not verts or not faces:
        raise ValueError(f"no geometry in {what}")
    v = np.concatenate(verts).astype(np.float64)
    f = np.concatenate(faces).astype(np.int64)
    if len(f) and (f.max() >= len(v) or f.min() < 0):
        raise ValueError(f"{what}: face index out of range ({f.min()}..{f.max()} of {len(v)} vertices)")
    return v, f


def _fan(indices: list[int]) -> list[list[int]]:
    return [[indices[0], indices[k], indices[k + 1]] for k in range(1, len(indices) - 1)]


# ---- 3DS -----------------------------------------------------------------------------------------
def load_3ds(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    if len(data) < 6 or struct.unpack_from("<H", data, 0)[0] != 0x4D4D:
        raise ValueError("not a 3DS file (missing 0x4D4D main chunk)")
    verts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    base = 0

    def walk(start: int, end: int, depth: int) -> None:
        nonlocal base
        pos = start
        while pos + 6 <= end:
            cid, length = struct.unpack_from("<HI", data, pos)
            if length < 6 or pos + length > end + 0:
                length = max(length, 6)
                if pos + length > end:
                    return
            body, nxt = pos + 6, pos + length
            if cid in (0x4D4D, 0x3D3D):
                walk(body, nxt, depth + 1)
            elif cid == 0x4000:  # object: name then sub-chunks
                z = data.index(b"\x00", body, nxt)
                walk(z + 1, nxt, depth + 1)
            elif cid == 0x4100:
                walk(body, nxt, depth + 1)
            elif cid == 0x4110:
                n = struct.unpack_from("<H", data, body)[0]
                arr = np.frombuffer(data, dtype="<f4", count=3 * n, offset=body + 2).reshape(n, 3)
                verts.append(arr)
                base = sum(len(x) for x in verts) - n
            elif cid == 0x4120:
                n = struct.unpack_from("<H", data, body)[0]
                arr = np.frombuffer(data, dtype="<u2", count=4 * n, offset=body + 2).reshape(n, 4)[:, :3].astype(np.int64) + base
                faces.append(arr)
            pos = nxt

    walk(0, len(data), 0)
    return _finish(verts, faces, "3DS")


# ---- LightWave ----------------------------------------------------------------------------------
def _vx(data: bytes, pos: int) -> tuple[int, int]:
    if data[pos] == 0xFF:
        return struct.unpack_from(">I", data, pos)[0] & 0x00FFFFFF, pos + 4
    return struct.unpack_from(">H", data, pos)[0], pos + 2


def load_lwo(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    if len(data) < 12 or data[:4] != b"FORM":
        raise ValueError("not a LightWave file (missing FORM)")
    kind = data[8:12]
    if kind not in (b"LWO2", b"LWOB"):
        raise ValueError(f"unsupported LightWave form {kind!r} (LWO2, LWOB)")
    size = struct.unpack_from(">I", data, 4)[0]
    end = min(8 + size, len(data))
    verts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    base = 0
    pos = 12
    while pos + 8 <= end:
        cid, length = data[pos:pos + 4], struct.unpack_from(">I", data, pos + 4)[0]
        body, nxt = pos + 8, pos + 8 + length + (length & 1)
        if cid == b"PNTS":
            n = length // 12
            verts.append(np.frombuffer(data, dtype=">f4", count=3 * n, offset=body).reshape(n, 3))
            base = sum(len(x) for x in verts) - n
        elif cid == b"POLS":
            polys: list[list[int]] = []
            p = body
            if kind == b"LWO2":
                if data[p:p + 4] != b"FACE":  # PTCH, SUBD, CURV, BONE: not renderable as flat triangles here
                    pos = nxt
                    continue
                p += 4
                while p + 2 <= body + length:
                    nv = struct.unpack_from(">H", data, p)[0] & 0x03FF
                    p += 2
                    idx = []
                    for _ in range(nv):
                        i, p = _vx(data, p)
                        idx.append(i + base)
                    if nv >= 3:
                        polys += _fan(idx)
            else:  # LWOB
                while p + 2 <= body + length:
                    nv = struct.unpack_from(">H", data, p)[0]
                    p += 2
                    idx = [struct.unpack_from(">H", data, p + 2 * k)[0] + base for k in range(nv)]
                    p += 2 * nv
                    surf = struct.unpack_from(">h", data, p)[0]
                    p += 2
                    if surf < 0:  # detail polygons follow: uint16 count, skipped structurally by reading them the same way
                        p += 2
                    if nv >= 3:
                        polys += _fan(idx)
            if polys:
                faces.append(np.asarray(polys, dtype=np.int64))
        pos = nxt
    return _finish(verts, faces, kind.decode())


# ---- STL -----------------------------------------------------------------------------------------
def load_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Binary STL (80-byte header, uint32 count, 50 bytes per facet) or ASCII STL. Every facet is its own triangle;
    vertices are not merged (the silhouette does not care)."""
    if len(data) >= 84 and not data[:5].lower().startswith(b"solid"):
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n <= len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            v = rec["v"].reshape(-1, 3)
            return _finish([v], [np.arange(3 * n, dtype=np.int64).reshape(n, 3)], "STL")
    if data[:5].lower().startswith(b"solid") or b"vertex" in data[:4096]:
        tris = []
        cur: list[list[float]] = []
        for line in data.decode(errors="replace").splitlines():
            t = line.split()
            if len(t) == 4 and t[0] == "vertex":
                cur.append([float(t[1]), float(t[2]), float(t[3])])
                if len(cur) == 3:
                    tris.append(cur)
                    cur = []
        if tris:
            n = len(tris)
            return _finish([np.asarray(tris, dtype=np.float64).reshape(-1, 3)], [np.arange(3 * n, dtype=np.int64).reshape(n, 3)], "STL")
    raise ValueError("not a readable STL (neither binary layout nor ASCII facets)")


# ---- glTF binary ---------------------------------------------------------------------------------
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    import json

    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file (missing glTF magic)")
    total = struct.unpack_from("<I", data, 8)[0]
    pos, doc, buffers = 12, None, []
    while pos + 8 <= min(total, len(data)):
        length, ctype = struct.unpack_from("<II", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if ctype == 0x4E4F534A:
            doc = json.loads(body.decode())
        elif ctype == 0x004E4942:
            buffers.append(body)
        pos += 8 + length
    if doc is None:
        raise ValueError("GLB without a JSON chunk")
    return _gltf_mesh(doc, buffers)


def load_gltf_json(text: str, folder: Path) -> tuple[np.ndarray, np.ndarray]:
    import base64
    import json

    doc = json.loads(text)
    buffers = []
    for b in doc.get("buffers", []):
        uri = b.get("uri", "")
        if uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            buffers.append((folder / uri).read_bytes())
    return _gltf_mesh(doc, buffers)


def _accessor(doc: dict, buffers: list[bytes], idx: int) -> np.ndarray:
    acc = doc["accessors"][idx]
    bv = doc["bufferViews"][acc["bufferView"]]
    dt = np.dtype(_CT[acc["componentType"]])
    nc = _NC[acc["type"]]
    buf = buffers[bv.get("buffer", 0)]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 0)
    n = acc["count"]
    if stride and stride != dt.itemsize * nc:
        rows = [np.frombuffer(buf, dtype=dt, count=nc, offset=start + i * stride) for i in range(n)]
        return np.stack(rows) if rows else np.zeros((0, nc), dtype=dt)
    return np.frombuffer(buf, dtype=dt, count=n * nc, offset=start).reshape(n, nc)


def _draco(doc: dict, buffers: list[bytes], ext: dict) -> tuple[np.ndarray, np.ndarray]:
    """KHR_draco_mesh_compression: NASA's GLB exports use it throughout. Decoded with the DracoPy wheel (vision extra)."""
    try:
        import DracoPy
    except ImportError as e:  # pragma: no cover - environment dependent
        raise ValueError("Draco-compressed glTF: install the vision extra (DracoPy) to decode it") from e
    bv = doc["bufferViews"][ext["bufferView"]]
    buf = buffers[bv.get("buffer", 0)]
    blob = buf[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
    m = DracoPy.decode(blob)
    pos = np.asarray(m.points, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(m.faces, dtype=np.int64).reshape(-1, 3)
    return pos, faces


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
    q = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
    sc = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
    x, y, z, w = q
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * sc
    m[:3, 3] = t
    return m


def _gltf_mesh(doc: dict, buffers: list[bytes]) -> tuple[np.ndarray, np.ndarray]:
    verts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    meshes = doc.get("meshes", [])

    def emit(mesh_idx: int, m: np.ndarray) -> None:
        for prim in meshes[mesh_idx].get("primitives", []):
            if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                continue
            draco = (prim.get("extensions") or {}).get("KHR_draco_mesh_compression")
            if draco is not None:
                pos, idx = _draco(doc, buffers, draco)
            else:
                pos = _accessor(doc, buffers, prim["attributes"]["POSITION"]).astype(np.float64)
                if "indices" in prim:
                    idx = _accessor(doc, buffers, prim["indices"]).reshape(-1).astype(np.int64)
                else:
                    idx = np.arange(len(pos), dtype=np.int64)
                idx = idx[: len(idx) - len(idx) % 3].reshape(-1, 3)
            pos = pos @ m[:3, :3].T + m[:3, 3]
            base = sum(len(x) for x in verts)
            idx = idx + base
            verts.append(pos)
            faces.append(idx)

    nodes = doc.get("nodes", [])
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else None
    if scene is not None and nodes:
        stack = [(i, np.eye(4)) for i in scene.get("nodes", [])]
        while stack:
            i, parent = stack.pop()
            node = nodes[i]
            m = parent @ _node_matrix(node)
            if "mesh" in node:
                emit(node["mesh"], m)
            stack += [(c, m) for c in node.get("children", [])]
    else:
        for i in range(len(meshes)):
            emit(i, np.eye(4))
    return _finish(verts, faces, "glTF")


def mesh_summary(v: np.ndarray, f: np.ndarray) -> dict[str, float | int]:
    lo, hi = v.min(axis=0), v.max(axis=0)
    return {"vertices": len(v), "triangles": len(f), "extent": [round(float(x), 4) for x in (hi - lo)]}


__all__ = ["SUPPORTED", "load_3ds", "load_glb", "load_gltf_json", "load_lwo", "load_mesh", "load_obj", "load_stl", "mesh_summary"]
