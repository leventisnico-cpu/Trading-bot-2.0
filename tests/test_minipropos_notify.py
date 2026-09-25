"""Telegram notifier + read-only console (fake transport, no network)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping

import pytest

from mini_prop_os.notify import (TelegramConsole, TelegramNotifier,
                                 notifier_from_env)
from mini_prop_os.notify.telegram import MAX_MESSAGE_CHARS


class FakeTransport:
    def __init__(self, updates: List[Dict[str, Any]] | None = None,
                 fail: bool = False) -> None:
        self.calls: List[tuple[str, Dict[str, Any]]] = []
        self.updates = updates or []
        self.fail = fail

    def post(self, method: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        self.calls.append((method, dict(payload)))
        if self.fail:
            raise RuntimeError("network down")
        if method == "getUpdates":
            pending, self.updates = self.updates, []
            return {"ok": True, "result": pending}
        return {"ok": True, "result": {}}

    def sent(self) -> List[str]:
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def update(uid: int, chat: str, text: str) -> Dict[str, Any]:
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_send_posts_to_configured_chat():
    t = FakeTransport()
    n = TelegramNotifier("42", t)
    assert n.send("hello") is True
    assert t.calls[0][0] == "sendMessage"
    assert t.calls[0][1]["chat_id"] == "42"
    assert t.calls[0][1]["text"] == "hello"
    assert n.sent == 1 and n.failed == 0


def test_send_never_raises_on_transport_failure(caplog):
    n = TelegramNotifier("42", FakeTransport(fail=True))
    with caplog.at_level(logging.WARNING):
        assert n.send("x") is False
    assert n.failed == 1
    assert "telegram send failed" in caplog.text


def test_send_truncates_oversized_messages():
    t = FakeTransport()
    TelegramNotifier("42", t).send("x" * 10_000)
    assert len(t.sent()[0]) <= MAX_MESSAGE_CHARS


def test_empty_chat_id_rejected():
    with pytest.raises(ValueError):
        TelegramNotifier("", FakeTransport())


def test_console_answers_status_from_own_chat_only():
    t = FakeTransport(updates=[
        update(1, "42", "/status"),
        update(2, "999", "/status"),        # foreign chat: ignored
        update(3, "42", "just chatting"),   # not a command: ignored
    ])
    n = TelegramNotifier("42", t)
    c = TelegramConsole(n, t, handlers={"/status": lambda: "all good"})
    assert c.poll_once() == 1
    assert t.sent() == ["all good"]
    assert c.ignored_foreign == 1
    assert c.handled == 1


def test_console_advances_offset_so_updates_are_not_replayed():
    t = FakeTransport(updates=[update(7, "42", "/status")])
    n = TelegramNotifier("42", t)
    c = TelegramConsole(n, t, handlers={"/status": lambda: "ok"})
    c.poll_once()
    c.poll_once()
    polls = [p for m, p in t.calls if m == "getUpdates"]
    assert polls[0]["offset"] is None
    assert polls[1]["offset"] == 8
    assert t.sent() == ["ok"]


def test_unknown_command_and_botname_suffix_get_help():
    t = FakeTransport()
    c = TelegramConsole(TelegramNotifier("42", t), t,
                        handlers={"/status": lambda: "ok"})
    assert "/status" in c.dispatch("/help")
    assert "/status" in c.dispatch("/flatten")     # no such command
    assert c.dispatch("/status@my_bot") == "ok"


def test_console_has_no_trading_commands():
    """The phone console is read-only by design."""
    t = FakeTransport()
    c = TelegramConsole(TelegramNotifier("42", t), t,
                        handlers={"/status": lambda: "ok"})
    for cmd in ("/buy", "/sell", "/flatten", "/kill", "/reset"):
        assert c.dispatch(cmd) == c.help_text()


def test_handler_exception_is_contained():
    def boom() -> str:
        raise KeyError("x")
    t = FakeTransport()
    c = TelegramConsole(TelegramNotifier("42", t), t, handlers={"/status": boom})
    assert "failed" in c.dispatch("/status")


def test_poll_failure_is_swallowed():
    t = FakeTransport(fail=True)
    c = TelegramConsole(TelegramNotifier("42", t), t)
    assert c.poll_once() == 0


def test_notifier_from_env_requires_both_vars(caplog):
    with caplog.at_level(logging.WARNING):
        assert notifier_from_env("TOK", "CHAT", environ={"TOK": "1:a"}) is None
    assert "CHAT" in caplog.text
    assert "1:a" not in caplog.text  # the value is never logged
    n = notifier_from_env("TOK", "CHAT", environ={"TOK": "1:a", "CHAT": "42"})
    assert n is not None and n.chat_id == "42"
