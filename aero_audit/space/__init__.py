"""Space intake: NASA open assets and launch footage brought into the same audit discipline as
ADS-B traffic (provenance on every file, physics checks on every telemetry stream).

Modules
- ``nasa3d``: catalogue and checksum-verified download from nasa/NASA-3D-Resources.
- ``nasa_images``: the NASA Image and Video Library API (images-api.nasa.gov, keyless).
- ``footage``: frames from local video, caption (SRT) event timelines, detection on frames.
- ``telemetry``: SPC-* rules over launch telemetry (speed, altitude vs time).
"""

from .nasa3d import Asset, Catalog, fetch_catalog, load_catalog, verify_blob
from .nasa_images import MediaItem, search
from .telemetry import TelemetryPoint, audit_telemetry, load_csv

__all__ = [
    "Asset", "Catalog", "MediaItem", "TelemetryPoint", "audit_telemetry", "fetch_catalog", "load_catalog", "load_csv",
    "search", "verify_blob",
]
