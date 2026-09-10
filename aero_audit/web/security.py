"""Request guard for the local app: who may talk to it, from where, and with which files.

A server on 127.0.0.1 is not private by default. Any web page the user has open can send
requests to it, and a hostile page can point its own DNS name at 127.0.0.1 (DNS rebinding) to
read responses. This module closes those doors without a login screen:

- **Host validation.** Requests must carry a loopback ``Host`` (localhost, 127.0.0.1, ::1) or
  one explicitly allowed; rebinding uses the attacker's hostname, which fails.
- **CSRF token.** Every POST must carry a per-process token in ``X-Aero-Token``. A custom header
  turns a "simple" cross-site request into one that needs a CORS preflight, which this server
  never grants. ``Origin`` and ``Sec-Fetch-Site`` are checked too, and POST bodies must be JSON.
- **Remote mode.** Binding to a non-loopback address requires a shared token on every API call
  (``--token`` or ``AERO_APP_TOKEN``) or an explicit ``--allow-unauthenticated`` for a container
  whose port the host publishes on loopback only.
- **Path confinement.** Every user-supplied path (recordings, models, watchlists, logs) must
  resolve inside a project directory; ``safe_path`` is the only way parameters become paths.
- **Response headers.** A strict Content-Security-Policy and the usual hardening headers on
  every response, so a bug in a report or a tile URL cannot become script execution.

Modes: ``loopback`` (default), ``token`` (remote bind with a shared secret), ``open`` (remote bind,
explicitly unauthenticated; Host validation still applies).
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

TOKEN_HEADER = "X-Aero-Token"
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
MAX_BODY_BYTES = 1_000_000

APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "geolocation=(), camera=(), microphone=(), payment=(), usb=()"),
    ("Cache-Control", "no-store"),
)


class Denied(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _is_loopback(host: str) -> bool:
    try:
        return host in LOOPBACK_NAMES or ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def host_of(header: str) -> str:
    """Hostname part of a Host/Origin netloc, lower-cased, brackets kept for IPv6."""
    h = (header or "").strip().lower()
    if h.startswith("["):
        return h.split("]")[0] + "]"
    return h.split(":")[0]


class Guard:
    def __init__(self, bind_host: str = "127.0.0.1", token: str | None = None,
                 allow_unauthenticated: bool = False, allowed_hosts: Iterable[str] = ()) -> None:
        self.bind_host = bind_host
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        loopback_bind = _is_loopback(bind_host)
        if loopback_bind:
            self.mode = "loopback"
        elif token:
            self.mode = "token"
        elif allow_unauthenticated:
            self.mode = "open"
        else:
            raise ValueError(
                f"binding to {bind_host} exposes the app beyond this machine; pass --token (or set "
                "AERO_APP_TOKEN) or --allow-unauthenticated if the port is only published on loopback"
            )
        self.token = token or ""
        self.csrf = secrets.token_urlsafe(24)
        if not loopback_bind and bind_host not in ("0.0.0.0", "::"):
            self.allowed_hosts.add(bind_host.lower())

    # ---- checks ----------------------------------------------------------------------------
    def host_ok(self, host_header: str) -> bool:
        if self.mode == "token":
            return True  # the shared secret is the control; hostnames are whatever the deployment uses
        h = host_of(host_header)
        return _is_loopback(h) or h in self.allowed_hosts

    def expected_token(self) -> str:
        return self.token if self.mode == "token" else self.csrf

    def check(self, method: str, path: str, headers: Any) -> None:
        """Raise Denied for a request that must not reach a handler."""
        host = headers.get("Host", "")
        if not self.host_ok(host):
            raise Denied(403, "host header not allowed (loopback names only)")
        api = path.startswith("/api/")
        presented = headers.get(TOKEN_HEADER, "")
        if self.mode == "token" and api and not hmac.compare_digest(presented, self.token):
            raise Denied(401, "access token required")
        if method == "POST":
            if not api:
                raise Denied(405, "POST is only accepted on the API")
            ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise Denied(415, "POST bodies must be application/json")
            origin = headers.get("Origin")
            if origin and not self.origin_ok(origin, host):
                raise Denied(403, "cross-origin request refused")
            fetch_site = headers.get("Sec-Fetch-Site")
            if fetch_site and fetch_site not in ("same-origin", "none"):
                raise Denied(403, "cross-site request refused")
            if not hmac.compare_digest(presented, self.expected_token()):
                raise Denied(403, f"missing or wrong {TOKEN_HEADER}")
        try:
            n = int(headers.get("Content-Length") or 0)
        except ValueError as e:
            raise Denied(400, "bad Content-Length") from e
        if n > MAX_BODY_BYTES:
            raise Denied(413, "request body too large")

    @staticmethod
    def origin_ok(origin: str, host_header: str) -> bool:
        if origin.strip().lower() == "null":
            return False
        parts = urlsplit(origin.strip().lower())
        return parts.scheme in ("http", "https") and parts.netloc == (host_header or "").strip().lower()

    # ---- headers ---------------------------------------------------------------------------
    @staticmethod
    def response_headers(report: bool = False) -> list[tuple[str, str]]:
        """Constant hardening headers; reports get a stricter, script-free policy."""
        return [("Content-Security-Policy", REPORT_CSP if report else APP_CSP), *SECURITY_HEADERS]

    def describe(self) -> dict[str, Any]:
        """What the front end needs: the mode and, unless a shared secret is in force, the CSRF token."""
        return {"mode": self.mode, "csrf": None if self.mode == "token" else self.csrf, "header": TOKEN_HEADER,
                "bind_host": self.bind_host}


# ---- paths -------------------------------------------------------------------------------------
def safe_path(value: Any, roots: Iterable[str | Path], suffixes: Iterable[str] = (), must_exist: bool = True) -> Path:
    """Resolve a user-supplied path and require it to live under one of ``roots``.

    Returns the path relative to the working directory when possible (nicer labels), otherwise the
    resolved absolute path. Raises PermissionError outside the roots or with a wrong suffix, and
    FileNotFoundError when ``must_exist`` and the file is missing.
    """
    if value is None or str(value).strip() == "":
        raise FileNotFoundError("empty path")
    raw = str(value)
    if "\x00" in raw:
        raise PermissionError("invalid path")
    p = Path(raw).expanduser()
    resolved = p.resolve()
    suffixes = tuple(suffixes)
    for root in roots:
        try:
            rr = Path(root).resolve()
        except OSError:
            continue
        if resolved == rr or not resolved.is_relative_to(rr):
            continue
        if suffixes and not any(resolved.name.endswith(s) for s in suffixes):
            raise PermissionError(f"{resolved.name}: expected one of {', '.join(suffixes)}")
        if must_exist and not resolved.is_file():
            raise FileNotFoundError(f"not found: {raw}")
        try:
            return resolved.relative_to(Path.cwd())
        except ValueError:
            return resolved
    raise PermissionError(f"path outside the allowed directories ({', '.join(str(r) for r in roots)}): {raw}")


def safe_url(value: Any) -> str:
    """Webhook URLs: http(s) only, no credentials in the URL, empty allowed (means off)."""
    s = str(value or "").strip()
    if not s:
        return ""
    parts = urlsplit(s)
    if parts.scheme not in ("http", "https") or not parts.netloc or "@" in parts.netloc:
        raise ValueError("webhook must be an http(s) URL without embedded credentials")
    return s


__all__ = ["APP_CSP", "MAX_BODY_BYTES", "TOKEN_HEADER", "Denied", "Guard", "host_of", "safe_path", "safe_url"]
