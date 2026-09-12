"""
Connectivity monitor for FieldLine's offline-first data layer.

The voice pipeline (STT / LLM / TTS) gets its offline fallback for free from
LiveKit's built-in stt.FallbackAdapter / llm.FallbackAdapter /
tts.FallbackAdapter -- see local_pipeline.py. Those adapters react per-call,
automatically, with no help needed from this file.

This module exists for the *other* half of Phase 4: the Moss tool layer.
fault_history / safety_procedure / inventory_lookup / dispatch_status /
log_job_note all go through moss_client.py, which needs an explicit mode
flag to know whether to query the cloud index or the local SessionIndex.
That flag is `connectivity.is_online`.

Usage:
    from connectivity import connectivity

    connectivity.start()                          # once, at agent startup
    connectivity.on_reconnect(some_async_fn)       # optional, see moss_client.py
    if connectivity.is_online:
        ...
    connectivity.mark_offline()                    # call when a cloud call fails
    connectivity.mark_online()                     # call when a cloud call succeeds
"""

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger("fieldline.connectivity")

# Fast, reliable hosts to probe. Cloudflare and Google public DNS both answer
# in a handful of milliseconds when there is a real route to the internet,
# and neither needs an API key or has maintenance windows.
_PROBE_HOSTS: list[tuple[str, int]] = [("1.1.1.1", 53), ("8.8.8.8", 53)]
_PROBE_TIMEOUT_SECONDS = 1.5
_POLL_INTERVAL_SECONDS = 5.0
# Once we've been marked offline (e.g. by a failed call), don't let a lucky
# background ping flip us straight back online -- wait at least this long,
# so a single flaky packet doesn't cause flapping mid-call.
_MIN_SECONDS_BEFORE_AUTO_RECOVER = 3.0


class ConnectivityMonitor:
    """Tracks whether the site currently has a working internet connection."""

    def __init__(self) -> None:
        self.is_online: bool = True
        self._last_change = 0.0
        self._task: asyncio.Task | None = None
        self._on_reconnect_callbacks: list[Callable[[], Awaitable[None]]] = []

    def start(self) -> None:
        """Begin the background connectivity poll. Safe to call more than
        once -- only starts one poll loop."""
        if self._task is None:
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("connectivity monitor started")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def on_reconnect(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register an async callback to fire (in the background, without
        blocking whatever caused the reconnect) the moment we flip from
        offline back to online. moss_client.py uses this to push locally
        logged notes and re-enable the cloud index's auto-refresh."""
        self._on_reconnect_callbacks.append(callback)

    def mark_online(self) -> None:
        was_offline = not self.is_online
        if was_offline:
            logger.warning("connectivity: back ONLINE")
        self.is_online = True
        self._last_change = time.monotonic()
        if was_offline:
            for callback in self._on_reconnect_callbacks:
                asyncio.create_task(callback())

    def mark_offline(self) -> None:
        if self.is_online:
            logger.warning("connectivity: went OFFLINE")
        self.is_online = False
        self._last_change = time.monotonic()

    async def _poll_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            try:
                reachable = await loop.run_in_executor(None, _probe_internet)
                since_change = time.monotonic() - self._last_change
                if reachable and not self.is_online:
                    if since_change >= _MIN_SECONDS_BEFORE_AUTO_RECOVER:
                        self.mark_online()
                elif not reachable and self.is_online:
                    self.mark_offline()
            except Exception:
                logger.exception("connectivity poll failed, assuming offline")
                self.mark_offline()
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _probe_internet() -> bool:
    """Blocking TCP-connect probe. Runs in a background thread via
    run_in_executor so it never blocks the agent's event loop."""
    for host, port in _PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_SECONDS):
                return True
        except OSError:
            continue
    return False


# Single shared instance -- import this everywhere, don't construct your own.
connectivity = ConnectivityMonitor()