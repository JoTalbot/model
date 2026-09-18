"""Tests for the new Telegram quant commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarm.tgbot.quant_cmds import cmd_basket, cmd_scoreboard


def test_cmd_basket_renders(tmp_path, monkeypatch):
    import swarm.tgbot.quant_cmds as mod

    monkeypatch.setattr(mod, "DATA", Path(tmp_path))
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "reports" / "basket_paper_state.json").write_text(
        json.dumps({"weights_rule": "inverse_vol_30d", "cash_usd": 0.0})
    )
    (tmp_path / "reports" / "basket_paper.jsonl").write_text(
        json.dumps(
            {
                "day": "2026-08-18",
                "value_usd": 999.0,
                "pnl_pct": -0.1,
                "invested_usd": 1000.0,
                "fees_paid_usd": 1.0,
            }
        )
        + "\n"
    )
    out = cmd_basket()
    assert "$999.00" in out and "-0.10%" in out and "inverse_vol_30d" in out


def test_cmd_basket_missing_data_graceful(tmp_path, monkeypatch):
    import swarm.tgbot.quant_cmds as mod

    monkeypatch.setattr(mod, "DATA", Path(tmp_path))
    (tmp_path / "reports").mkdir(parents=True)
    out = cmd_basket()
    assert "данных нет" in out or "ошибка" in out


def test_cmd_scoreboard_renders_winner(tmp_path, monkeypatch):
    import swarm.tgbot.quant_cmds as mod

    monkeypatch.setattr(mod, "DATA", Path(tmp_path))
    (tmp_path / "reports").mkdir(parents=True)
    row = {
        "date": "2026-08",
        "dv2": {"pnl_pct": -0.38, "trades": 9},
        "market_mean_pct": -7.35,
        "top10_basket_pct": 2.51,
        "verdict": {"winner": "top10_basket", "best_momentum": None},
    }
    (tmp_path / "reports" / "strategy_scoreboard.jsonl").write_text(
        json.dumps(row) + "\n"
    )
    out = cmd_scoreboard()
    assert "top10_basket" in out and "2026-08" in out
    assert "DV2 -0.38%" in out


def test_cmd_scoreboard_unstable_flag(tmp_path, monkeypatch):
    import swarm.tgbot.quant_cmds as mod

    monkeypatch.setattr(mod, "DATA", Path(tmp_path))
    (tmp_path / "reports").mkdir(parents=True)
    row = {
        "date": "2026-08",
        "dv2": {"pnl_pct": -0.38, "trades": 9},
        "market_mean_pct": -7.35,
        "top10_basket_pct": 2.51,
        "verdict": {"winner": "M2", "unstable": True},
    }
    (tmp_path / "reports" / "strategy_scoreboard.jsonl").write_text(
        json.dumps(row) + "\n"
    )
    out = cmd_scoreboard()
    assert "M2 ⚠️" in out


def test_cmd_scoreboard_empty(tmp_path, monkeypatch):
    import swarm.tgbot.quant_cmds as mod

    monkeypatch.setattr(mod, "DATA", Path(tmp_path))
    (tmp_path / "reports").mkdir(parents=True)
    out = cmd_scoreboard()
    assert "данных нет" in out
