"""Telegram alerts + a read-only command console.

Design rules:

* **Credentials only from the environment.** :func:`notifier_from_env`
  reads the bot token and chat id from the env-var *names* given in
  config; the values are never logged or persisted.
* **The console has no order entry.** ``/status``, ``/positions``,
  ``/orders`` and ``/help`` answer questions; the operator commands the
  app registers (``/pause``, ``/resume``, ``/halt CONFIRM``) can only
  reduce or stop activity — nothing sent from a phone can buy, sell, or
  size anything. Clearing a halt stays at the keyboard
  (``--reset-kill-switch``) so a human looks at the account first.
* **Only the configured chat is answered.** Messages from any other chat
  are ignored (and counted), so a leaked bot username cannot be used to
  read the book.
* **Failures never reach the trading loop.** Every network call is
  wrapped; a Telegram outage degrades to log lines.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol

log = logging.getLogger(__name__)

#: Telegram caps messages at 4096 chars; keep alerts comfortably below.
MAX_MESSAGE_CHARS = 3900


class TelegramTransport(Protocol):
    """Minimal HTTP surface the notifier needs; swapped for a fake in tests."""

    def post(self, method: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """POST ``payload`` to Bot API ``method``; return the decoded JSON."""


class UrllibTransport:
    """Real Bot API transport over ``urllib`` (no third-party dependency)."""

    def __init__(self, token: str, timeout_s: float = 10.0,
                 base_url: str = "https://api.telegram.org") -> None:
        if not token:
            raise ValueError("Telegram bot token is empty")
        self._token = token
        self._timeout = timeout_s
        self._base = base_url.rstrip("/")

    def post(self, method: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        url = f"{self._base}/bot{self._token}/{method}"
        data = urllib.parse.urlencode(
            {k: v for k, v in payload.items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:200]
            # Never include the URL (it carries the token) in the error.
            raise RuntimeError(
                f"Telegram {method} failed: HTTP {exc.code} {body}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Telegram {method} unreachable: {exc.reason}") from None


class TelegramNotifier:
    """Sends alerts to one chat. ``send`` never raises."""

    def __init__(self, chat_id: str, transport: TelegramTransport) -> None:
        if not chat_id:
            raise ValueError("Telegram chat id is empty")
        self.chat_id = str(chat_id)
        self._transport = transport
        self.sent: int = 0
        self.failed: int = 0

    def send(self, text: str) -> bool:
        """Deliver ``text``; returns True on success, logs on failure."""
        text = text if len(text) <= MAX_MESSAGE_CHARS else \
            text[:MAX_MESSAGE_CHARS - 1] + "…"
        try:
            resp = self._transport.post("sendMessage", {
                "chat_id": self.chat_id, "text": text,
                "disable_web_page_preview": True})
            if not resp.get("ok", False):
                raise RuntimeError(resp.get("description", "not ok"))
        except Exception as exc:
            self.failed += 1
            log.warning("telegram send failed (%d so far): %s",
                        self.failed, exc)
            return False
        self.sent += 1
        return True


#: A handler receives the text after the command ("" if none).
CommandHandler = Callable[[str], str]


class TelegramConsole:
    """Answers read-only slash commands from the configured chat.

    Handlers take the argument text and return the reply; the app
    registers them (``/status`` etc.). Unknown commands get the help
    text. ``poll_once`` is synchronous and safe to run in a thread.
    """

    def __init__(self, notifier: TelegramNotifier,
                 transport: TelegramTransport,
                 handlers: Optional[Mapping[str, CommandHandler]] = None,
                 poll_timeout_s: int = 2) -> None:
        self._notifier = notifier
        self._transport = transport
        self._handlers: Dict[str, CommandHandler] = dict(handlers or {})
        self._poll_timeout = poll_timeout_s
        self._offset: Optional[int] = None
        self.ignored_foreign: int = 0
        self.handled: int = 0

    def register(self, command: str, handler: CommandHandler) -> None:
        if not command.startswith("/"):
            raise ValueError("commands start with '/'")
        self._handlers[command] = handler

    @property
    def commands(self) -> List[str]:
        return sorted(self._handlers)

    def help_text(self) -> str:
        return "commands: " + " ".join(self.commands + ["/help"])

    def dispatch(self, text: str) -> str:
        """Map one message to its reply (pure; no network)."""
        parts = text.strip().split(None, 1)
        cmd = parts[0].split("@", 1)[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "/help" or cmd not in self._handlers:
            return self.help_text()
        try:
            return self._handlers[cmd](args)
        except Exception as exc:  # a handler bug must not kill the console
            log.exception("telegram command %s failed", cmd)
            return f"{cmd} failed: {type(exc).__name__}: {exc}"

    def poll_once(self) -> int:
        """Fetch pending updates, answer those from our chat; returns the
        number handled. Never raises."""
        try:
            resp = self._transport.post("getUpdates", {
                "offset": self._offset, "timeout": self._poll_timeout,
                "allowed_updates": json.dumps(["message"])})
        except Exception as exc:
            log.warning("telegram poll failed: %s", exc)
            return 0
        if not resp.get("ok", False):
            log.warning("telegram poll not ok: %s", resp.get("description"))
            return 0
        n = 0
        for update in resp.get("result", []):
            uid = update.get("update_id")
            if isinstance(uid, int):
                self._offset = uid + 1
            msg = update.get("message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            text = msg.get("text") or ""
            if chat_id != self._notifier.chat_id:
                self.ignored_foreign += 1
                continue
            if not text.startswith("/"):
                continue
            self._notifier.send(self.dispatch(text))
            self.handled += 1
            n += 1
        return n


def notifier_from_env(bot_token_env: str, chat_id_env: str,
                      environ: Optional[Mapping[str, str]] = None
                      ) -> Optional[TelegramNotifier]:
    """Build a notifier from the named environment variables, or None (with
    a log line naming the *variable*, never its value) if either is unset."""
    env = os.environ if environ is None else environ
    token = env.get(bot_token_env, "").strip()
    chat = env.get(chat_id_env, "").strip()
    missing = [n for n, v in ((bot_token_env, token), (chat_id_env, chat))
               if not v]
    if missing:
        log.warning("notifications enabled but %s not set — alerts disabled",
                    ", ".join(missing))
        return None
    return TelegramNotifier(chat, UrllibTransport(token))
