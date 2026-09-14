"""Robust IBKR connection management on top of ``ib_insync``.

Responsibilities:

* Connect to TWS / IB Gateway (paper or live port, from config).
* Active heartbeat: periodically round-trips ``reqCurrentTimeAsync``; a
  configurable number of consecutive misses is treated as a dead socket even
  if the TCP connection still *looks* open.
* Auto-reconnect with exponential backoff + jitter when the socket drops,
  firing ``on_connected`` / ``on_disconnected`` callbacks so the application
  can re-subscribe market data and reconcile order state after each recovery.

This is the only "core" module that imports ``ib_insync``.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional

from ib_insync import IB

from .config import ConnectionConfig

log = logging.getLogger(__name__)

AsyncCallback = Callable[[], Awaitable[None]]


class ConnectionError_(RuntimeError):
    """Raised when the connection cannot be established within the configured
    retry budget (``reconnect_max_attempts`` > 0 and exhausted)."""


class IBConnectionManager:
    """Owns the ``IB`` instance and keeps it alive.

    Usage::

        conn = IBConnectionManager(cfg.connection,
                                   on_connected=resubscribe,
                                   on_disconnected=pause_trading)
        await conn.start()          # blocks until first successful connect
        ...
        await conn.stop()           # cancels tasks and disconnects cleanly
    """

    def __init__(
        self,
        config: ConnectionConfig,
        on_connected: Optional[AsyncCallback] = None,
        on_disconnected: Optional[AsyncCallback] = None,
    ) -> None:
        self._cfg = config
        self._ib = IB()
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._supervisor_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._disconnect_evt = asyncio.Event()
        self._connected_evt = asyncio.Event()
        self._stopping = False
        self._ib.disconnectedEvent += self._handle_disconnected

    # ------------------------------------------------------------------ API

    @property
    def ib(self) -> IB:
        """The managed ``ib_insync.IB`` instance."""
        return self._ib

    @property
    def is_connected(self) -> bool:
        return self._ib.isConnected()

    async def start(self) -> None:
        """Connect (with retries) and launch the supervision tasks."""
        self._stopping = False
        await self._connect_with_backoff(first=True)
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name="ib-conn-supervisor")

    async def stop(self) -> None:
        """Tear everything down; safe to call more than once."""
        self._stopping = True
        for task in (self._supervisor_task, self._heartbeat_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._supervisor_task = None
        self._heartbeat_task = None
        if self._ib.isConnected():
            self._ib.disconnect()
        log.info("connection manager stopped")

    async def wait_connected(self) -> None:
        """Block until the connection is (re-)established."""
        await self._connected_evt.wait()

    # ------------------------------------------------------- connect logic

    async def _connect_once(self) -> None:
        cfg = self._cfg
        log.info("connecting to IBKR at %s:%d (clientId=%d)",
                 cfg.host, cfg.port, cfg.client_id)
        await asyncio.wait_for(
            self._ib.connectAsync(
                host=cfg.host, port=cfg.port, clientId=cfg.client_id,
                account=cfg.account or "",
                timeout=cfg.connect_timeout_s),
            timeout=cfg.connect_timeout_s + 5.0,
        )
        log.info("connected: serverVersion=%s accounts=%s",
                 self._ib.client.serverVersion(),
                 self._ib.managedAccounts())

    async def _connect_with_backoff(self, first: bool = False) -> None:
        """Try to connect until success or the retry budget is exhausted."""
        cfg = self._cfg
        attempt = 0
        while not self._stopping:
            try:
                await self._connect_once()
            except (asyncio.TimeoutError, ConnectionRefusedError,
                    OSError, Exception) as exc:
                attempt += 1
                if 0 < cfg.reconnect_max_attempts <= attempt:
                    raise ConnectionError_(
                        f"giving up after {attempt} connection attempts: {exc}"
                    ) from exc
                delay = min(
                    cfg.reconnect_backoff_base_s * (2 ** (attempt - 1)),
                    cfg.reconnect_backoff_max_s,
                )
                delay *= 0.75 + random.random() * 0.5  # +/-25% jitter
                log.warning(
                    "connect attempt %d failed (%s: %s); retrying in %.1fs",
                    attempt, type(exc).__name__, exc, delay)
                await asyncio.sleep(delay)
                continue
            # Success.
            self._disconnect_evt.clear()
            self._connected_evt.set()
            self._start_heartbeat()
            if self._on_connected is not None:
                try:
                    await self._on_connected()
                except Exception:
                    log.exception("on_connected callback failed")
            return
        if first:
            raise ConnectionError_("stopped before first connection")

    # --------------------------------------------------------- supervision

    def _handle_disconnected(self) -> None:
        """ib_insync event: socket dropped."""
        if self._stopping:
            return
        log.warning("IBKR socket disconnected")
        self._connected_evt.clear()
        self._disconnect_evt.set()

    async def _supervise(self) -> None:
        """Wait for disconnects and drive reconnection forever."""
        while not self._stopping:
            await self._disconnect_evt.wait()
            self._disconnect_evt.clear()
            if self._stopping:
                return
            self._stop_heartbeat()
            if self._on_disconnected is not None:
                try:
                    await self._on_disconnected()
                except Exception:
                    log.exception("on_disconnected callback failed")
            # Make sure the client is fully torn down before reconnecting.
            if self._ib.isConnected():
                try:
                    self._ib.disconnect()
                except Exception:
                    log.exception("error during disconnect cleanup")
            log.info("starting reconnection loop")
            await self._connect_with_backoff()

    # ----------------------------------------------------------- heartbeat

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="ib-heartbeat")

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Round-trip the API regularly; escalate repeated misses to a
        disconnect so the supervisor reconnects even on a half-open socket."""
        cfg = self._cfg
        misses = 0
        try:
            while True:
                await asyncio.sleep(cfg.heartbeat_interval_s)
                if not self._ib.isConnected():
                    # disconnectedEvent should already have fired; make sure.
                    self._handle_disconnected()
                    return
                try:
                    await asyncio.wait_for(
                        self._ib.reqCurrentTimeAsync(),
                        timeout=cfg.heartbeat_timeout_s)
                    misses = 0
                except (asyncio.TimeoutError, Exception) as exc:
                    misses += 1
                    log.warning("heartbeat miss %d/%d (%s)",
                                misses, cfg.heartbeat_max_misses, exc)
                    if misses >= cfg.heartbeat_max_misses:
                        log.error(
                            "heartbeat failed %d times; forcing reconnect",
                            misses)
                        try:
                            self._ib.disconnect()
                        finally:
                            self._handle_disconnected()
                        return
        except asyncio.CancelledError:
            raise
