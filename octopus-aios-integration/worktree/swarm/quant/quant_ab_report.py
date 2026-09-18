#!/usr/bin/env python3
"""Weekly A/B report for the Directional-v2 paper experiment.

Compares the owner paper portfolios:
  main    (multi_exchange_portfolios_owner_paper.json,         trail=1.0)
  control (multi_exchange_portfolios_owner_paper_control.json, trail=0.988)

Read-only. Writes data/reports/quant_ab_report.json and, with --notify,
sends a short digest to the owner's Telegram.

Usage:
    python scripts/quant_ab_report.py [--notify]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))

MAIN = DATA / "multi_exchange_portfolios_owner_paper.json"
CONTROL = DATA / "multi_exchange_portfolios_owner_paper_control.json"
OUT = DATA / "reports" / "quant_ab_report.json"


def load_trade_pnls(data: dict) -> list[float]:
    """Per-trade net PnL from persisted trade_logs (across exchanges)."""

    pnls: list[float] = []
    for key, value in data.items():
        if key.startswith("_") or key == "cross_arbitrage":
            continue
        for t in (value or {}).get("trade_log") or []:
            raw = t.get("net_pnl_usd")
            if raw is None:
                continue  # отсутствующий PnL не считаем наблюдением
            try:
                pnls.append(float(raw))
            except (TypeError, ValueError):
                continue
    return pnls


def ab_verdict(
    main_pnls: list[float],
    control_pnls: list[float],
    *,
    min_trades: int = 15,
    n_boot: int = 2000,
    seed: int = 42,
) -> dict | None:
    """Bootstrap comparison of per-trade PnL; None until both arms have data.

    Returns None when not enough trades; otherwise dict with means, observed
    difference, 90% CI and a significance flag (CI excludes zero).
    """

    if len(main_pnls) < min_trades or len(control_pnls) < min_trades:
        return None
    import numpy as np

    rng = np.random.default_rng(seed)
    main = np.asarray(main_pnls, dtype=float)
    control = np.asarray(control_pnls, dtype=float)
    obs = float(main.mean() - control.mean())
    boots = []
    for _ in range(n_boot):
        sm = rng.choice(main, size=len(main), replace=True)
        sc = rng.choice(control, size=len(control), replace=True)
        boots.append(float(sm.mean() - sc.mean()))
    boots = np.asarray(boots)
    lo, hi = float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))
    return {
        "n_main": len(main),
        "n_control": len(control),
        "main_mean": round(float(main.mean()), 4),
        "control_mean": round(float(control.mean()), 4),
        "diff_obs": round(obs, 4),
        "ci90": [round(lo, 4), round(hi, 4)],
        "significant": bool(lo > 0 or hi < 0),
        "winner": "main" if obs > 0 else ("control" if obs < 0 else "tie"),
    }


def required_trades_for_power(
    effect_usd: float, sd_usd: float, *, power: float = 0.80, alpha: float = 0.10
) -> int:
    """Trades per arm needed to detect `effect_usd` with given power
    (two-sided t-test approximation, pooled sd)."""

    import math
    from statistics import NormalDist

    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    n = math.ceil(2 * (sd_usd / effect_usd) ** 2 * (z_alpha + z_beta) ** 2)
    return max(n, 2)


def basket_benchmark(path: Path) -> dict | None:
    """Latest basket-paper row as the passive benchmark (None when absent)."""

    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        last = json.loads(lines[-1])
        return {
            "value_usd": float(last.get("value_usd", 0.0)),
            "pnl_pct": float(last.get("pnl_pct", 0.0)),
            "fees_paid_usd": float(last.get("fees_paid_usd", 0.0)),
        }
    except (OSError, ValueError, TypeError):
        return None


def _portfolio_stats(data: dict) -> dict:
    """Aggregate paper metrics across exchange portfolios."""

    exchanges = [
        v for k, v in data.items() if k not in {"cross_arbitrage", "_risk_state"}
    ]
    closed = sum(int(v.get("closed_trades", 0) or 0) for v in exchanges)
    wins = sum(int(v.get("winning_trades", 0) or 0) for v in exchanges)
    realized = sum(float(v.get("realized_pnl_usd", 0.0) or 0.0) for v in exchanges)
    gross = sum(float(v.get("gross_pnl_usd", 0.0) or 0.0) for v in exchanges)
    fees = sum(float(v.get("fees_paid_usd", 0.0) or 0.0) for v in exchanges)
    exec_costs = sum(float(v.get("execution_costs_usd", 0.0) or 0.0) for v in exchanges)
    net_profit = sum(float(v.get("net_profit_usd", 0.0) or 0.0) for v in exchanges)
    net_loss = sum(float(v.get("net_loss_usd", 0.0) or 0.0) for v in exchanges)
    risk = data.get("_risk_state") or {}
    return {
        "closed_trades": closed,
        "winning_trades": wins,
        "win_rate_pct": round(100.0 * wins / closed, 1) if closed else None,
        "realized_pnl_usd": round(realized, 4),
        "gross_pnl_usd": round(gross, 4),
        "fees_usd": round(fees, 4),
        "execution_costs_usd": round(exec_costs, 4),
        "profit_factor": round(net_profit / net_loss, 3) if net_loss > 0 else None,
        "equity_usd": round(float(risk.get("equity_usd", 0.0) or 0.0), 2),
        "max_drawdown_pct_seen": round(
            float(risk.get("max_drawdown_pct_seen", 0.0) or 0.0), 4
        ),
        "entry_mode": risk.get("entry_mode"),
    }


def compare_portfolios(main: dict, control: dict) -> dict:
    """Pure A/B comparison (unit-tested)."""

    return {"main": _portfolio_stats(main), "control": _portfolio_stats(control)}


def _env(key: str) -> str:
    if key in ("AIOS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"):
        from swarm.tgbot.credentials import secret_from_env_or_credential

        value = secret_from_env_or_credential(
            "AIOS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", credential="telegram_token"
        )
        if value:
            return value
    if key in ("TELEGRAM_CHAT_ID", "AIOS_OWNER_CHAT_ID"):
        from swarm.tgbot.credentials import read_systemd_credential

        value = read_systemd_credential("telegram_owner_chat_id")
        if value:
            return value
    v = os.environ.get(key, "")
    if v:
        return v
    env_file = Path(os.environ.get("OCTOPUS_ENV_FILE", "/opt/octopus/.env"))
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _tg(text: str) -> bool:
    token = _env("TELEGRAM_BOT_TOKEN") or _env("AIOS_TELEGRAM_TOKEN")
    chat = _env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("⚠️ telegram credentials not found; skip notify")
        return False
    payload = {
        "chat_id": int(chat),
        "text": html.escape(text)[:3900],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60):
            return True
    except Exception:
        return False


def _fmt_side(name: str, s: dict) -> str:
    lines = [f"{name}:"]
    lines.append(
        f"  сделки: {s['closed_trades']} (win {s['win_rate_pct']}%)"
        if s["win_rate_pct"] is not None
        else f"  сделки: {s['closed_trades']}"
    )
    lines.append(
        f"  realized PnL: {s['realized_pnl_usd']:+.4f} USD | gross {s['gross_pnl_usd']:+.4f} | fees {s['fees_usd']:.4f}"
    )
    lines.append(
        f"  exec costs: {s['execution_costs_usd']:.4f} | PF: {s['profit_factor']} | equity: {s['equity_usd']}"
    )
    lines.append(
        f"  max DD seen: {s['max_drawdown_pct_seen']:.3f}% | mode: {s['entry_mode']}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notify", action="store_true", help="send the digest to Telegram"
    )
    args = parser.parse_args()

    if not MAIN.exists() or not CONTROL.exists():
        print("SKIP: portfolio files missing")
        return 0
    main_data = json.loads(MAIN.read_text(encoding="utf-8"))
    control_data = json.loads(CONTROL.read_text(encoding="utf-8"))
    verdict = ab_verdict(load_trade_pnls(main_data), load_trade_pnls(control_data))
    basket = basket_benchmark(DATA / "reports" / "basket_paper.jsonl")
    power = {
        "effect_0.1usd": required_trades_for_power(0.1, 2.0),
        "effect_0.2usd": required_trades_for_power(0.2, 2.0),
        "effect_0.3usd": required_trades_for_power(0.3, 2.0),
    }
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comparison": compare_portfolios(main_data, control_data),
        "ab_verdict": verdict,
        "basket_benchmark": basket,
        "power_required_trades": power,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    c = report["comparison"]
    text = (
        "📊 <b>Directional v2 A/B paper</b> (main trail=1.0 vs control 0.988)\n"
        + _fmt_side("🅰️ main", c["main"])
        + "\n"
        + _fmt_side("🅱️ control", c["control"])
    )
    if verdict:
        sig = "✅ значимо" if verdict["significant"] else "≈ незначимо"
        text += (
            f"\n🔬 <b>A/B вердикт готов</b> (n={verdict['n_main']}/{verdict['n_control']}):\n"
            f"main {verdict['main_mean']:+.3f}$/сд. vs control {verdict['control_mean']:+.3f}$/сд.\n"
            f"diff {verdict['diff_obs']:+.3f} | CI90 [{verdict['ci90'][0]:+.3f}, {verdict['ci90'][1]:+.3f}] | {sig}"
        )
    else:
        text += (
            "\n🔬 A/B вердикт ещё не готов (нужно ≥15 закрытых сделок в каждом контуре; "
            f"для 80% мощности: {power['effect_0.2usd']} сделок/контур при эффекте 0.2$/сд.)"
        )
    if basket:
        text += (
            f"\n🧺 Бенчмарк корзина топ-10: {basket['pnl_pct']:+.2f}% "
            f"(value ${basket['value_usd']:.2f}, fees ${basket['fees_paid_usd']:.2f})"
        )
    text += "\nПолные данные: data/reports/quant_ab_report.json"
    print(text.replace("<b>", "").replace("</b>", ""))
    if args.notify:
        print("notified:", _tg(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
