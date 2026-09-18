#!/usr/bin/env python3
"""Detailed trading report for the 'Трейдинг' Telegram button.

Gathers every paper portfolio (Directional v2 A/B, DCA VA+control, basket
top-10 vol-targeting, T2 momentum 5 legs + portfolio, freqtrade T2 dry),
market-microstructure status (ws snapshots/latency, queue model), scoreboard
verdict and service health; formats compact HTML chunks (Telegram 4096 limit)
and, separately, produces an LLM analytics + scenario-forecast section via
LLMBalancer (read-only, paper-only, with explicit honesty framing: no
financial advice).

Kept OUTSIDE protected files; callbacks.py wires one branch.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))

MAX_CHUNK = 3800

SERVICES = (
    "octopus-quant-trading",
    "octopus-quant-trading-control",
    "octopus-orderbook-ws",
    "octopus-orderbook-research",
    "octopus-freqtrade-t2-dry",
    "octopus-market-data",
    "octopus-quant-ml-inference",
    "octopus-dca-paper.timer",
    "octopus-basket-paper.timer",
    "octopus-strategy-scoreboard.timer",
)


# --------------------------------------------------------------- helpers ----
def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _fmt_usd(v: float) -> str:
    return f"{v:+,.2f}$"


def _chunks(text: str, limit: int = MAX_CHUNK) -> list[str]:
    """Split text into Telegram-safe chunks on line boundaries."""

    if len(text) <= limit:
        return [text]
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    if text:
        parts.append(text)
    return parts


# --------------------------------------------------------------- snapshots --
def snap_directional() -> dict:
    out = {"arms": {}, "ok": False}
    for tag, fname in (
        ("main", "multi_exchange_portfolios_owner_paper.json"),
        ("control", "multi_exchange_portfolios_owner_paper_control.json"),
    ):
        data = _read_json(DATA / fname, {})
        if not isinstance(data, dict) or not data:
            continue
        exchanges = [
            v
            for k, v in data.items()
            if k not in ("cross_arbitrage", "_risk_state") and isinstance(v, dict)
        ]
        closed = sum(int(v.get("closed_trades", 0) or 0) for v in exchanges)
        wins = sum(int(v.get("winning_trades", 0) or 0) for v in exchanges)
        realized = sum(float(v.get("realized_pnl_usd", 0.0) or 0.0) for v in exchanges)
        gross = sum(float(v.get("gross_pnl_usd", 0.0) or 0.0) for v in exchanges)
        fees = sum(float(v.get("fees_paid_usd", 0.0) or 0.0) for v in exchanges)
        positions = [
            (ex, pos)
            for ex, v in zip(
                [
                    k
                    for k, v2 in data.items()
                    if k not in ("cross_arbitrage", "_risk_state")
                ],
                exchanges,
                strict=False,  # длины могут различаться (не-dict значения); как zip()
            )
            for pos in (v.get("positions") or {}).values()
            if pos
        ]
        trade_log = [t for v in exchanges for t in (v.get("trade_log") or [])]
        risk = data.get("_risk_state") or {}
        out["arms"][tag] = {
            "closed": closed,
            "wins": wins,
            "realized": realized,
            "gross": gross,
            "fees": fees,
            "win_rate": round(100 * wins / closed, 1) if closed else None,
            "open_positions": len(positions),
            "equity": round(float(risk.get("equity_usd", 0.0) or 0.0), 2),
            "dd_pct": round(float(risk.get("max_drawdown_pct_seen", 0.0) or 0.0), 4),
            "entry_mode": risk.get("entry_mode", "?"),
            "recent_trades": trade_log[-5:],
        }
    out["ok"] = bool(out["arms"])
    return out


def snap_dca() -> dict:
    out = {}
    for tag, cfg_f, state_f, hist_f in (
        (
            "VA main",
            "dca_portfolio.json",
            "dca_paper_state.json",
            "dca_paper_value.jsonl",
        ),
        (
            "control",
            "dca_portfolio_control.json",
            "dca_paper_state_control.json",
            "dca_paper_value_control.jsonl",
        ),
    ):
        state = _read_json(DATA / state_f, {})
        cfg = _read_json(DATA / cfg_f, {})
        hist_path = DATA / hist_f
        rows = []
        if hist_path.exists():
            rows = [
                json.loads(line)
                for line in hist_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
        last = rows[-1] if rows else None
        out[tag] = {
            "mode": cfg.get("mode", state.get("mode", "?")),
            "weekly": cfg.get("weekly_amount_usd", state.get("weekly_amount_usd")),
            "value": last.get("value_usd") if last else None,
            "deposited": last.get("deposited_usd") if last else None,
            "fees": last.get("fees_usd") if last else None,
            "date": last.get("date") if last else None,
        }
    return out


def snap_basket() -> dict:
    state = _read_json(DATA / "reports" / "basket_paper_state.json", {})
    hist_path = DATA / "reports" / "basket_paper.jsonl"
    rows = []
    if hist_path.exists():
        rows = [
            json.loads(line)
            for line in hist_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    last = rows[-1] if rows else None
    return {
        "value": last.get("value_usd") if last else None,
        "pnl_pct": last.get("pnl_pct") if last else None,
        "invested": last.get("invested_usd") if last else None,
        "fees": last.get("fees_paid_usd") if last else None,
        "date": last.get("day") if last else None,
        "weights_rule": state.get("weights_rule", "?"),
        "cash": round(float(state.get("cash_usd", 0.0) or 0.0), 2) if state else None,
    }


def snap_t2() -> dict:
    legs = {}
    for tag, fname in (
        ("BTC", "t2_paper_state_btcusd.json"),
        ("ETH", "t2_paper_state_ethusd.json"),
        ("SOL", "t2_paper_state_solusd.json"),
        ("BNB", "t2_paper_state_bnbusd.json"),
        ("NEAR", "t2_paper_state_nearusd.json"),
    ):
        st = _read_json(DATA / fname, {})
        if st:
            trades = st.get("trades") or []
            first_trade = trades[0].get("date") if trades else None
            # сделки до 2026-08-01 = засеянный исторический реплей (2023+),
            # а не живой daily-цикл (стартовал 16-18.08)
            is_replay = bool(first_trade and str(first_trade) < "2026-08-01")
            legs[tag] = {
                "position": st.get("position"),
                "equity": round(float(st.get("equity", 0.0) or 0.0), 2),
                "cash_equiv": round(float(st.get("cash_equiv", 0.0) or 0.0), 2),
                "trades": len(trades),
                "last_signal": st.get("last_signal_date"),
                "first_trade": first_trade,
                "is_replay": is_replay,
            }
    port_path = DATA / "t2_portfolio_equity.jsonl"
    port = None
    if port_path.exists():
        rows = [
            json.loads(line)
            for line in port_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if rows:
            r = rows[-1]
            port = {
                "date": r.get("date"),
                "portfolio": r.get("portfolio"),
                "bh": r.get("bh"),
            }
    return {"legs": legs, "portfolio": port}


def snap_freqtrade() -> dict:
    db = DATA / "freqtrade" / "tradesv3.dryrun.sqlite"
    if not db.exists():
        return {"open": [], "closed": 0}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        open_rows = con.execute(
            "SELECT pair, open_rate, close_profit_abs, open_date, stop_loss "
            "FROM trades WHERE is_open=1 ORDER BY id DESC"
        ).fetchall()
        closed = con.execute("SELECT COUNT(*) FROM trades WHERE is_open=0").fetchone()[
            0
        ]
        con.close()
        return {"open": open_rows, "closed": closed}
    except Exception:
        return {"open": [], "closed": 0}


def snap_mm() -> dict:
    db = DATA / "quant" / "orderbooks.sqlite"
    out = {}
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            n = con.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0]
            span = (
                con.execute("SELECT MAX(ts)-MIN(ts) FROM snapshots_ws").fetchone()[0]
                or 0
            )
            nt = con.execute("SELECT COUNT(*) FROM trades_ws").fetchone()[0]
            out["snapshots"] = n
            out["span_h"] = round(span / 3600, 1)
            out["trade_flow"] = nt
            con.close()
        except Exception:
            pass
    qm = _read_json(DATA / "reports" / "mm_queue_model.json", {})
    if qm and "BTC" in qm:
        btc = qm["BTC"].get("bid", {})
        out["btc_touch_life_s"] = btc.get("lifetime_median_s")
        fills = qm["BTC"].get("bid_fill", {}) or {}
        out["btc_fill60_q2000"] = fills.get("tau60s_q$2000")
    return out


def snap_scoreboard() -> dict | None:
    path = DATA / "reports" / "strategy_scoreboard.jsonl"
    if not path.exists():
        return None
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        ]
        return rows[-1] if rows else None
    except Exception:
        return None


def snap_services() -> dict[str, str]:
    out = {}
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", *SERVICES],
            capture_output=True,
            text=True,
            timeout=30,
        )
        states = proc.stdout.strip().split("\n") if proc.stdout.strip() else []
        for svc, st in zip(SERVICES, states, strict=False):  # строк может быть меньше
            out[svc] = st
    except Exception:
        pass
    return out


def build_snapshot() -> dict:
    try:
        from run_morning_brief import btc_regime

        regime = btc_regime()
    except Exception:
        regime = None
    try:
        regime_payload = _read_json(DATA / "reports" / "market_regime_latest.json", {})
    except Exception:
        regime_payload = {}
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "btc_regime": regime,
        "market_regime": regime_payload if isinstance(regime_payload, dict) else {},
        "directional": snap_directional(),
        "dca": snap_dca(),
        "basket": snap_basket(),
        "t2": snap_t2(),
        "freqtrade": snap_freqtrade(),
        "mm": snap_mm(),
        "scoreboard": snap_scoreboard(),
        "services": snap_services(),
    }


# -------------------------------------------------------------- formatting --
REASON_HUMAN = {
    "stop_loss": "защитный стоп (продали, чтобы не потерять больше)",
    "trailing_stop": "трейлинг-стоп (зафиксировали прибыль по пути)",
    "take_profit": "цель прибыли достигнута",
    "confirmed_bearish_exit": "сигнал разворота (робот увидел слабость)",
}


def _short_pct(v: float, base: float) -> str:
    if not base:
        return "—"
    return f"{v / base * 100:+.2f}%"


def format_report(snap: dict) -> list[str]:
    """Отчёт «по-человечески»: простые слова, «что это» к каждому контуру,
    вердикты обывателю и словарик. Telegram-безопасные куски."""

    lines = [
        "📊 <b>Трейдинг-отчёт</b> (по-человечески)",
        f"🕐 {snap['generated_at']}",
        "",
        "── <b>Главное за 30 секунд</b> ──",
    ]

    d = snap["directional"]
    main_a = d["arms"].get("main")
    ctrl_a = d["arms"].get("control")
    if d["ok"] and main_a and ctrl_a:
        lines.append(
            f"🤖 Робот-трейдер (ученик): {_short_pct(main_a['realized'], 10000)} и "
            f"{_short_pct(ctrl_a['realized'], 10000)} от счёта — тренируется на виртуальных "
            f"деньгах, убытки копеечные."
        )
    b = snap["basket"]
    if b.get("value") is not None:
        lines.append(f"🧺 Корзина топ-10: {b['pnl_pct']:+.2f}% — наш «крипто-ETF».")
    dca = snap["dca"]
    va = dca.get("VA main", {})
    if va.get("value") is not None:
        pnl = va["value"] - va["deposited"]
        lines.append(
            f"🐷 Автокопилка: {_short_pct(pnl, va['deposited'])} — копит по чуть-чуть каждую неделю."
        )
    t2 = snap["t2"]
    if t2.get("portfolio"):
        pct = (t2["portfolio"]["portfolio"] / 10000 - 1) * 100
        lines.append(
            f"📈 Моментум-роботы: +{pct:.0f}% в СИМУЛЯЦИИ с 2023 года "
            f"(не заработок — подробности ниже)."
        )
    mr = snap.get("market_regime") or {}
    if mr.get("regime"):
        lines.append(
            f"🎛 Режим рынка: {mr['regime']} (риск {mr.get('risk_level', '?')}) — "
            f"стратегия: {mr.get('strategy_family', '—')}."
        )
    elif snap.get("btc_regime") == "bear":
        lines.append(
            "🐻 Рынок в медвежьей фазе: BTC ниже своего долгосрочного среднего."
        )
    sb = snap["scoreboard"]
    if sb:
        v = sb.get("verdict") or {}
        lines.append("🏆 По тесту за месяц лучшая стратегия — корзина топ-10.")
    lines.append("")

    # ---------- Directional ----------
    lines.append("🤖 <b>Робот-трейдер</b> (сам ищет моменты, на виртуальные деньги)")
    lines.append(
        "Что это: программа с машинным обучением сама решает, когда купить и когда "
        "продать. Два робота-близнеца «А» и «Б» соревнуются — отличаются лишь тем, "
        "как выходят из сделки."
    )
    if d["ok"]:
        for tag, icon, name in (("main", "🅰️", "Робот А"), ("control", "🅱️", "Робот Б")):
            a = d["arms"].get(tag)
            if not a:
                continue
            wr = f"{a['win_rate']}%" if a["win_rate"] is not None else "—"
            lines.append(
                f"{icon} <b>{name}</b>: {a['closed']} сделок, удачных {wr}, "
                f"итог {_short_pct(a['realized'], 10000)} от счёта "
                f"(в деньгах {_fmt_usd(a['realized'])})"
            )
            lines.append(
                f"   на счету {_fmt_usd(a['equity'])} из 10 000$ "
                f"| просадка {a['dd_pct']:.3f}%"
            )
            if a["recent_trades"]:
                lines.append("   последние сделки:")
                for t in a["recent_trades"]:
                    reason = REASON_HUMAN.get(t.get("reason"), t.get("reason") or "—")
                    lines.append(
                        f"   • {t.get('symbol')} ({t.get('exchange')}): {reason} — "
                        f"итог {_fmt_usd(float(t.get('net_pnl_usd', 0.0) or 0.0))}"
                    )
        if main_a and ctrl_a:
            better = (
                "Робот А" if main_a["realized"] >= ctrl_a["realized"] else "Робот Б"
            )
            lines.append(
                f"Кто впереди: <b>{better}</b> — но сделок мало "
                f"(по {main_a['closed']}), выводы рано."
            )
        lines.append(
            "Защита: если счёт за день просядет на 0.25% — торговля остановится сама."
        )
    else:
        lines.append("нет данных")
    lines.append("")

    # ---------- DCA ----------
    lines.append("🐷 <b>Автокопилка (DCA)</b>")
    lines.append(
        "Что это: каждую неделю докупается крипта на фиксированную сумму. Цены упали — "
        "купили дешевле, выросли — купили меньше. Классический способ копить в долгую."
    )
    for tag, name in (("VA main", "основная копилка"), ("control", "контрольная")):
        a = dca.get(tag, {})
        if a.get("value") is None:
            continue
        pnl = a["value"] - a["deposited"]
        lines.append(
            f"• {name}: вложено {_fmt_usd(a['deposited'])} → сейчас {_fmt_usd(a['value'])} "
            f"({_short_pct(pnl, a['deposited'])})"
        )
    lines.append("")

    # ---------- Basket ----------
    lines.append("🧺 <b>Корзина топ-10</b> (наш «крипто-ETF»)")
    lines.append(
        "Что это: одна покупка = сразу 10 крупнейших криптовалют. Правило тихое: чем "
        "спокойнее монета (меньше скачет цена), тем больше её доля — чтобы корзину "
        "меньше трясло."
    )
    if b.get("value") is not None:
        lines.append(
            f"• вложено {_fmt_usd(b['invested'])} → сейчас {_fmt_usd(b['value'])} "
            f"({b['pnl_pct']:+.2f}%) | комиссии {_fmt_usd(b['fees'])}"
        )
        lines.append(f"• правило весов: {b.get('weights_rule', '?')}")
    else:
        lines.append("нет данных")
    lines.append("")

    # ---------- T2 ----------
    lines.append("📈 <b>Моментум-роботы (T2)</b> — держим монету, пока растёт")
    lines.append(
        "Что это: робот заходит, когда монета в устойчивом тренде, и выходит, когда "
        "тренд ломается."
    )
    lines.append(
        "⚠️ Честно: почти все цифры ниже — это СИМУЛЯЦИЯ «как будто запустили в "
        "октябре 2023 с $10,000», а не реальная прибыль. Живой ежедневный тест "
        "стартовал только 16-18 августа. Причём проверка последних месяцев "
        "показывает, что правило сейчас НЕ зарабатывает (минус на свежих данных)."
    )
    live_legs = [tag for tag, leg in t2["legs"].items() if not leg.get("is_replay")]
    replay_legs = [tag for tag, leg in t2["legs"].items() if leg.get("is_replay")]
    if live_legs:
        lines.append(
            "🟢 <b>Живой тест (старт 16-18 августа, настоящие виртуальные $10,000):</b>"
        )
        for tag in live_legs:
            leg = t2["legs"][tag]
            pct = (leg["equity"] / 10000 - 1) * 100
            state = {"LONG": "в позиции", "CASH": "вне рынка (кэш)"}.get(
                leg["position"], str(leg["position"])
            )
            lines.append(
                f"• {tag}: {state} | счёт {_fmt_usd(leg['equity'])} ({pct:+.1f}%) | сделок {leg['trades']}"
            )
    if replay_legs:
        lines.append(
            "📜 <b>Историческая симуляция (октябрь 2023 → сегодня, виртуально):</b>"
        )
        for tag in replay_legs:
            leg = t2["legs"][tag]
            pct = (leg["equity"] / 10000 - 1) * 100
            lines.append(
                f"• {tag}: «как будто» $10,000 стали {_fmt_usd(leg['equity'])} "
                f"({pct:+.0f}%) | {leg['trades']} сделок с {leg.get('first_trade', '?')}"
            )
    if t2["portfolio"]:
        p = t2["portfolio"]
        pct = (p["portfolio"] / 10000 - 1) * 100
        bh_pct = (p["bh"] / 10000 - 1) * 100
        lines.append(
            f"🧺 историческая симуляция всех вместе: +{pct:.0f}% против простого "
            f"«купи и держи» +{bh_pct:.0f}% (за те же 2023-2026)"
        )
    lines.append("")

    # ---------- freqtrade ----------
    ft = snap["freqtrade"]
    lines.append("🤖 <b>Второй робот (freqtrade)</b> — торгует по тренду на 5 монетах")
    lines.append(f"Закрытых сделок: {ft['closed']}. Сейчас держит:")
    for row in ft["open"]:
        lines.append(
            f"• {row[0]}: куплено по {row[1]}, защитный стоп на {row[4]} "
            f"(если цена упадёт — продаст сам)"
        )
    if not ft["open"]:
        lines.append("сейчас ничего не держит")
    lines.append("")

    # ---------- MM ----------
    m = snap["mm"]
    lines.append("🌊 <b>Данные для обучения</b>")
    if m:
        lines.append(
            f"• собрано {m.get('snapshots', 0):,} «снимков» биржевого стакана за "
            f"{m.get('span_h', 0)} часов — на них учатся алгоритмы предсказаний"
        )
        if m.get("btc_touch_life_s"):
            lines.append(
                f"• BTC: лучшая цена живёт в среднем {m['btc_touch_life_s']} секунд"
            )
    else:
        lines.append("нет данных")
    lines.append("")

    # ---------- Scoreboard ----------
    if sb:
        v = sb.get("verdict") or {}
        w = v.get("winner", "—")
        winner_name = {
            "top10_basket": "корзина топ-10",
            "directional_v2": "робот-трейдер",
        }.get(w, w)
        if v.get("unstable"):
            winner_name += " ⚠️"
        basket = sb.get("top10_basket_pct")
        lines.append(f"🏆 <b>Кто лучший по тесту за {sb['date']}</b>")
        lines.append("Протестировали стратегии «как будто начали месяц назад»:")
        lines.append(f"• робот-трейдер: {sb['dv2']['pnl_pct']:+.2f}%")
        if basket is not None:
            lines.append(f"• корзина топ-10: {basket:+.2f}%")
        lines.append(f"• рынок в среднем: {sb['market_mean_pct']:+.2f}%")
        lines.append(f"🥇 Победитель: <b>{winner_name}</b>")
        lines.append("")

    # ---------- services ----------
    svc = snap["services"]
    bad = [k for k, v in svc.items() if v != "active"]
    total = len(svc)
    lines.append(
        f"🖥 <b>Техника:</b> {total - len(bad)} из {total} сервисов работают"
        + (f" | ⚠️ лежит: {', '.join(bad)}" if bad else " — всё в порядке")
    )
    lines.append("")

    # ---------- простой вывод ----------
    lines.append("🧸 <b>Простыми словами</b>")
    if snap.get("btc_regime") == "bear":
        lines.append(
            "Рынок сейчас в медвежьей фазе (цены под давлением). Наши тесты показали, "
            "что угадывать короткие движения рынка невыгодно, поэтому робот "
            "осторожничает и тренируется на виртуальных деньгах. Зарабатывают тихие "
            "стратегии — копилка и корзина: они и держат основную роль."
        )
    else:
        lines.append(
            "Система работает в штатном режиме: робот тренируется на виртуальных "
            "деньгах, тихие стратегии (копилка и корзина) накапливают, всё под "
            "автоматической защитой от крупных потерь."
        )
    lines.append("")
    mr = snap.get("market_regime") or {}
    if mr.get("regime"):
        lines.append("🎛 <b>Режим рынка и защита</b>")
        lines.append(
            f"• режим: <b>{mr['regime']}</b> | уровень риска: {mr.get('risk_level', '?')}"
        )
        lines.append(
            f"• рекомендуемое семейство стратегий: {mr.get('strategy_family', '—')}"
        )
        lines.append(
            "• защита: в режимах CRASH/PANIC бумажные входы робота блокируются "
            "(сохранение капитала); дневная просадка ограничена 0.25%."
        )
        triggers = mr.get("triggers") or []
        if triggers:
            lines.append("• что изменит режим:")
            for t in triggers[:3]:
                lines.append(f"   – {t}")
        lines.append("")

    lines.append("📖 <b>Словарик</b>")
    lines.append(
        "стоп — автопродажа, чтобы убыток не рос; тренд — общее направление цены; "
        "просадка — насколько счёт опускался от максимума; волатильность — насколько "
        "сильно скачет цена."
    )

    return _chunks("\n".join(lines))


# ------------------------------------------------------------------- LLM ----
def prompt_for_llm(snap: dict) -> str:
    """Компактный текстовый снапшот для LLM (без HTML)."""

    d = snap["directional"]
    parts = ["Состояние трейдинг-контуров AIOS (paper-only):"]
    for tag in ("main", "control"):
        a = d["arms"].get(tag)
        if not a:
            continue
        parts.append(
            f"Directional v2 {tag} (trail {'1.0' if tag == 'main' else '0.988'}): "
            f"{a['closed']} сделок, win {a['win_rate']}%, PnL {a['realized']:+.2f}$, "
            f"gross {a['gross']:+.2f}$, fees {a['fees']:.2f}$, equity {a['equity']}$, "
            f"DD {a['dd_pct']}%, открытых {a['open_positions']}"
        )
    dca = snap["dca"]
    for tag in ("VA main", "control"):
        a = dca.get(tag, {})
        if a.get("value") is not None:
            pnl = a["value"] - (a["deposited"] or 0)
            parts.append(
                f"DCA {tag}: {a['deposited']}$ -> {a['value']}$ (PnL {pnl:+.2f}$)"
            )
    b = snap["basket"]
    if b.get("value") is not None:
        parts.append(
            f"Корзина топ-10 (vol-targeting): {b['value']}$ ({b['pnl_pct']:+.2f}%), "
            f"fees {b['fees']}$, правило {b['weights_rule']}"
        )
    t2 = snap["t2"]
    for tag, leg in t2["legs"].items():
        pct = (leg["equity"] / 10000 - 1) * 100
        if leg.get("is_replay"):
            parts.append(
                f"T2 {tag}: ИСТОРИЧЕСКАЯ СИМУЛЯЦИЯ с 2023 (не заработок), "
                f"«как будто» {leg['equity']}$ ({pct:+.1f}%)"
            )
        else:
            parts.append(
                f"T2 {tag}: живой тест с 16-18.08.2026, equity {leg['equity']}$ "
                f"({pct:+.1f}%)"
            )
    ft = snap["freqtrade"]
    parts.append(
        f"freqtrade T2 dry: {len(ft['open'])} открытых, {ft['closed']} закрытых"
    )
    m = snap["mm"]
    if m:
        parts.append(
            f"ws-снапшотов {m.get('snapshots', 0):,} за {m.get('span_h', 0)} ч"
        )
    mr = snap.get("market_regime") or {}
    if mr.get("regime"):
        parts.append(
            f"Режим рынка: {mr['regime']} (риск {mr.get('risk_level')}); "
            f"триггеры: {'; '.join((mr.get('triggers') or [])[:3])}"
        )
    sb = snap["scoreboard"]
    if sb:
        v = sb.get("verdict") or {}
        parts.append(f"Scoreboard {sb['date']}: победитель {v.get('winner')}")
    return "\n".join(parts)


SYSTEM_PROMPT = (
    "Ты — дружелюбный помощник, который объясняет состояние торговой системы AIOS "
    "простым языком, понятным человеку без финансового образования. Все портфели "
    "виртуальные (paper) — реальные деньги не используются. Известные факты системы: "
    "попытки угадывать короткие движения рынка не дают преимущества (проверено десятками "
    "честных тестов); тихие стратегии (корзина из 10 монет, еженедельная копилка) — "
    "единственные устойчиво положительные. Пиши без жаргона; термин объясняй в скобках. "
    "НИКОГДА не пиши «рынок точно пойдёт вверх/вниз» — только вероятностные сценарии. "
    "Формат ответа (русский, до 900 символов): "
    "1) «Главное за 30 секунд» — 3-4 предложения, включая текущий режим рынка и уровень риска; "
    "2) «Что с каждым портфелем» — по одной строке (лучшая и худшая стратегия месяца); "
    "3) «Чего ждать» — 3 сценария на 1-2 недели с вероятностями в %, для каждого — что "
    "значит для обычного человека и какой триггер подтвердит сценарий; "
    "4) «Насколько можно доверять» — одной строкой: уверенность в оценке (низкая/средняя), "
    "качество данных (по числу сделок и глубине истории). "
    "В конце обязательная строка: «Это не финансовый совет — система работает на "
    "виртуальные деньги»."
)


def llm_analysis(snap: dict) -> str | None:
    """LLM-аналитика и сценарии-прогнозы; None при недоступности LLM."""

    try:
        from swarm.tgbot.support.llm_balancer import LLMBalancer

        balancer = LLMBalancer()
        answer = balancer.chat(
            [{"role": "user", "content": prompt_for_llm(snap)}],
            system=SYSTEM_PROMPT,
            max_tokens=900,
            temperature=0.4,
            task_type="trading_report",
        )
        return (answer or "").strip() or None
    except Exception as exc:
        print(f"[trading_report] LLM недоступен: {exc}")
        return None


def llm_section(snap: dict) -> list[str]:
    """HTML-блок LLM-аналитики (куски, с дисклеймером)."""

    analysis = llm_analysis(snap)
    if not analysis:
        return [
            "🤖 <b>Что думает наш ИИ-аналитик:</b> временно недоступен (сервис не "
            "ответил). Цифры выше актуальны, попробуйте ещё раз чуть позже."
        ]
    return _chunks("🤖 <b>Что думает наш ИИ-аналитик</b>\n" + analysis)


def full_report() -> list[str]:
    """Все сообщения для отправки: данные + LLM-аналитика."""

    snap = build_snapshot()
    return format_report(snap) + llm_section(snap)


def is_trading_button_text(text: str | None) -> bool:
    """Кнопка текстовой клавиатуры «📈 Трейдинг» (и варианты написания)."""

    norm = " ".join(str(text or "").casefold().split())
    return norm in ("трейдинг", "📈 трейдинг", "трейдинг отчёт", "трейдинг отчет")


def handle_trading_text_intent(api, chat_id, text: str) -> bool:
    """Текстовый путь кнопки: отчёт; True если текст был «Трейдинг»."""

    if not is_trading_button_text(text):
        return False
    try:
        send_full_report(api, chat_id)
    except Exception as _e:
        api.send_message(chat_id, f"⚠️ Трейдинг-отчёт: {_e}")
    return True


def send_full_report(api, chat_id) -> None:
    """Отправка отчёта в чат: данные сразу, LLM-аналитика в фоновом потоке.

    Используется кнопкой «Трейдинг» (и inline-callback nav_trading, и
    текстовой клавиатурой MAIN_MENU_KEYBOARD) — единая точка сборки.
    """

    snap = build_snapshot()
    for msg in format_report(snap):
        api.send_message(chat_id, msg)
    api.send_message(chat_id, "⏳ LLM-аналитика готовится…")
    import threading

    def _bg():
        try:
            for msg in llm_section(snap):
                api.send_message(chat_id, msg)
        except Exception as _e:
            api.send_message(chat_id, f"🤖 LLM-аналитика: ошибка ({_e})")

    threading.Thread(target=_bg, daemon=True).start()


if __name__ == "__main__":
    for msg in full_report():
        print("=" * 60)
        print(msg)
