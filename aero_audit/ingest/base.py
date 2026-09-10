from __future__ import annotations

from typing import Protocol

from ..config import Region
from ..models import Batch


class Provider(Protocol):
    name: str

    async def fetch(self, region: Region) -> Batch: ...

    async def aclose(self) -> None: ...
