"""nasa/NASA-3D-Resources intake: catalogue the repository without cloning its 5 GB, then fetch
individual assets with integrity verification against git's own blob hash.

The GitHub tree API lists every file with its blob SHA-1. A downloaded file is accepted only when
``sha1(b"blob <len>\\0" + bytes)`` equals that id, so a corrupted or substituted download is refused
before it reaches disk. Each accepted file gets a ``.provenance.json`` sidecar (source URL, blob
SHA-1, SHA-256, size, licence, fetch time).

Terms: the repository's README states the assets are "free and without copyright"; ``meta.json``
lists the NASA Open Source Agreement 1.3; NASA's media usage guidelines still apply (no implied
endorsement, NASA insignia rules). The catalogue carries that text with every asset.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..config import settings
from ..ingest.http import download_file, get_json

REPO = "nasa/NASA-3D-Resources"
DEFAULT_REF = "master"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/{{ref}}"
LICENCE = ("NASA Open Source Agreement 1.3 (meta.json); README: assets are free and without copyright; "
           "NASA media usage guidelines apply: https://www.nasa.gov/nasa-brand-center/images-and-media")
CATALOG_FILE = Path("data/space/nasa3d_catalog.json")
ASSETS_DIR = Path("data/space/nasa3d")

MODEL_EXT = {"glb", "gltf", "stl", "obj", "fbx", "blend", "3ds", "lwo", "lws", "dae", "usdz", "ma", "mb", "max"}
IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp", "exr", "hdr", "gif"}
ARCHIVE_EXT = {"7z", "zip", "rar", "gz", "tgz", "tar"}
DOC_EXT = {"pdf", "txt", "md", "json", "csv"}


def kind_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if re.fullmatch(r"\d{3}", ext):  # split archives: name.7z.001
        return "archive"
    if ext in MODEL_EXT:
        return "model"
    if ext in IMAGE_EXT:
        return "image"
    if ext in ARCHIVE_EXT:
        return "archive"
    if ext in DOC_EXT:
        return "doc"
    return "other"


@dataclass(frozen=True)
class Asset:
    path: str
    size: int
    sha: str  # git blob SHA-1
    kind: str
    category: str  # top-level folder: "3D Models", "3D Printing", "Images and Textures"
    subject: str  # second-level folder, e.g. "International Space Station (ISS) (A)"

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def raw_url(self, ref: str = DEFAULT_REF) -> str:
        return f"{RAW_BASE}/{ref}/{quote(self.path)}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "name": self.name, "raw_url": self.raw_url()}


@dataclass
class Catalog:
    ref: str
    fetched_at: float
    assets: list[Asset] = field(default_factory=list)
    licence: str = LICENCE

    def filter(self, kind: str | None = None, subject: str | None = None, category: str | None = None,
               max_bytes: int | None = None) -> list[Asset]:
        rx = re.compile(subject, re.IGNORECASE) if subject else None
        out = []
        for a in self.assets:
            if kind and a.kind != kind:
                continue
            if category and a.category.lower() != category.lower():
                continue
            if rx and not (rx.search(a.subject) or rx.search(a.path)):
                continue
            if max_bytes is not None and a.size > max_bytes:
                continue
            out.append(a)
        return out

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_cat: dict[str, int] = {}
        total = 0
        for a in self.assets:
            by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
            by_cat[a.category] = by_cat.get(a.category, 0) + 1
            total += a.size
        return {"ref": self.ref, "assets": len(self.assets), "bytes": total, "by_kind": by_kind, "by_category": by_cat,
                "subjects": len({a.subject for a in self.assets})}

    def to_dict(self) -> dict[str, Any]:
        return {"repo": REPO, "ref": self.ref, "fetched_at": self.fetched_at, "licence": self.licence,
                "summary": self.summary(), "assets": [a.to_dict() for a in self.assets]}


def parse_tree(tree: dict[str, Any], ref: str = DEFAULT_REF, fetched_at: float | None = None) -> Catalog:
    """Build a catalogue from a GitHub ``git/trees/<ref>?recursive=1`` payload."""
    assets: list[Asset] = []
    for e in tree.get("tree", []):
        if e.get("type") != "blob":
            continue
        parts = e["path"].split("/")
        if len(parts) < 2:
            continue  # README, meta.json, dotfiles
        category = parts[0]
        subject = parts[1] if len(parts) > 2 else parts[-1].rsplit(".", 1)[0]
        assets.append(Asset(e["path"], int(e.get("size") or 0), e["sha"], kind_of(e["path"]), category, subject))
    return Catalog(ref, fetched_at or time.time(), assets)


def _headers() -> dict[str, str]:
    h = {"User-Agent": settings.user_agent, "Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"  # raises the anonymous 60/h limit; never logged
    return h


async def fetch_catalog(ref: str = DEFAULT_REF) -> Catalog:
    async with httpx.AsyncClient(timeout=60) as client:
        tree = await get_json(client, TREE_URL.format(ref=ref), {"recursive": "1"}, _headers())
    if tree.get("truncated"):
        raise RuntimeError("GitHub truncated the tree listing; catalogue would be incomplete")
    return parse_tree(tree, ref)


def save_catalog(cat: Catalog, path: str | Path = CATALOG_FILE) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cat.to_dict(), indent=1))
    return p


def load_catalog(path: str | Path = CATALOG_FILE) -> Catalog:
    d = json.loads(Path(path).read_text())
    return Catalog(d["ref"], d["fetched_at"], [Asset(a["path"], a["size"], a["sha"], a["kind"], a["category"], a["subject"])
                                              for a in d["assets"]], d.get("licence", LICENCE))


def blob_sha1(data: bytes) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    h.update(f"blob {len(data)}\0".encode())
    h.update(data)
    return h.hexdigest()


def verify_blob(data: bytes, expected_sha: str) -> bool:
    return blob_sha1(data) == expected_sha


def safe_local_path(dest_dir: Path, asset: Asset) -> Path:
    """Mirror the repository layout under dest_dir; refuse any path that escapes it."""
    base = os.path.realpath(dest_dir)
    target = os.path.normpath(os.path.join(base, asset.path))
    if not target.startswith(base + os.sep):
        raise PermissionError(f"asset path escapes the destination: {asset.path}")
    return Path(target)


async def download(asset: Asset, dest_dir: str | Path = ASSETS_DIR, ref: str = DEFAULT_REF,
                   max_bytes: int = 200_000_000) -> Path:
    """Fetch one asset, verify it against its git blob id, write it plus a provenance sidecar."""
    if asset.size > max_bytes:
        raise ValueError(f"{asset.name} is {asset.size} bytes; raise max_bytes to fetch it")
    target = safe_local_path(Path(dest_dir), asset)
    if target.is_file() and verify_blob(target.read_bytes(), asset.sha):
        return target
    url = asset.raw_url(ref)
    tmp = target.with_name(target.name + ".part")
    size, sha256 = await asyncio.to_thread(download_file, url, tmp, None, max_bytes)
    data = await asyncio.to_thread(tmp.read_bytes)
    if not verify_blob(data, asset.sha):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"integrity check failed for {asset.path}: blob sha1 mismatch (expected {asset.sha[:12]})")
    tmp.replace(target)
    prov = {"source": url, "repo": REPO, "ref": ref, "path": asset.path, "git_blob_sha1": asset.sha,
            "sha256": sha256, "bytes": size, "licence": LICENCE,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    target.with_name(target.name + ".provenance.json").write_text(json.dumps(prov, indent=1))
    return target


__all__ = ["ASSETS_DIR", "CATALOG_FILE", "LICENCE", "REPO", "Asset", "Catalog", "blob_sha1", "download", "fetch_catalog",
           "kind_of", "load_catalog", "parse_tree", "safe_local_path", "save_catalog", "verify_blob"]
