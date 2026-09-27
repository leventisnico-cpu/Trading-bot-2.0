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
    assert cfg.contract.sec_type == "FUT"
    assert cfg.contract.symbol == "MES"
    assert cfg.contract.multiplier == 5.0  # MES is $5/point
    assert cfg.strategy.use_rth is False   # futures trade nearly 24h
    assert cfg.strategy.fast_period < cfg.strategy.slow_period
    # One contract must fit within the per-order and position caps.
    assert cfg.strategy.order_quantity <= cfg.risk.max_order_quantity
    assert cfg.strategy.order_quantity <= cfg.risk.max_position_shares


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


def test_invalid_contract_values_rejected(tmp_path):
    with pytest.raises(ConfigError, match="sec_type"):
        load_config(write(tmp_path, "contract:\n  sec_type: OPT\n"))
    with pytest.raises(ConfigError, match="multiplier"):
        load_config(write(tmp_path, "contract:\n  multiplier: 0\n"))
    with pytest.raises(ConfigError, match="last_trade_date"):
        load_config(write(
            tmp_path, "contract:\n  last_trade_date: 'dec-2026'\n"))


def test_stock_contract_still_configurable(tmp_path):
    cfg = load_config(write(tmp_path, (
        "contract:\n  symbol: SPY\n  sec_type: STK\n  exchange: SMART\n"
        "  multiplier: 1.0\nstrategy:\n  use_rth: true\n")))
    assert cfg.contract.sec_type == "STK"
    assert cfg.contract.multiplier == 1.0
    assert cfg.strategy.use_rth is True


def test_malformed_yaml_rejected(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "risk: [unclosed\n"))
