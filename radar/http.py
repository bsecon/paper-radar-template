"""One shared HTTP client with a polite user agent and retries."""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

import httpx

_client: httpx.Client | None = None
_ua = "paper-radar/0.1"


def configure(user_agent: str) -> None:
    global _client, _ua
    _ua = user_agent
    _client = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": _ua, "Accept": "*/*"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
    return _client


def get(url: str, *, params: dict[str, Any] | None = None, retries: int = 3, ok_404: bool = False) -> httpx.Response | None:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = client().get(url, params=params)
            if r.status_code == 404 and ok_404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:  # network or 4xx
            last = e
            time.sleep(1 + attempt)
    if last:
        raise last
    return None


def _curl_bytes(url: str, max_bytes: int) -> bytes | None:
    """Some hosts (NBER) reject Python HTTP clients but not curl."""
    if not shutil.which("curl"):
        return None
    try:
        out = subprocess.run(
            ["curl", "-sL", "--max-time", "120", "--max-filesize", str(max_bytes), "-A", _ua, url],
            capture_output=True, timeout=150,
        )
    except Exception:
        return None
    data = out.stdout
    return data if out.returncode == 0 and data.startswith(b"%PDF") else None


def get_bytes(url: str, max_bytes: int = 30_000_000) -> bytes | None:
    try:
        with client().stream("GET", url) as r:
            if r.status_code == 403:
                return _curl_bytes(url, max_bytes)
            if r.status_code != 200:
                return None
            ctype = r.headers.get("content-type", "")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    return None
            data = bytes(buf)
            if not data.startswith(b"%PDF") and "pdf" not in ctype:
                return None
            return data
    except httpx.HTTPError:
        return None
