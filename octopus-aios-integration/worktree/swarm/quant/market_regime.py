#!/usr/bin/env python3
"""Market regime engine (ревизия 2026-08-19, по рекомендациям).

Цель — НЕ предсказывать цену, а честно определять режим рынка из совокупности
доступных индикаторов и выдавать (режим, уровень риска, семейство стратегий,
триггеры смены режима). Используется:
- scripts/quant_regime_engine.py (ежедневный сбор + история);
- swarm/quant/regime_guard.py (kill-guard бумажных входов в CRASH/PANIC);
- swarm/tgbot/trading_report.py (блок «Режим рынка» + AI-аналитик).

Чистые функции; без сетевых вызовов.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGIMES = ("STRONG_BULL", "BULL", "SIDEWAYS", "VOLATILE", "BEAR", "CRASH", "PANIC")

CRASH_PANIC = {"CRASH", "PANIC"}

RISK_BY_REGIME = {
    "STRONG_BULL": "LOW",
    "BULL": "LOW",
    "SIDEWAYS": "MEDIUM",
    "VOLATILE": "HIGH",
    "BEAR": "HIGH",
    "CRASH": "EXTREME",
    "PANIC": "EXTREME",
}

STRATEGY_BY_REGIME = {
    "STRONG_BULL": "momentum/trend (полный экспозицион)",
    "BULL": "momentum/trend",
    "SIDEWAYS": "mean-reversion/range",
    "VOLATILE": "пониженный размер позиций",
    "BEAR": "defensive/низкий экспозицион (DCA-накопление)",
    "CRASH": "сохранение капитала (кэш)",
    "PANIC": "сохранение капитала (кэш)",
}


def classify_regime(i: dict[str, float | None]) -> str:
    """Классификация режима из индикаторов (a-priori правила, без подгонки).

    Приоритет правил: PANIC > CRASH > BEAR > STRONG_BULL > BULL > VOLATILE > SIDEWAYS.
    Отсутствующий индикатор (None) просто выключает зависящие от него правила.
    """

    def num(key: str) -> float | None:
        v = i.get(key)
        return float(v) if v is not None else None

    dd90 = num("dd90_pct")  # просадка от 90-дневного максимума, %
    fng = num("fear_greed")  # 0..100
    ret7 = num("btc_ret_7d_pct")  # 7-дневная доходность BTC, %
    above200 = num("btc_above_sma200")  # 1/0
    above50 = num("btc_above_sma50")
    breadth = num("breadth_7d")  # доля активов вселенной с положительным ret_7d
    vol = num("vol30_annualized_pct")

    if dd90 is not None and dd90 <= -35:
        return "PANIC"
    if fng is not None and fng <= 15:
        return "PANIC"
    if dd90 is not None and dd90 <= -20:
        return "CRASH"
    if ret7 is not None and ret7 <= -15:
        return "CRASH"
    if above200 is not None and above200 <= 0:
        # ниже долгосрочного тренда: медвежий режим, если есть глубокая просадка
        # или отрицательный импульс; иначе — боковик с попыткой восстановления
        if dd90 is not None and dd90 <= -10:
            return "BEAR"
        if ret7 is not None and ret7 < 0:
            return "BEAR"
        return "SIDEWAYS"
    # выше SMA200
    strong = (breadth is None or breadth >= 0.7) and (fng is None or fng >= 60)
    if above50 is not None and above50 > 0 and strong:
        return "STRONG_BULL"
    if breadth is not None and breadth >= 0.5:
        return "BULL"
    if vol is not None and vol >= 80:
        return "VOLATILE"
    return "SIDEWAYS"


def risk_level(regime: str) -> str:
    return RISK_BY_REGIME.get(regime, "UNKNOWN")


def strategy_family(regime: str) -> str:
    return STRATEGY_BY_REGIME.get(regime, "—")


def next_regime_triggers(i: dict[str, float | None], regime: str) -> list[str]:
    """Конкретные условия смены режима (для отчёта и AI-аналитика)."""

    def num(key: str) -> float | None:
        v = i.get(key)
        return float(v) if v is not None else None

    dd90 = num("dd90_pct")
    fng = num("fear_greed")
    above200 = num("btc_above_sma200")
    above50 = num("btc_above_sma50")
    breadth = num("breadth_7d")
    vol = num("vol30_annualized_pct")
    out: list[str] = []
    if above200 is not None:
        out.append(
            f"BTC закроется {'выше' if above200 <= 0 else 'ниже'} SMA200 "
            f"(сейчас {'ниже' if above200 <= 0 else 'выше'})"
        )
    if regime in CRASH_PANIC:
        if fng is not None:
            out.append(f"Fear&Greed выйдет из зоны паники (>25; сейчас {fng:.0f})")
        if dd90 is not None:
            out.append(
                f"просадка от максимума сократится до >-20% (сейчас {dd90:.1f}%)"
            )
    else:
        if dd90 is not None and dd90 <= -15:
            out.append(
                f"углубление просадки <-20% переведёт в CRASH (сейчас {dd90:.1f}%)"
            )
        if breadth is not None and breadth < 0.35:
            out.append(f"breadth восстановится >0.5 (сейчас {breadth:.2f})")
        if vol is not None and vol >= 70:
            out.append(f"волатильность снизится <70% (сейчас {vol:.0f}%)")
    if above50 is not None and above200 is not None:
        if above50 > 0 and above200 <= 0:
            out.append(
                "BTC выше SMA50, но ниже SMA200 — пробой SMA200 подтвердит бычий режим"
            )
        if above50 <= 0 and above200 > 0:
            out.append(
                "BTC ниже SMA50 при цене выше SMA200 — потеря SMA50 ослабит бычий режим"
            )
    return out[:5]


def regime_payload(
    i: dict[str, float | None], regime: str | None = None
) -> dict[str, Any]:
    regime = regime or classify_regime(i)
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regime": regime,
        "risk_level": risk_level(regime),
        "strategy_family": strategy_family(regime),
        "indicators": i,
        "triggers": next_regime_triggers(i, regime),
    }


def write_latest(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        __import__("json").dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def append_history(payload: dict[str, Any], path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "date": payload["generated_at"][:10],
        "regime": payload["regime"],
        "risk_level": payload["risk_level"],
        "indicators": payload["indicators"],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
