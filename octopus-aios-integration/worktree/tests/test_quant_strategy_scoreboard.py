"""Tests for the strategy scoreboard pure helpers."""

from __future__ import annotations

from scripts.aios.research.quant_strategy_scoreboard import (
    parse_momentum_md,
    rebuild_md,
    top_basket_pnl,
    verdict,
)

MD_SAMPLE = """| Вариант | PnL % | CAGR % | MaxDD % | Sharpe | Сделок | OOS CAGR % | last30d PnL% | last30d DD% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T1: TS-момент BTC (SMA200) | -12.1 | -6.2 | -20.6 | -0.26 | 18 | +0.0 | +0.0 | 0.0 |
| M2: CS-момент топ-5 (30д) | -46.9 | -27.1 | -64.4 | -0.46 | 137 | -46.0 | +1.9 | -5.9 |
"""


def test_parse_momentum_md():
    rows = parse_momentum_md(MD_SAMPLE)
    assert len(rows) == 2
    m2 = next(r for r in rows if r["name"] == "M2")
    assert m2["month_pnl_pct"] == 1.9
    assert m2["oos_cagr_pct"] == -46.0
    assert m2["n_trades"] == 137


def test_top_basket_pnl_equal_weight():
    bh = {"per_symbol_pct": {"BTC": 0.7, "ETH": 4.0, "SOL": 1.4, "XRP": -7.6,
                             "BNB": 7.6, "DOGE": -2.8, "TRX": 1.8, "TON": -5.0,
                             "ADA": 5.5, "LINK": 15.6, "BONK": -27.3}}
    pnl, n = top_basket_pnl(bh, ["BTC", "ETH", "SOL", "XRP", "BNB",
                                    "DOGE", "TRX", "TON", "ADA", "LINK"])
    expected = sum([0.7, 4.0, 1.4, -7.6, 7.6, -2.8, 1.8, -5.0, 5.5, 15.6]) / 10
    assert n == 10
    assert abs(pnl - expected) < 1e-9


def test_top_basket_pnl_missing_assets():
    # неполный срез (<min_present из 10) -> (None, n)
    pnl, n = top_basket_pnl({"per_symbol_pct": {"BTC": 1.0}}, ["BTC", "ETH"])
    assert pnl is None and n == 1
    pnl, n = top_basket_pnl({}, ["BTC"])
    assert pnl is None and n == 0


def test_top_basket_pnl_partial_but_representative():
    per = {s: 1.0 for s in ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "TRX", "ADA", "LINK"]}
    pnl, n = top_basket_pnl({"per_symbol_pct": per}, ["BTC", "ETH", "SOL", "XRP", "BNB",
                                                               "DOGE", "TRX", "TON", "ADA", "LINK"])
    assert n == 9 and abs(pnl - 1.0) < 1e-9


def test_verdict_momentum_without_positive_oos_is_unstable_winner():
    momentum = [{"name": "M2", "month_pnl_pct": 1.9, "oos_cagr_pct": -46.0,
                 "n_trades": 137}]
    v = verdict(-0.38, 1.43, momentum)
    # M2 лучший в месяце, но OOS<0 -> победитель с флагом unstable
    assert v["winner"] == "M2"
    assert v["unstable"] is True


def test_verdict_momentum_with_positive_oos_wins():
    momentum = [{"name": "M2", "month_pnl_pct": 5.0, "oos_cagr_pct": 3.0,
                 "n_trades": 10}]
    v = verdict(-0.38, 1.43, momentum)
    assert v["winner"] == "M2"


def test_verdict_dv2_wins_when_all_momentum_negative_month():
    momentum = [{"name": "T2", "month_pnl_pct": -4.1, "oos_cagr_pct": -16.7,
                 "n_trades": 48}]
    v = verdict(-0.38, -1.5, momentum)
    assert v["winner"] == "directional_v2"


def test_rebuild_md_writes_table(tmp_path):
    rows = [{
        "date": "2026-08",
        "dv2": {"pnl_pct": -0.378, "trades": 9},
        "top10_basket_pct": 1.43,
        "market_mean_pct": -7.59,
        "verdict": {"winner": "top10_basket", "best_momentum": None},
    }]
    md = tmp_path / "score.md"
    rebuild_md(rows, md)
    text = md.read_text(encoding="utf-8")
    assert "| 2026-08 |" in text
    assert "-0.38%" in text and "+1.43%" in text
    assert "top10_basket" in text
