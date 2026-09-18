#!/usr/bin/env python3
"""/quant command for the Telegram bot: status of all quant/portfolio services.

Reads runtime state files and service statuses; returns a compact HTML summary.
Kept OUTSIDE run_telegram_bot.py (protected) so the bot file needs only a thin
wrapper + dispatch branch.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def _fmt_num(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def cmd_quant() -> str:
    lines = ["📊 <b>Quant-контуры</b>", ""]

    # MM-сигналы: точность
    try:
        r = subprocess.run(
            [sys.executable, "scripts/aios/mm_signal_score.py"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
        out = [line for line in r.stdout.strip().split("\n") if line and "эмиссий" not in line]
        if out:
            lines.append("📡 <b>MM-сигналы:</b>")
            lines.extend(f"  {line}" for line in out)
        else:
            lines.append("📡 MM-сигналы: нет данных")
    except Exception as e:
        lines.append(f"📡 MM: ошибка ({e})")

    # ws-данные
    try:
        con = sqlite3.connect(str(DATA / "quant/orderbooks.sqlite"))
        n = con.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0]
        h = (
            con.execute("SELECT MAX(ts)-MIN(ts) FROM snapshots_ws").fetchone()[0] or 0
        ) / 3600
        nt = con.execute("SELECT COUNT(*) FROM trades_ws").fetchone()[0]
        con.close()
        lines.append(
            f"🌊 <b>ws-данные:</b> {_fmt_num(n)} снапшотов ({h:.1f} ч), "
            f"trade-flow {_fmt_num(nt)} записей"
        )
    except Exception as e:
        lines.append(f"🌊 ws: ошибка ({e})")

    # DCA
    try:
        s = json.loads((DATA / "dca_paper_state.json").read_text())
        vlog = [
            json.loads(line)
            for line in (DATA / "dca_paper_value.jsonl").read_text().splitlines()
            if line
        ]
        val = vlog[-1]["value_usd"] if vlog else 0.0
        dep = float(s.get("deposited_usd", 0))
        pnl = val - dep
        pct = pnl / dep * 100 if dep else 0
        lines.append(
            f"📈 <b>DCA:</b> ${dep:.0f} → ${val:.2f} ({pnl:+.2f}$ / {pct:+.1f}%)"
        )
    except Exception as e:
        lines.append(f"📈 DCA: ошибка ({e})")

    # A/B paper
    try:
        m = json.loads(
            (DATA / "multi_exchange_portfolios_owner_paper.json").read_text()
        )
        c = json.loads(
            (DATA / "multi_exchange_portfolios_owner_paper_control.json").read_text()
        )
        tm = sum(p.get("total_trades", 0) for p in m.values() if isinstance(p, dict))
        tc = sum(p.get("total_trades", 0) for p in c.values() if isinstance(p, dict))
        lines.append(
            f"⚖️ <b>A/B:</b> main (trail 1.0) {tm} | control (0.988) {tc} сделок"
        )
    except Exception as e:
        lines.append(f"⚖️ A/B: ошибка ({e})")

    # новостной сентимент
    try:
        import json as _j

        rows = [
            _j.loads(line)
            for line in (DATA / "quant" / "news_sentiment.jsonl").read_text().splitlines()
            if line
        ]
        if rows:
            pos = sum(1 for r in rows if r["sentiment"] > 0.2)
            neg = sum(1 for r in rows if r["sentiment"] < -0.2)
            last = rows[-1]
            avg = sum(r["sentiment"] for r in rows[-50:]) / max(1, len(rows[-50:]))
            lines.append(
                f"📰 <b>Сентимент:</b> {len(rows)} новостей (pos {pos} / neg {neg}), "
                f"avg(50) {avg:+.2f}, последняя {last['label']}"
            )
    except Exception:
        pass
    # Fear & Greed
    try:
        import json as _j

        ctx = _j.loads((DATA / "quant" / "market_context_latest.json").read_text())
        fng = ctx.get("fng", {})
        if fng.get("value") is not None:
            lines.append(f"😨 <b>Fear&Greed:</b> {fng['value']} ({fng['class']})")
    except Exception:
        pass
    # T2 momentum (BTC/ETH/SOL/BNB/NEAR)
    for tag, fname in (
        ("BTC", "t2_paper_state.json"),
        ("ETH", "t2_paper_state_ethusd.json"),
        ("SOL", "t2_paper_state_solusd.json"),
        ("BNB", "t2_paper_state_bnbusd.json"),
        ("NEAR", "t2_paper_state_nearusd.json"),
    ):
        try:
            import json as _j

            st = _j.loads((DATA / fname).read_text())
            eq = float(st.get("equity", 0))
            bh = float(st.get("cash_equiv", 0))
            pct = (eq / 10000 - 1) * 100 if eq else 0
            lines.append(
                f"📈 <b>T2-{tag} (SMA50):</b> {st.get('position')} | equity ${eq:,.0f} "
                f"({pct:+.1f}%) | BH ${bh:,.0f} | сделок {len(st.get('trades', []))}"
            )
        except Exception:
            pass
    # T2 portfolio
    try:
        import json as _j

        lines_p = [
            _j.loads(line)
            for line in (DATA / "t2_portfolio_equity.jsonl").read_text().splitlines()
            if line
        ]
        if lines_p:
            last = lines_p[-1]
            port = float(last["portfolio"])
            bh = float(last["bh"])
            pct = (port / 10000 - 1) * 100
            bh_pct = (bh / 10000 - 1) * 100
            lines.append(
                f"🧺 <b>T2-портфель (3 актива):</b> ${port:,.0f} ({pct:+.1f}%) | BH {bh_pct:+.1f}%"
            )
    except Exception:
        pass
    # funding/OI
    try:
        fdir = DATA / "quant/funding_oi"
        days = len(list(fdir.glob("daily_BTC.jsonl")))
        if days:
            lines.append(f"💧 <b>Funding/OI:</b> {days} дн истории")
    except Exception:
        pass

    # корзина топ-10 (vol-targeting)
    try:
        state = json.loads((DATA / "reports/basket_paper_state.json").read_text())
        hist = [
            json.loads(line)
            for line in (DATA / "reports/basket_paper.jsonl").read_text().splitlines()
            if line
        ]
        if hist:
            last = hist[-1]
            lines.append(
                f"🧺 <b>Корзина топ-10:</b> ${last['value_usd']:.2f} "
                f"({last['pnl_pct']:+.2f}%) | правило {state.get('weights_rule', 'eq')}"
            )
    except Exception:
        pass

    # scoreboard: последний вердикт
    try:
        hist = [
            json.loads(line)
            for line in (DATA / "reports/strategy_scoreboard.jsonl")
            .read_text()
            .splitlines()
            if line
        ]
        if hist:
            v = hist[-1].get("verdict") or {}
            w = v.get("winner", "—")
            if v.get("unstable"):
                w += " ⚠️"
            lines.append(f"🏆 <b>Scoreboard ({hist[-1]['date']}):</b> {w}")
    except Exception:
        pass

    # сервисы
    try:
        svc = subprocess.run(
            [
                "systemctl",
                "is-active",
                "aios-orderbook-ws.service",
                "aios-mm-signal-monitor.timer",
                "aios-mm-signal-emitter.timer",
                "aios-dca-paper.timer",
                "aios-funding-oi-daily.timer",
                "aios-quant-trading.service",
                "aios-quant-trading-control.service",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        st = svc.stdout.strip().split("\n")
        lines.append(f"🖥 <b>Сервисы:</b> {', '.join(st)}")
    except Exception as e:
        lines.append(f"🖥 сервисы: ошибка ({e})")

    return "\n".join(lines)


def cmd_basket() -> str:
    """Корзина топ-10 (vol-targeting): значение, PnL, веса."""

    try:
        state = json.loads((DATA / "reports/basket_paper_state.json").read_text())
        hist = [
            json.loads(line)
            for line in (DATA / "reports/basket_paper.jsonl").read_text().splitlines()
            if line
        ]
        lines = ["🧺 <b>Корзина топ-10 (vol-targeting)</b>", ""]
        if hist:
            last = hist[-1]
            lines.append(
                f"💰 ${last['value_usd']:.2f} ({last['pnl_pct']:+.2f}%) "
                f"| внесено ${last['invested_usd']:.0f} "
                f"| комиссии ${last['fees_paid_usd']:.2f}"
            )
            lines.append(
                f"📅 {last['day']} | правило: {state.get('weights_rule', 'eq')}"
            )
            lines.append(f"💵 кэш: ${state.get('cash_usd', 0.0):.2f}")
        else:
            lines.append("данных нет")
        return "\n".join(lines)
    except Exception as e:
        return f"🧺 Корзина: ошибка ({e})"


def cmd_ab() -> str:
    """A/B Directional v2: сделки, PnL, вердикт (если готов)."""

    try:
        from swarm.quant.quant_ab_report import (
            ab_verdict,
            compare_portfolios,
            load_trade_pnls,
        )

        m = json.loads(
            (DATA / "multi_exchange_portfolios_owner_paper.json").read_text()
        )
        c = json.loads(
            (DATA / "multi_exchange_portfolios_owner_paper_control.json").read_text()
        )
        cmp = compare_portfolios(m, c)
        lines = ["⚖️ <b>Directional v2 A/B</b> (main trail 1.0 vs control 0.988)", ""]
        for tag, key in (("🅰️ main", "main"), ("🅱️ control", "control")):
            st = cmp[key]
            lines.append(
                f"{tag}: {st['closed_trades']} сд. | PnL {st['realized_pnl_usd']:+.2f}$ "
                f"| equity {st['equity_usd']:.2f}$ | DD {st['max_drawdown_pct_seen']:.3f}%"
            )
        v = ab_verdict(load_trade_pnls(m), load_trade_pnls(c))
        if v:
            sig = "✅ значимо" if v["significant"] else "≈ незначимо"
            lines.append(
                f"🔬 Вердикт готов: diff {v['diff_obs']:+.3f}$/сд. "
                f"CI90 [{v['ci90'][0]:+.3f}, {v['ci90'][1]:+.3f}] | {sig}"
            )
        else:
            lines.append(
                "🔬 Вердикт ещё не готов (нужно ≥15 закрытых сделок в каждом контуре)"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"⚖️ A/B: ошибка ({e})"


def cmd_scoreboard() -> str:
    """Последний вердикт ежемесячного scoreboard стратегий."""

    try:
        sb_path = DATA / "reports/strategy_scoreboard.jsonl"
        if not sb_path.exists():
            return "🏆 Scoreboard: данных нет"
        hist = [json.loads(line) for line in sb_path.read_text().splitlines() if line]
        if not hist:
            return "🏆 Scoreboard: данных нет"
        lines = ["🏆 <b>Scoreboard стратегий</b>", ""]
        for row in hist[-3:]:
            v = row.get("verdict") or {}
            w = v.get("winner", "—")
            if v.get("unstable"):
                w += " ⚠️"
            basket = row.get("top10_basket_pct")
            basket_s = f"{basket:+.2f}%" if basket is not None else "—"
            lines.append(
                f"📅 {row['date']}: DV2 {row['dv2']['pnl_pct']:+.2f}% | "
                f"корзина {basket_s} | рынок {row['market_mean_pct']:+.2f}% | 🥇 {w}"
            )
        lines.append("")
        lines.append("Правило: моментум — только при PnL>корзины И OOS CAGR>0.")
        return "\n".join(lines)
    except Exception as e:
        return f"🏆 Scoreboard: ошибка ({e})"
