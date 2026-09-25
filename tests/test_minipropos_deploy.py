"""Deploy artifacts: paper-only ports, the TFSA config, and the Windows
setup script installing it (not the MES futures config)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from mini_prop_os.core.config import (LIVE_PORTS, PAPER_PORTS, ConfigError,
                                      NotificationsConfig, is_live_port,
                                      load_config)

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy"
TFSA = DEPLOY / "config.tfsa-paper.yaml"


def test_live_ports_include_gateway_alternate_4003():
    assert LIVE_PORTS == {7496, 4001, 4003}
    assert PAPER_PORTS == {7497, 4002}
    assert is_live_port(4003) and not is_live_port(4002)


def test_tfsa_paper_config_matches_the_order_sheet():
    cfg = load_config(TFSA)
    assert cfg.connection.port == 4002
    assert cfg.contract.symbol == "SPY"
    assert cfg.contract.sec_type == "STK"
    assert cfg.contract.exchange == "SMART"
    assert cfg.contract.currency == "USD"
    assert cfg.contract.multiplier == 1.0
    assert cfg.strategy.use_rth is True
    assert cfg.strategy.order_quantity == 10
    assert cfg.risk.max_position_shares == 50
    assert cfg.risk.max_order_quantity == 10
    # Notional caps sized for 10-share lots of a ~$700 ETF, not for MES.
    assert 10 * 700 <= cfg.risk.max_position_notional <= 50 * 1000
    assert cfg.risk.max_gross_notional <= 50 * 1000
    assert cfg.notifications.enabled is True


def test_every_deploy_config_is_paper_only():
    """A live port in any shipped config is a bug until live readiness
    is signed off."""
    for path in list(DEPLOY.glob("*.yaml")) + [
            REPO / "mini_prop_os" / "config.yaml"]:
        cfg = load_config(path)
        assert cfg.connection.port in PAPER_PORTS, f"{path} is not paper"
        assert not is_live_port(cfg.connection.port)


def test_deploy_configs_never_use_futures():
    """The TFSA-permissioned account cannot trade futures, ever."""
    for path in DEPLOY.glob("*.yaml"):
        cfg = load_config(path)
        assert cfg.contract.sec_type == "STK", f"{path} trades futures"


def test_setup_script_installs_tfsa_config_not_mes():
    text = (DEPLOY / "windows" / "setup.ps1").read_text()
    assert "config.tfsa-paper.yaml" in text
    assert re.search(r"state\\config\.yaml", text)
    # The MES reference config must not be what gets installed: the only
    # source assigned for the config copy is the TFSA paper file.
    sources = re.findall(r'\$source\s*=[^\n"]*"([^"]+)"', text)
    assert sources == [r"deploy\config.tfsa-paper.yaml"]
    code = "\n".join(l for l in text.splitlines()
                     if not l.lstrip().startswith("#"))
    assert not re.search(r"mini_prop_os\\config\.yaml", code)


def test_run_script_wires_preflight_flag():
    text = (DEPLOY / "windows" / "run.ps1").read_text()
    assert "--preflight" in text and "state\\config.yaml" in text


def test_secrets_are_gitignored_and_never_in_config():
    ignored = (REPO / ".gitignore").read_text().splitlines()
    for entry in (".env", "state/config.yaml", "state/kill_switch.json"):
        assert entry in ignored, f"{entry} must be git-ignored"
    text = TFSA.read_text()
    assert not re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", text)  # no bot token
    env_example = (DEPLOY / ".env.example").read_text()
    for line in env_example.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            assert k == "TRADING_MODE" or v == "", f"{k} must be blank"
    assert "TRADING_MODE=paper" in env_example


def test_notifications_config_refuses_credential_values():
    NotificationsConfig(bot_token_env="MY_TOKEN_VAR")
    with pytest.raises(ConfigError, match="NAME"):
        NotificationsConfig(bot_token_env="123456:ABCdefGHI")
    with pytest.raises(ConfigError, match="NAME"):
        NotificationsConfig(chat_id_env="-100123456")
    with pytest.raises(ConfigError, match="provider"):
        NotificationsConfig(provider="slack")
    with pytest.raises(ConfigError, match="poll_interval"):
        NotificationsConfig(poll_interval_s=0)
