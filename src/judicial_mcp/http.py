"""Polite HTTP client for cons.judicial.gov.tw."""

from __future__ import annotations

import logging
import socket
import ssl
import threading
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


# Total time allowed for one file. The site sometimes stalls mid-transfer with the TLS
# connection still open, so the per-read timeout never fires; this bounds it.
MAX_DOWNLOAD_SECONDS = 600.0


class _Watchdog:
    """Shut down the response's socket if a transfer exceeds its deadline.

    A blocked SSL read cannot be interrupted from the reading thread, so a timer
    thread shuts the socket down, which makes the read fail and the retry kick in.
    """

    def __init__(self, response: httpx.Response, seconds: float) -> None:
        self._response = response
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True

    def _fire(self) -> None:
        stream = self._response.extensions.get("network_stream")
        sock = stream.get_extra_info("socket") if stream is not None else None
        log.warning("download stalled; aborting %s", self._response.request.url)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed

    def __enter__(self) -> _Watchdog:
        self._timer.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._timer.cancel()


class PoliteClient:
    """Rate-limited client with retries. Use as a context manager."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        max_download_s: float = MAX_DOWNLOAD_SECONDS,
    ) -> None:
        self._settings = settings
        self._max_download_s = max_download_s
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
            deadline = time.monotonic() + self._max_download_s
            with self._client.stream("GET", url) as response, _Watchdog(response, self._max_download_s):
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                with tmp.open("wb") as fh:
                    for chunk in response.iter_bytes(1 << 16):
                        if time.monotonic() > deadline:
                            raise httpx.ReadTimeout(f"download exceeded {self._max_download_s:.0f}s")
                        fh.write(chunk)
                        size += len(chunk)
            tmp.replace(dest)
            return content_type, size

        try:
            return self._with_retries(url, action)
        finally:
            tmp.unlink(missing_ok=True)
