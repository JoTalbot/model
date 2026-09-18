"""Wave 4 port-safety contract for swarm.quant (item 1).

- Kraken client carries NO secrets and refuses live orders by default
- engine chain constructs offline on tmp dirs (no web3/numpy needed)
- OCTOPUS_ env/config resolution works; stdlib quantiles are exact
"""

import json

import pytest

from swarm.quant.kraken_client import AIOSKrakenClient
from swarm.quant.ml_gate_calibration import (
    calibrated_ml_threshold,
    compute_quantiles,
    threshold_is_sane,
)
from swarm.quant.paths import resolve_data_dir
from swarm.quant.quant_directional_policy import DirectionalV2Config
from swarm.quant.quant_trading_engine import (
    MultiExchangeQuantEngine,
    PaperTradingSimulator,
)
from swarm.quant.regime_guard import crash_kill_active


def _offline(monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("network access in offline test")

    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket, "socket", _boom)


def test_kraken_no_hardcoded_secrets(monkeypatch):
    monkeypatch.delenv("OCTOPUS_KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("OCTOPUS_KRAKEN_API_SECRET", raising=False)
    client = AIOSKrakenClient(data_dir="/tmp")
    assert client.api_key == "" and client.api_secret == ""


def test_kraken_live_orders_blocked_by_default(monkeypatch):
    monkeypatch.delenv("OCTOPUS_KRAKEN_LIVE", raising=False)
    client = AIOSKrakenClient(data_dir="/tmp")
    called = []
    monkeypatch.setattr(client, "_query", lambda *a, **k: called.append((a, k)))
    res = client.add_market_order("XXBTZUSD", "buy", 0.001)
    assert res["status"] == "error" and called == []


def test_kraken_live_orders_opt_in(monkeypatch):
    monkeypatch.setenv("OCTOPUS_KRAKEN_LIVE", "1")
    client = AIOSKrakenClient(data_dir="/tmp")
    called = []
    monkeypatch.setattr(
        client, "_query", lambda *a, **k: (called.append((a, k)), {"error": []})[1]
    )
    client.add_market_order("XXBTZUSD", "buy", 0.001)
    assert called and called[0][0][:2] == ("private", "AddOrder")


def test_kraken_query_does_not_mutate_caller_dict(monkeypatch):
    client = AIOSKrakenClient(data_dir="/tmp")
    monkeypatch.setattr(client, "_get_signature", lambda *a: "sig")
    import urllib.request

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"error": [], "result": {}}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    params = {"pair": "XXBTZUSD"}
    client._query("private", "Balance", params)
    assert params == {"pair": "XXBTZUSD"}


def test_resolve_data_dir(monkeypatch, tmp_path):
    assert resolve_data_dir(str(tmp_path)) == tmp_path
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))
    assert resolve_data_dir(None) == tmp_path
    monkeypatch.delenv("OCTOPUS_DATA_DIR")
    assert str(resolve_data_dir(None)) == "/var/lib/octopus"


def test_engine_constructs_offline(monkeypatch, tmp_path):
    _offline(monkeypatch)
    engine = MultiExchangeQuantEngine(data_dir=str(tmp_path))
    assert engine.portfolio_file.parent == tmp_path
    assert (tmp_path / "multi_exchange_portfolios.json").exists()
    sim = PaperTradingSimulator(data_dir=str(tmp_path))
    assert (tmp_path / ".wallet_vault.json").exists()
    res = sim.execute_paper_signal(
        {"symbol": "BTC", "current_price": 100.0, "signal": "BUY_LONG"}
    )
    assert isinstance(res, dict)


def test_policy_from_env_octopus_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OCTOPUS_QUANT_ENTRY_MODE", "enabled")
    monkeypatch.setenv("OCTOPUS_QUANT_MAX_GLOBAL_POSITIONS", "1")
    config = DirectionalV2Config.from_env()
    assert config.entry_mode == "enabled"
    assert config.max_global_positions == 1
    assert config.ml_calibrate_file == str(
        tmp_path / "quant" / "ml_prob_calibration.json"
    )
    assert config.regime_file == str(tmp_path / "reports" / "market_regime_latest.json")


def test_compute_quantiles_known_values():
    assert compute_quantiles([])["q90"] == 0.5
    assert compute_quantiles([0.7])["q50"] == 0.7
    got = compute_quantiles([0.1, 0.2, 0.3, 0.4, 0.5])
    assert got == {"q50": 0.3, "q75": 0.4, "q90": 0.46, "q95": 0.48, "q99": 0.496}


def test_calibration_threshold_helpers(tmp_path):
    assert calibrated_ml_threshold(str(tmp_path / "nope.json")) is None
    (tmp_path / "cal.json").write_text(json.dumps({"threshold_q90": 0.66}))
    assert calibrated_ml_threshold(str(tmp_path / "cal.json")) == pytest.approx(0.66)
    assert threshold_is_sane(0.66) is True
    assert threshold_is_sane(0.95) is False


def test_regime_guard_fail_open(tmp_path):
    assert crash_kill_active(str(tmp_path / "nope.json")) is False
    (tmp_path / "reg.json").write_text(json.dumps({"regime": "CRASH"}))
    assert crash_kill_active(str(tmp_path / "reg.json")) is True
    (tmp_path / "reg.json").write_text(json.dumps({"regime": "RISK_ON"}))
    assert crash_kill_active(str(tmp_path / "reg.json")) is False


def test_wallet_evm_guards_without_web3(tmp_path):
    from swarm.quant import crypto_wallet as wallet_mod

    if wallet_mod.Web3 is not None:
        pytest.skip("web3 installed: guards not exercised")
    wallet = wallet_mod.AIOSWalletManager(data_dir=str(tmp_path))
    assert "error" in wallet.check_evm_balance()
    assert "error" in wallet.check_erc20_balance()
    assert wallet.send_evm_tokens()["status"] == "error"
