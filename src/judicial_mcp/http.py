"""Polite HTTP client for cons.judicial.gov.tw."""

from __future__ import annotations

import logging
import ssl
import time
from pathlib import Path

import httpx

from judicial_mcp.config import USER_AGENT, Settings

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    # The site's certificate lacks a Subject Key Identifier, which Python 3.13's
    # default VERIFY_X509_STRICT rejects. Keep full chain/hostname verification,
    # relax only that strictness flag.
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


class PoliteClient:
    """Rate-limited client with retries. Use as a context manager."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._client = httpx.Client(
            transport=transport,
            verify=_ssl_context(),
            timeout=settings.timeout_s,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._last_request = 0.0

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._settings.request_delay_s:
            time.sleep(self._settings.request_delay_s - elapsed)
        self._last_request = time.monotonic()

    def _with_retries(self, url: str, action):  # noqa: ANN001, ANN202
        last_error: Exception | None = None
        for attempt in range(1, self._settings.max_retries + 1):
            self._wait()
            try:
                return action()
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                log.warning("fetch %s failed (attempt %d): %s", url, attempt, exc)
                if attempt < self._settings.max_retries:
                    time.sleep(self._settings.request_delay_s * 2**attempt)
        raise FetchError(f"{url}: {last_error}") from last_error

    def get_text(self, url: str) -> str:
        def action() -> str:
            response = self._client.get(url)
            response.raise_for_status()
            return response.text

        return self._with_retries(url, action)

    def download(self, url: str, dest: Path) -> tuple[str, int]:
        """Stream a file to `dest`; returns (content-type, size). Writes atomically."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")

        def action() -> tuple[str, int]:
            size = 0
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                with tmp.open("wb") as fh:
                    for chunk in response.iter_bytes(1 << 16):
                        fh.write(chunk)
                        size += len(chunk)
            tmp.replace(dest)
            return content_type, size

        try:
            return self._with_retries(url, action)
        finally:
            tmp.unlink(missing_ok=True)
