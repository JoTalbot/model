"""Compatibility and purity tests for extracted quant report formatters."""

from __future__ import annotations

from pathlib import Path

import swarm.quant.quant_report_formatters as formatters
import swarm.quant.quant_trading_engine as engine

NAMES = (
    "format_kraken_demo_report",
    "format_unified_crypto_earnings_report",
    "format_positions_only_report",
    "format_single_asset_analysis",
    "format_backtest_report",
    "format_portfolio_advice_report",
)


def test_legacy_module_reexports_exact_formatter_objects() -> None:
    for name in NAMES:
        assert getattr(engine, name) is getattr(formatters, name)


def test_formatters_accept_empty_snapshot_without_side_effects() -> None:
    outputs = {name: getattr(formatters, name)({}) for name in NAMES}

    assert all(isinstance(text, str) and text for text in outputs.values())
    assert outputs["format_kraken_demo_report"].startswith("🐙")
    assert outputs["format_unified_crypto_earnings_report"].startswith("🚀")
    assert outputs["format_positions_only_report"].startswith("💼")
    assert outputs["format_single_asset_analysis"].startswith("🔮")
    assert outputs["format_backtest_report"].startswith("🧪")
    assert outputs["format_portfolio_advice_report"].startswith("🧠")


def test_formatter_module_has_no_operational_imports() -> None:
    source = Path(formatters.__file__).read_text(encoding="utf-8")

    assert "requests" not in source
    assert "subprocess" not in source
    assert "AIOSWalletManager" not in source
