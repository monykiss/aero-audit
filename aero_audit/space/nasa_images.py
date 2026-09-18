"""NASA Image and Video Library (images-api.nasa.gov): search, asset variants, verified download.

Keyless and public. Each item has a ``nasa_id``, metadata (title, date, centre, keywords, an
optional ``photographer``/``secondary_creator`` and, rarely, a ``copyright`` line that must be
honoured), and a ``collection.json`` listing every rendition (``~orig``, ``~large``, ``~medium``,
``~small``/``~mobile``, ``~thumb``, plus ``.srt`` captions and ``metadata.json`` for video).
Launch footage of NASA missions, including SpaceX crew flights flown for NASA, lives here in the
public domain; SpaceX's own webcasts do not, and this module never fetches from anywhere else.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..ingest.http import download_file, get_json

API = "https://images-api.nasa.gov/search"
ASSETS_HOST = "images-assets.nasa.gov"
MEDIA_DIR = Path("data/space/nasa_media")
TERMS = ("NASA content is generally not subject to copyright in the United States; individual items may carry a "
         "'copyright' field (respect it) and NASA insignia / identifiable people rules apply: "
         "https://www.nasa.gov/nasa-brand-center/images-and-media")


@dataclass
class MediaItem:
    nasa_id: str
    title: str
    media_type: str
    date_created: str
    center: str | None
    description: str
    keywords: list[str] = field(default_factory=list)
    copyright: str | None = None
    photographer: str | None = None
    collection_href: str = ""
    thumbnail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_search(payload: dict[str, Any]) -> tuple[list[MediaItem], int]:
    coll = payload.get("collection", {})
    items = []
    for it in coll.get("items", []):
        d = (it.get("data") or [{}])[0]
        thumb = next((ln.get("href") for ln in it.get("links", []) if ln.get("rel") == "preview"), None)
        items.append(MediaItem(
            nasa_id=d.get("nasa_id", ""), title=d.get("title", ""), media_type=d.get("media_type", ""),
            date_created=d.get("date_created", ""), center=d.get("center"), description=d.get("description", ""),
            keywords=list(d.get("keywords") or []), copyright=d.get("copyright") or None,
            photographer=d.get("photographer") or d.get("secondary_creator") or None,
            collection_href=it.get("href", ""), thumbnail=thumb))
    total = int(coll.get("metadata", {}).get("total_hits") or 0)
    return items, total


async def search(q: str, media_type: str | None = None, year_start: int | None = None, year_end: int | None = None,
                 page_size: int = 25, page: int = 1, center: str | None = None) -> tuple[list[MediaItem], int]:
    params: dict[str, Any] = {"q": q, "page_size": min(max(page_size, 1), 100), "page": page}
    if media_type:
        params["media_type"] = media_type
    if year_start:
        params["year_start"] = year_start
    if year_end:
        params["year_end"] = year_end
    if center:
        params["center"] = center
    async with httpx.AsyncClient(timeout=30) as client:
        payload = await get_json(client, API, params, {"User-Agent": settings.user_agent})
    return parse_search(payload)


async def assets(item: MediaItem) -> list[str]:
    """Every rendition URL for the item (from its collection.json)."""
    async with httpx.AsyncClient(timeout=30) as client:
        urls = await get_json(client, item.collection_href, None, {"User-Agent": settings.user_agent})
    return [u.replace("http://", "https://", 1) for u in urls if isinstance(u, str)]


VARIANT_RX = {"orig": r"~orig\.", "large": r"~large\.", "medium": r"~medium\.", "small": r"~small\.", "mobile": r"~mobile\.",
              "thumb": r"~thumb\.", "captions": r"\.srt$", "metadata": r"metadata\.json$"}


def pick(urls: list[str], variant: str) -> str | None:
    rx = VARIANT_RX.get(variant)
    if not rx:
        raise ValueError(f"unknown variant {variant}; known: {', '.join(VARIANT_RX)}")
    return next((u for u in urls if re.search(rx, u)), None)


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120]


async def download(item: MediaItem, variant: str = "medium", dest_dir: str | Path = MEDIA_DIR,
                   max_bytes: int = 500_000_000) -> Path:
    urls = await assets(item)
    url = pick(urls, variant)
    if not url:
        raise FileNotFoundError(f"{item.nasa_id} has no '{variant}' rendition; available: {[u.rsplit('/', 1)[-1] for u in urls]}")
    if ASSETS_HOST not in url:
        raise PermissionError(f"refusing to fetch from {url}: not the NASA assets host")
    dest = Path(dest_dir) / item.media_type / _safe_name(item.nasa_id)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / _safe_name(url.rsplit("/", 1)[-1])
    size, sha256 = await asyncio.to_thread(download_file, url, target, None, max_bytes, 600.0)
    prov = {"source": url, "nasa_id": item.nasa_id, "title": item.title, "media_type": item.media_type,
            "date_created": item.date_created, "center": item.center, "copyright": item.copyright,
            "photographer": item.photographer, "variant": variant, "sha256": sha256, "bytes": size,
            "terms": TERMS, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    target.with_name(target.name + ".provenance.json").write_text(json.dumps(prov, indent=1))
    _append_manifest(prov, dest_dir)
    return target


def _append_manifest(prov: dict[str, Any], dest_dir: str | Path) -> None:
    mf = Path(dest_dir) / "manifest.json"
    try:
        entries = json.loads(mf.read_text())
    except (OSError, ValueError):
        entries = []
    entries = [e for e in entries if e.get("source") != prov["source"]] + [prov]
    mf.write_text(json.dumps(entries, indent=1))


def verify_downloads(dest_dir: str | Path = MEDIA_DIR) -> dict[str, Any]:
    """Re-hash every file named in the manifest."""
    mf = Path(dest_dir) / "manifest.json"
    out: dict[str, Any] = {"ok": True, "checked": 0, "bad": []}
    try:
        entries = json.loads(mf.read_text())
    except (OSError, ValueError):
        out["error"] = "no manifest"
        return out
    import hashlib

    for e in entries:
        p = Path(dest_dir) / e["media_type"] / _safe_name(e["nasa_id"]) / _safe_name(e["source"].rsplit("/", 1)[-1])
        out["checked"] += 1
        try:
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            actual = None
        if actual != e["sha256"]:
            out["ok"] = False
            out["bad"].append(str(p))
    return out


__all__ = ["MEDIA_DIR", "TERMS", "VARIANT_RX", "MediaItem", "assets", "download", "parse_search", "pick", "search",
           "verify_downloads"]
