"""Tests for config.yaml loading/validation (skipped if PyYAML is absent)."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from mini_prop_os.core.config import AppConfig, ConfigError, load_config

REPO = Path(__file__).resolve().parents[1]
SHIPPED = REPO / "mini_prop_os" / "config.yaml"


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_shipped_config_loads_and_defaults_to_paper_port():
    cfg = load_config(SHIPPED)
    assert isinstance(cfg, AppConfig)
    assert cfg.connection.port in (7497, 4002), \
        "shipped config must point at a PAPER port"
    assert cfg.contract.symbol == "SPY"
    assert cfg.strategy.fast_period < cfg.strategy.slow_period


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/config.yaml")


def test_empty_file_yields_all_defaults(tmp_path):
    cfg = load_config(write(tmp_path, ""))
    assert cfg.connection.port == 7497  # paper by default
    assert cfg.risk.allow_short is False


def test_unknown_top_level_key_rejected(tmp_path):
    with pytest.raises(ConfigError, match="unknown top-level"):
        load_config(write(tmp_path, "connektion: {}\n"))


def test_unknown_section_key_rejected(tmp_path):
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(write(tmp_path, "risk:\n  max_daily_losss: 5\n"))


def test_invalid_values_rejected(tmp_path):
    with pytest.raises(ConfigError, match="fast_period"):
        load_config(write(
            tmp_path, "strategy:\n  fast_period: 30\n  slow_period: 10\n"))
    with pytest.raises(ConfigError, match="max_daily_loss_pct"):
        load_config(write(tmp_path, "risk:\n  max_daily_loss_pct: 1.5\n"))
    with pytest.raises(ConfigError, match="port"):
        load_config(write(tmp_path, "connection:\n  port: 0\n"))


def test_malformed_yaml_rejected(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "risk: [unclosed\n"))
