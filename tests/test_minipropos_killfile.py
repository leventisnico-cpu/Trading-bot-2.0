"""Tests for the persistent kill-switch marker (pure, CI-safe)."""

from __future__ import annotations

import json

import pytest

from mini_prop_os.core.killfile import (clear_kill_marker, read_kill_marker,
                                        write_kill_marker)


def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "state" / "kill_switch.json"
    write_kill_marker(p, "daily loss 1500.00 breached limit 1000.00")
    marker = read_kill_marker(p)
    assert marker is not None
    assert "daily loss" in marker["reason"]
    assert "tripped_at" in marker


def test_read_missing_returns_none(tmp_path):
    assert read_kill_marker(tmp_path / "absent.json") is None


def test_unreadable_marker_still_blocks(tmp_path):
    p = tmp_path / "kill_switch.json"
    p.write_text("{not json")
    marker = read_kill_marker(p)
    assert marker is not None  # corruption is a reason to halt, not proceed
    assert "unreadable" in marker["reason"]


def test_non_dict_marker_still_blocks(tmp_path):
    p = tmp_path / "kill_switch.json"
    p.write_text(json.dumps(["surprise"]))
    marker = read_kill_marker(p)
    assert marker is not None and "malformed" in marker["reason"]


def test_clear_requires_operator_and_removes(tmp_path):
    p = tmp_path / "kill_switch.json"
    write_kill_marker(p, "x")
    with pytest.raises(ValueError):
        clear_kill_marker(p, "")
    assert clear_kill_marker(p, "nico") is True
    assert read_kill_marker(p) is None
    assert clear_kill_marker(p, "nico") is False  # idempotent
