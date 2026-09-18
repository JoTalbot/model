"""Pure presentation formatters for quantitative trading reports.

Public compatibility imports remain in ``swarm.quant.quant_trading_engine``.
This module must not perform trading, network or persistence operations.
"""

from typing import Any

__all__ = [
    "format_backtest_report",
    "format_kraken_demo_report",
    "format_portfolio_advice_report",
    "format_positions_only_report",
    "format_single_asset_analysis",
    "format_unified_crypto_earnings_report",
]


def format_kraken_demo_report(report: dict[str, Any]) -> str:
    """Форматирует отчёт демонстрационного счёта Kraken ($100) для Telegram."""
    init_bal = report.get("initial_balance_usd", 100.0)
    cash = report.get("cash_usd", 100.0)
    equity = report.get("total_equity_usd", 100.0)
    total_pnl = report.get("total_pnl_usd", 0.0)
    total_ret = report.get("total_return_pct", 0.0)
    realized = report.get("realized_pnl_usd", 0.0)
    unrealized = report.get("unrealized_pnl_usd", 0.0)
    trades = report.get("total_trades", 0)
    wins = report.get("winning_trades", 0)
    win_rate = report.get("win_rate_pct", 0.0)
    positions = report.get("positions", [])

    pnl_icon = "📈" if total_pnl >= 0 else "📉"
    pnl_sign = "+" if total_pnl > 0 else ""
    realized_sign = "+" if realized > 0 else ""
    unrealized_sign = "+" if unrealized > 0 else ""

    lines = [
        "🐙 <b>Демонстрационный счёт Kraken ($100.00 USD)</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💵 <b>Начальный депозит:</b> ${init_bal:.2f} USD",
        f"💳 <b>Свободный кэш:</b> ${cash:.2f} USD",
        f"📊 <b>Текущий капитал (Equity):</b> <b>${equity:.2f} USD</b>",
        f"{pnl_icon} <b>Общий результат (PnL):</b> <b>{pnl_sign}${total_pnl:.2f} USD ({pnl_sign}{total_ret:.2f}%)</b>",
        "",
        "📈 <b>Статистика процесса заработка:</b>",
        f"• Всего сделок: <b>{trades}</b> (Успешных: <b>{wins}</b>, Винрейт: <b>{win_rate:.1f}%</b>)",
        f"• Реализованная прибыль: <b>{realized_sign}${realized:.2f} USD</b>",
        f"• Незафиксированный PnL: <b>{unrealized_sign}${unrealized:.2f} USD</b>",
        "",
    ]

    if positions:
        lines.append("💼 <b>Открытые позиции на Kraken:</b>")
        for p in positions:
            p_icon = "🟢" if p["unrealized_pnl_usd"] >= 0 else "🔴"
            u_sign = "+" if p["unrealized_pnl_usd"] > 0 else ""
            lines.append(
                f"{p_icon} <b>{p['pair_display']}</b> ({p['side']}):\n"
                f"  – Вход: ${p['entry_price']:.2f} ➔ Рынок: <b>${p['live_price']:.2f}</b>\n"
                f"  – Объём: {p['qty']:.6f} (${p['invested_usd']:.2f})\n"
                f"  – PnL: <b>{u_sign}${p['unrealized_pnl_usd']:.2f} USD ({u_sign}{p['unrealized_pnl_pct']:.2f}%)</b>"
            )
        lines.append("")
    else:
        lines.append(
            "💼 <b>Открытые позиции:</b> <i>В данный момент позиций нет (100% в кэше)</i>"
        )

    lines.extend(
        [
            "🤖 <b>Алгоритм & Стратегия:</b>",
            "• Количественный робот AIOS (SMA 3/10 Crossover + RSI 14)",
            "• Риск-менеджмент: Take-Profit +2.0%, Trailing Stop-Loss -1.0%",
            "• Торговые пары: 24 пары; в этом отчёте учитывается paper-счёт Kraken",
            "",
            "💡 <i>Команды:</i>",
            "<code>баланс кракен</code> — реальный баланс активов",
            "<code>кракен демо сброс</code> — сбросить демо-счёт на $100",
        ]
    )

    return "\n".join(lines)


def format_unified_crypto_earnings_report(report: dict[str, Any]) -> str:
    """Форматирует комплексный отчёт автономного крипто-заработка для Telegram."""
    init_bal = report.get("initial_balance_usd", 100.0)
    cash = report.get("cash_usd", 100.0)
    equity = report.get("total_equity_usd", 100.0)
    total_pnl = report.get("total_pnl_usd", 0.0)
    total_ret = report.get("total_return_pct", 0.0)

    kraken_rep = report.get("kraken_report", {})
    trades = kraken_rep.get("total_trades", 0)
    wins = kraken_rep.get("winning_trades", 0)
    win_rate = kraken_rep.get("win_rate_pct", 0.0)
    positions = kraken_rep.get("positions", [])

    arb = report.get("arbitrage", {})
    arb_scanned = arb.get("pairs_scanned", 0)
    arb_viable = arb.get("viable_count", 0)
    best_spread = arb.get("best_spread_pct", 0.0)

    defi = report.get("defi_yield", {})
    daily_yield = defi.get("daily_yield_usd", 0.0)

    split_25 = report.get("profit_split_25_usd", 0.0)

    pnl_icon = "🚀" if total_pnl >= 0 else "📉"
    pnl_sign = "+" if total_pnl > 0 else ""

    lines = [
        "🚀 <b>AIOS Автономный Крипто-Заработок ($100 Демо)</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💵 <b>Начальный депозит:</b> ${init_bal:.2f} USD",
        f"💳 <b>Свободный кэш:</b> ${cash:.2f} USD",
        f"📊 <b>Текущий капитал (Equity):</b> <b>${equity:.2f} USD</b>",
        f"{pnl_icon} <b>Совокупный PnL:</b> <b>{pnl_sign}${total_pnl:.2f} USD ({pnl_sign}{total_ret:.2f}%)</b>",
        "",
        "🌐 <b>4 Активных Вектора Заработка:</b>",
        "1. 📈 <b>Квантовый paper-trading (отчёт Kraken):</b>",
        f"   • Сделок: <b>{trades}</b> (Успешных: {wins}, Винрейт: <b>{win_rate:.1f}%</b>)",
        "   • Сигналы: SMA 3/10 + RSI 14 + Полосы Боллинджера (20)",
        "2. ⚡ <b>Кросс-DEX Арбитраж (Kraken/Binance/UniV3):</b>",
        f"   • Сканирование пар: {arb_scanned} | Доходных окон: <b>{arb_viable}</b> (Лучший спрэд: <b>{best_spread:.3f}%</b>)",
        "3. 🌾 <b>DeFi Staking & Yield (8.0% APY):</b>",
        f"   • Пассивный доход на кэш: <b>+${daily_yield:.4f} USD/день</b>",
        "4. 🤖 <b>Web3 Bounties & AI Datasets:</b>",
        "   • Авто-решение задач GitHub (Gitcoin/Algora)",
        "",
    ]

    if positions:
        lines.append("💼 <b>Открытые позиции на Kraken:</b>")
        for p in positions:
            p_icon = "🟢" if p.get("unrealized_pnl_usd", 0) >= 0 else "🔴"
            u_sign = "+" if p.get("unrealized_pnl_usd", 0) > 0 else ""
            pair_disp = p.get("pair_display", "")
            side = p.get("side", "")
            entry_p = p.get("entry_price", 0.0)
            live_p = p.get("live_price", 0.0)
            qty = p.get("qty", 0.0)
            inv = p.get("invested_usd", 0.0)
            un_pnl = p.get("unrealized_pnl_usd", 0.0)
            un_pct = p.get("unrealized_pnl_pct", 0.0)
            lines.append(f"{p_icon} <b>{pair_disp}</b> ({side}):")
            lines.append(f"  – Вход: ${entry_p:.4f} ➔ Рынок: <b>${live_p:.4f}</b>")
            lines.append(f"  – Объём: {qty:.6f} (${inv:.2f})")
            lines.append(
                f"  – PnL: <b>{u_sign}${un_pnl:.2f} USD ({u_sign}{un_pct:.2f}%)</b>"
            )
        lines.append("")
    else:
        lines.append(
            "💼 <b>Открытые позиции:</b> <i>В данный момент позиций нет (100% в кэше)</i>"
        )
        lines.append("")

    lines.extend(
        [
            "💰 <b>Распределение прибыли (Правило 25% × 4):</b>",
            f"• 👨‍💻 Разработчик (25%): <b>${split_25:.2f} USD</b>",
            f"• 🏦 Инвестор (25%): <b>${split_25:.2f} USD</b>",
            f"• 👥 Персонал (25%): <b>${split_25:.2f} USD</b>",
            f"• 🤖 AIOS Фонд (25%): <b>${split_25:.2f} USD</b>",
            "",
            "💡 <i>Команды:</i>",
            "<code>крипто заработок</code> — полный отчёт",
            "<code>кракен демо сброс</code> — сброс счёта на $100",
            "<code>баланс кракен</code> — реальный баланс активов",
        ]
    )

    return "\n".join(lines)


def format_positions_only_report(report: dict[str, Any]) -> str:
    """Форматирует позиции по всем настроенным paper-биржам."""
    exchanges = report.get("exchanges", {})
    lines = [f"💼 <b>Сводка открытых позиций по {len(exchanges)} биржам AIOS:</b>", ""]
    total_pos = 0

    for ex_key, ex_data in exchanges.items():
        ex_name = ex_data.get("name", ex_key.upper())
        poss = ex_data.get("positions", [])
        if poss:
            lines.append(f"<b>{ex_name}</b> ({len(poss)} позиций):")
            # Показываем первые 4 позиций для лаконичности
            for p in poss[:4]:
                total_pos += 1
                u_pnl = p.get("unrealized_pnl_usd", 0.0)
                u_sign = "+" if u_pnl > 0 else ""
                p_icon = "🟢" if u_pnl >= 0 else "🔴"
                pair_disp = p.get("pair", "")
                ep = p.get("entry_price", 0.0)
                lp = p.get("live_price", 0.0)
                lines.append(
                    f"  {p_icon} <b>{pair_disp}</b>: Вход ${ep:.4f} ➔ Рынок ${lp:.4f} | PnL: <b>{u_sign}${u_pnl:.2f}</b>"
                )
            if len(poss) > 4:
                lines.append(f"  <i>... и ещё {len(poss) - 4} позиций</i>")
            lines.append("")

    if total_pos == 0:
        lines.append(
            "<i>В данный момент открытых позиций нет (100% средств в свободном кэше).</i>"
        )

    return "\n".join(lines)


def format_single_asset_analysis(data: dict[str, Any]) -> str:
    """Форматирует карточку ИИ-анализа монеты для Telegram."""
    sym = data.get("symbol", "BTC")
    p = data.get("avg_price", 0.0)
    prices = data.get("prices_by_exchange", {})
    analysis = data.get("analysis", {})
    ob = data.get("orderbook", {})
    sent = data.get("sentiment", {})
    verdict = data.get("llm_verdict", "")

    sig = analysis.get("signal", "HOLD")
    conf = analysis.get("confidence", 0.5) * 100
    icon = "🟢" if "BUY" in sig else ("🔴" if "SELL" in sig else "⚪")

    lines = [
        f"🔮 <b>ИИ-Анализ & Прогноз AIOS для {sym}</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💵 <b>Средняя цена:</b> <b>${p:,.4f} USD</b>",
        f"{icon} <b>ИИ-Сигнал:</b> <b>{sig}</b> (Уверенность: <b>{conf:.0f}%</b>)",
        f"💡 <b>Факторы:</b> <i>{analysis.get('reason')}</i>",
        "",
        "📊 <b>Цены на биржах:</b>",
    ]
    for ex_k, ex_p in prices.items():
        lines.append(f"• {ex_k.upper()}: <b>${ex_p:,.4f}</b>")

    lines.extend(
        [
            "",
            "📐 <b>Метрики & Деривативы:</b>",
            f"• RSI (14): <b>{analysis.get('rsi')}</b> | MACD: <b>{analysis.get('macd')}</b>",
            f"• Ставка Фандинга: <b>{analysis.get('funding_rate')}%</b>",
            f"• Стакан ордеров: <b>{ob.get('status')}</b>",
            f"• Рыночный сентимент: <b>{sent.get('verdict')}</b>",
            "",
            "🤖 <b>Вердикт ИИ-Аналитика:</b>",
            f"<i>{verdict}</i>",
        ]
    )

    return "\n".join(lines)


def format_backtest_report(data: dict[str, Any]) -> str:
    """Форматирует отчёт ИИ-бэктестинга и оптимизации параметров для Telegram."""
    sym = data.get("symbol", "BTC")
    candles = data.get("candles_analyzed", 0)
    strats = data.get("strategies", {})
    best = data.get("best_strategy", "")

    lines = [
        f"🧪 <b>ИИ-Бэктестинг & Авто-Тюнинг для {sym}</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Проанализировано свечей истории: <b>{candles}</b>",
        "",
        "🏆 <b>Результаты симуляции алгоритмов ($200/сделка):</b>",
    ]

    for s_name, s_info in strats.items():
        tr = s_info.get("trades", 0)
        w = s_info.get("wins", 0)
        pnl = s_info.get("pnl", 0.0)
        wr = (w / tr * 100.0) if tr > 0 else 0.0
        p_sign = "+" if pnl > 0 else ""
        star = " 🌟 (ЛУЧШИЙ ПРЕСЕТ)" if s_name == best else ""
        lines.append(f"• <b>{s_name}</b>{star}:")
        lines.append(f"  – Сделок: <b>{tr}</b> (Винрейт: <b>{wr:.1f}%</b>)")
        lines.append(f"  – Моделируемый PnL: <b>{p_sign}${pnl:.2f} USD</b>")

    lines.extend(
        [
            "",
            f"🤖 <b>Рекомендуемый Пресет:</b> <b>{best}</b>",
            "<i>Квантовый робот AIOS автоматически применяет оптимальный пресет для текущей волатильности.</i>",
        ]
    )

    return "\n".join(lines)


def format_portfolio_advice_report(data: dict[str, Any]) -> str:
    """Форматирует карточку ИИ-совета по портфелю для Telegram."""
    rep = data.get("report", {})
    adv = data.get("advice_text", "")

    lines = [
        "🧠 <b>ИИ-Советник по Оптимизации Paper-Портфеля AIOS</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Текущий капитал:</b> <b>${rep.get('total_equity_usd', 10000.0):,.2f} USD</b>",
        f"💳 <b>Свободный кэш:</b> ${rep.get('total_cash_usd', 10000.0):,.2f} USD",
        f"📈 <b>Результат (PnL):</b> <b>${rep.get('grand_total_pnl_usd', 0.0):.2f} USD</b>",
        "",
        "💡 <b>Рекомендации ИИ-Управляющего:</b>",
        f"<i>{adv}</i>",
    ]

    return "\n".join(lines)
