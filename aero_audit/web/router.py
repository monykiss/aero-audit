"""Tiny decorator router for the stdlib HTTP server. Patterns use {name} segments."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[..., Any]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler
    raw: str


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        regex = "^" + re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", path) + "$"
        self.routes.append(Route(method.upper(), re.compile(regex), handler, path))

    def route(self, method: str, path: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.add(method, path, fn)
            return fn

        return deco

    def match(self, method: str, path: str) -> tuple[Handler, dict[str, str]] | None:
        for r in self.routes:
            if r.method != method.upper():
                continue
            m = r.pattern.match(path)
            if m:
                return r.handler, m.groupdict()
        return None

    def describe(self) -> list[dict[str, str]]:
        return [{"method": r.method, "path": r.raw, "handler": r.handler.__name__} for r in self.routes]
