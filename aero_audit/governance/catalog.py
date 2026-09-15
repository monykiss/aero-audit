"""Data catalogue: a CMR-style registry of everything the programme holds on disk, split into
collections (what kind of thing) and granules (one file each) with size, hash, time bounds,
region and a pointer to provenance. Built from the tree, searchable, and reconcilable against a
previous build so drift (files added, removed or changed underneath the records) is visible.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

CATALOG_FILE = Path("data/app/catalog.json")
HASH_LIMIT = 64_000_000
COLLECTIONS: dict[str, tuple[str, ...]] = {
    "recordings": ("data/recordings/*.jsonl", "data/recordings/*.jsonl.gz"),
    "samples": ("data/samples/*.jsonl.gz", "data/samples/*.cdm", "data/samples/*.json", "data/samples/*.jpg"),
    "reports": ("reports/*.json", "reports/*.md", "reports/*.html"),
    "studies": ("reports/studies/*.json", "reports/studies/*.md"),
    "evidence": ("reports/*.zip",),
    "models": ("models/*.joblib", "models/*.md", "models/evaluation.json", "models/registry.json"),
    "assets": ("data/space/nasa3d/**/*",),
    "media": ("data/space/nasa_media/**/*",),
    "elements": ("data/space/elements/*.tle",),
    "cdm": ("data/space/cdm/inbox/*", "data/space/cdm/ledger.jsonl"),
    "datasets": ("data/space/dataset/manifest.json",),
    "audit": ("data/app/audit.jsonl",),
}


def _sha(p: Path) -> str | None:
    if p.stat().st_size > HASH_LIMIT:
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _recording_bounds(p: Path) -> dict[str, Any]:
    from ..ingest.replay import open_recording

    try:
        with open_recording(p) as fh:
            first = fh.readline()
            last = first
            for line in fh:
                if line.strip():
                    last = line
        a, b = json.loads(first), json.loads(last)
        return {"time_start": a.get("ts"), "time_end": b.get("ts"), "provider": a.get("provider"), "region": a.get("region")}
    except (OSError, ValueError):
        return {}


HASH_CACHE = Path("data/app/catalog_hashes.json")


def _load_hash_cache(path: Path) -> dict[str, list[Any]]:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha_cached(p: Path, rel: str, st: Any, cache: dict[str, list[Any]]) -> str | None:
    """Re-hash only when size or mtime changed: a catalogue rebuild over gigabytes of recordings then costs a stat per file."""
    hit = cache.get(rel)
    if hit and len(hit) == 3 and hit[0] == st.st_size and hit[1] == st.st_mtime:
        return hit[2]
    sha = _sha(p)
    cache[rel] = [st.st_size, st.st_mtime, sha]
    return sha


def build_catalog(root: str | Path = ".", hash_cache: str | Path | None = HASH_CACHE) -> dict[str, Any]:
    root = Path(root)
    cache_path = (root / hash_cache) if hash_cache and not Path(hash_cache).is_absolute() else (Path(hash_cache) if hash_cache else None)
    cache = _load_hash_cache(cache_path) if cache_path else {}
    cat: dict[str, Any] = {"format": "aero-audit-catalog/1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "collections": {}}
    for name, patterns in COLLECTIONS.items():
        granules = []
        seen: set[str] = set()
        for pat in patterns:
            for p in sorted(root.glob(pat)):
                if not p.is_file() or p.name.endswith(".provenance.json") or p.name.endswith(".part"):
                    continue
                rel = p.relative_to(root).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                st = p.stat()
                g: dict[str, Any] = {"id": rel, "collection": name, "bytes": st.st_size, "mtime": st.st_mtime, "sha256": _sha_cached(p, rel, st, cache)}
                prov = p.with_name(p.name + ".provenance.json")
                if prov.is_file():
                    g["provenance"] = prov.relative_to(root).as_posix()
                if name in ("recordings", "samples") and (p.suffix == ".gz" or p.suffix == ".jsonl"):
                    g.update(_recording_bounds(p))
                if name == "reports" and p.name.endswith(".manifest.json"):
                    g["kind"] = "manifest"
                granules.append(g)
        cat["collections"][name] = {"count": len(granules), "bytes": sum(g["bytes"] for g in granules), "granules": granules}
    cat["granules_total"] = sum(c["count"] for c in cat["collections"].values())
    cat["bytes_total"] = sum(c["bytes"] for c in cat["collections"].values())
    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))
        except OSError:
            pass  # the cache is an accelerator, never a requirement
    return cat


def save_catalog(cat: dict[str, Any], path: str | Path = CATALOG_FILE) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cat, indent=1))
    return p


def load_catalog(path: str | Path = CATALOG_FILE) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def search(cat: dict[str, Any], q: str | None = None, collection: str | None = None, since_ts: float | None = None) -> list[dict[str, Any]]:
    ql = (q or "").lower()
    out = []
    for name, c in cat["collections"].items():
        if collection and name != collection:
            continue
        for g in c["granules"]:
            if since_ts and (g.get("time_end") or g["mtime"]) < since_ts:
                continue
            if ql and ql not in json.dumps(g).lower():
                continue
            out.append(g)
    return sorted(out, key=lambda g: -g["mtime"])


def reconcile(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    def index(cat: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {g["id"]: g for c in cat["collections"].values() for g in c["granules"]}

    a, b = index(old) if old else {}, index(new)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if (a[k].get("sha256"), a[k]["bytes"]) != (b[k].get("sha256"), b[k]["bytes"]))
    return {"previous": old.get("built_at") if old else None, "current": new["built_at"], "added": added, "removed": removed, "changed": changed,
            "drift": bool(added or removed or changed)}


__all__ = ["CATALOG_FILE", "COLLECTIONS", "build_catalog", "load_catalog", "reconcile", "save_catalog", "search"]
