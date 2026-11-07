"""Telegram notifications and an optional dead-man's-switch ping.

Configured from the environment:
- ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` — message on every order,
  every guard decision and the daily 00:05 summary.
- ``HEALTHCHECK_URL`` — pinged by the guard each minute during sessions; set up
  the external monitor (e.g. healthchecks.io) with a 10-minute grace so a dead
  VPS pages you. Telegram alone cannot alert on its own silence.

Notification failures are logged and swallowed: an alerting outage must never
stop the guard from flattening.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)
Poster = Callable[[str, bytes], None]


def _post(url: str, body: bytes) -> None:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10):
        pass


class Notifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        healthcheck_url: str | None = None,
        post: Poster = _post,
        prefix: str = "",
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.healthcheck_url = healthcheck_url
        self._post = post
        self.prefix = prefix
        self.sent: list[str] = []

    @classmethod
    def from_env(cls, prefix: str = "") -> Notifier:
        return cls(
            os.environ.get("TELEGRAM_BOT_TOKEN"),
            os.environ.get("TELEGRAM_CHAT_ID"),
            os.environ.get("HEALTHCHECK_URL"),
            prefix=prefix,
        )

    def send(self, text: str) -> None:
        msg = f"{self.prefix}{text}"
        self.sent.append(msg)
        log.info("notify: %s", msg)
        if not (self.token and self.chat_id):
            return
        url = f"https://api.telegram.org/bot{urllib.parse.quote(self.token)}/sendMessage"
        try:
            self._post(url, json.dumps({"chat_id": self.chat_id, "text": msg}).encode())
        except Exception as exc:
            log.error("telegram send failed: %s", exc)

    def ping(self) -> None:
        if not self.healthcheck_url:
            return
        try:
            self._post(self.healthcheck_url, b"")
        except Exception as exc:
            log.error("healthcheck ping failed: %s", exc)
