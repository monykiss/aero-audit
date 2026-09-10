import httpx
import pytest

from aero_audit.ingest import http as h


async def test_curl_json_raises_status_error_for_4xx(monkeypatch):
    class P:
        returncode = 0

        async def communicate(self):
            return b'{"error":"x"}\n429', b""

    async def fake_exec(*a, **k):
        return P()

    monkeypatch.setattr(h.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await h.curl_json("https://example.invalid/x", {"a": 1})
    assert ei.value.response.status_code == 429


async def test_curl_json_parses_body(monkeypatch):
    class P:
        returncode = 0

        async def communicate(self):
            return b'{"ac":[]}\n200', b""

    async def fake_exec(*a, **k):
        return P()

    monkeypatch.setattr(h.asyncio, "create_subprocess_exec", fake_exec)
    assert await h.curl_json("https://example.invalid/x") == {"ac": []}
