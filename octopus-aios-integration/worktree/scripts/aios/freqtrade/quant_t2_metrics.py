# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy (not in prod venv); runs on ML hosts
#!/usr/bin/env python3
"""Честные метрики T2-симуляции (ревизия 2026-08-19, рекомендации).

Считает по state-файлам ног и портфельной истории: profit factor, win rate,
expectancy (на сделку), Sharpe/Sortino/MaxDD/Calmar (по дневной портфельной
истории). ВАЖНО: это метрики ИСТОРИЧЕСКОЙ СИМУЛЯЦИИ с октября 2023 (не
заработок); живой daily-цикл стартовал 16-18.08 и покрыт отдельно.

Usage: python scripts/quant_t2_metrics.py [--out data/reports/t2_simulation_metrics.md]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LEGS = (
    ("BTC", "t2_paper_state_btcusd.json"),
    ("ETH", "t2_paper_state_ethusd.json"),
    ("SOL", "t2_paper_state_solusd.json"),
    ("BNB", "t2_paper_state_bnbusd.json"),
    ("NEAR", "t2_paper_state_nearusd.json"),
)
PORT = REPO_ROOT / "data" / "t2_portfolio_equity.jsonl"


def trade_metrics(trades: list[dict], final_equity: float) -> dict | None:
    """Метрики по последовательности сделок (equity в каждом trade)."""

    if not trades:
        return None
    eq = [float(t.get("equity", 0.0) or 0.0) for t in trades]
    eq.append(final_equity)
    pnls = [b - a for a, b in zip(eq, eq[1:], strict=False)]  # noqa: RUF007
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else float("inf")
    return {
        "n_trades": len(pnls),
        "win_rate_pct": round(100 * len(wins) / len(pnls), 1),
        "profit_factor": round(pf, 2) if math.isfinite(pf) else None,
        "expectancy_usd": round(float(np.mean(pnls)), 2),
        "total_from_10k_pct": round((final_equity / 10000 - 1) * 100, 1),
    }


def portfolio_metrics(rows: list[dict]) -> dict | None:
    """Sharpe/Sortino/MaxDD/Calmar по дневной портфельной истории."""

    eq = np.array([float(r.get("portfolio", 0.0) or 0.0) for r in rows])
    if len(eq) < 10:
        return None
    rets = np.diff(eq) / eq[:-1]
    mean, std = float(rets.mean()), float(rets.std())
    sharpe = mean / std * math.sqrt(365) if std > 0 else 0.0
    downside = rets[rets < 0]
    sortino = (
        mean / float(downside.std()) * math.sqrt(365)
        if len(downside) > 1 and float(downside.std()) > 0
        else float("nan")
    )
    dd = float((eq / np.maximum.accumulate(eq) - 1).min()) * 100
    days = len(rows)
    total = float(eq[-1] / eq[0] - 1) * 100
    cagr = ((eq[-1] / eq[0]) ** (365.25 / days) - 1) * 100 if eq[0] > 0 else 0.0
    calmar = cagr / abs(dd) if dd < 0 else float("nan")
    return {
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2) if sortino == sortino else None,
        "max_dd_pct": round(dd, 1),
        "cagr_pct": round(cagr, 1),
        "calmar": round(calmar, 2) if calmar == calmar else None,
        "total_pct": round(total, 1),
        "n_days": days,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "reports" / "t2_simulation_metrics.md")
    args = ap.parse_args()

    lines = [
        "# Метрики T2-симуляции (честная оценка)",
        "",
        "⚠️ Это метрики ИСТОРИЧЕСКОЙ СИМУЛЯЦИИ с октября 2023 (виртуальные $10,000),",
        "а не заработок. Живой daily-цикл стартовал 16-18.08.2026; свежая OOS-проверка",
        "правила отрицательна (SMA50-BTC: −16.7% на последних 30% окна, последний месяц",
        "−4.1%). Высокие значения = подгонка под прошлое + survivorship + идеальное",
        "исполнение.",
        "",
        "| Нога | Сделок | Win% | PF | Expectancy $ | Итог от $10k |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tag, fname in LEGS:
        try:
            st = json.loads((REPO_ROOT / "data" / fname).read_text(encoding="utf-8"))
        except Exception:
            continue
        m = trade_metrics(st.get("trades") or [], float(st.get("equity", 0.0) or 0.0))
        if m:
            pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "∞"
            lines.append(
                f"| {tag} | {m['n_trades']} | {m['win_rate_pct']} | {pf} "
                f"| {m['expectancy_usd']:+.2f} | {m['total_from_10k_pct']:+.1f}% |"
            )
    rows = []
    if PORT.exists():
        rows = [json.loads(ln) for ln in PORT.read_text(encoding="utf-8").splitlines() if ln]
    pm = portfolio_metrics(rows)
    if pm:
        lines += [
            "",
            "| Портфель (5 ног) | Sharpe | Sortino | MaxDD | CAGR | Calmar | Итог |",
            "|---|---:|---:|---:|---:|---:|---:|",
            f"| значение | {pm['sharpe']} | {pm['sortino']} | {pm['max_dd_pct']}% | "
            f"{pm['cagr_pct']}% | {pm['calmar']} | {pm['total_pct']}% |",
        ]
    lines += [
        "",
        "Вывод: метрики описывают СИМУЛЯЦИЮ и не являются доказательством ",
        "прибыльности. Решение о доверии правилу — только по живому daily-циклу ",
        "и честному OOS.",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
