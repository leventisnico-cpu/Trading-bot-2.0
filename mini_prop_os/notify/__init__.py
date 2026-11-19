"""Operator notifications: Telegram alerts and a read-only command console.

Pure stdlib (``urllib``) so it runs wherever the bot runs; nothing here
imports the broker library, and the transport is injectable for tests.
"""

from .telegram import (TelegramConsole, TelegramNotifier, TelegramTransport,
                       UrllibTransport, notifier_from_env)

__all__ = ["TelegramConsole", "TelegramNotifier", "TelegramTransport",
           "UrllibTransport", "notifier_from_env"]
