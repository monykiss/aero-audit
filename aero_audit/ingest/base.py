from __future__ import annotations

from typing import Protocol

from ..config import Region
from ..models import Batch


class Provider(Protocol):
    name: str

    async def fetch(self, region: Region) -> Batch:
        """Return one batch of state vectors for the region."""

    async def aclose(self) -> None:
        """Release the HTTP client."""
