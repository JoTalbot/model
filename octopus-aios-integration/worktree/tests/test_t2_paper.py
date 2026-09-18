#!/usr/bin/env python3
"""Wave 5b: T2 paper loop (needs numpy; skipped in prod venv)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import numpy as np

from scripts.aios.freqtrade import run_t2_momentum as t2


def check(name: str, cond: bool, detail: str = ""):
    print(f"  {'✅' if cond else '❌'} {name} {detail if not cond else ''}")
    assert cond, f"{name} {detail}"


def make_rows(n=120, drift=0.001, seed=1, start_close=100.0):
    """Synthetic daily closes."""
    rng = np.random.default_rng(seed)
    closes = [start_close]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + drift + rng.normal(0, 0.02)))
    import time

    base = 1700000000
    rows = []
    for i, c in enumerate(closes):
        rows.append({"date": time.strftime("%Y-%m-%d", time.gmtime(base + i * 86400)), "close": float(c)})
    return rows


def test_signal():
    print("\n[T1] сигнал close vs SMA50")
    rows = make_rows(120, drift=0.005)  # растущий рынок
    sig = t2.compute_signal(rows)
    check("длинный тренд -> LONG", sig["signal"] == "LONG", str(sig))
    rows2 = make_rows(120, drift=-0.005)
    sig2 = t2.compute_signal(rows2)
    check("падающий тренд -> CASH", sig2["signal"] == "CASH", str(sig2))
    # мало истории
    rows3 = make_rows(30)
    sig3 = t2.compute_signal(rows3)
    check("мало истории -> CASH (reason)", sig3["signal"] == "CASH" and sig3.get("sma_in") is None)


def test_fetch_fallback():
    print("\n[T2] fetch_closes: Yahoo + фолбэк Binance")
    n = 120

    def transport(url, timeout=25):
        if "binance" in url:
            # Binance primary теперь: вернём klines-формат
            return json.dumps(
                [
                    [1700000000 * 1000 + i * 86400 * 1000, "0", "0", "0", str(100.0 + i), "0", 0, "0", 0, "0", "0", "0"]
                    for i in range(n)
                ]
            ).encode()
        raise AssertionError("no yahoo needed")

    rows = t2.fetch_closes(transport, "BTC-USD")
    check("Binance primary работает", len(rows) == n and rows[-1]["close"] == 100.0 + n - 1)

    # Binance падает -> Yahoo; проверим, что URL учитывает символ (ETHUSDT / ETH-USD)
    yahoo_payload2 = {
        "chart": {
            "result": [
                {
                    "timestamp": [1700000000 + i * 86400 for i in range(n)],
                    "indicators": {"quote": [{"close": [200.0 + i for i in range(n)]}]},
                }
            ]
        }
    }

    seen_urls = []

    def transport2(url, timeout=25):
        seen_urls.append(url)
        if "binance" in url:
            raise RuntimeError("binance down")
        return json.dumps(yahoo_payload2).encode()

    rows2 = t2.fetch_closes(transport2, "ETH-USD")
    check("фолбэк Yahoo", len(rows2) == n and rows2[-1]["close"] == 200.0 + n - 1)
    check("URL использует символ (ETHUSDT)", any("ETHUSDT" in u for u in seen_urls), str(seen_urls))
    check("Yahoo URL использует ETH-USD", any("ETH-USD" in u for u in seen_urls))

    # оба падают -> исключение
    def transport3(url, timeout=25):
        raise RuntimeError("all down")

    try:
        t2.fetch_closes(transport3)
        check("исключение при обоих сбоях", False)
    except RuntimeError:
        check("исключение при обоих сбоях", True)


def test_daily_idempotent():
    print("\n[T3] идемпотентность (повторный запуск не дублирует)")
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        log = Path(tmp) / "log.jsonl"
        rows = make_rows(120, drift=0.005)
        r1 = t2.run_daily(state, log, rows)
        check("первый запуск ok", r1["status"] == "ok")
        n1 = len(log.read_text().splitlines())
        r2 = t2.run_daily(state, log, rows)
        check("повторный — already_processed", r2["status"] == "already_processed")
        n2 = len(log.read_text().splitlines())
        check("лог не задвоился", n1 == n2 == 1, f"{n1} vs {n2}")


def test_position_change_costs():
    print("\n[T4] смена позиции: издержки и трейды")
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        log = Path(tmp) / "log.jsonl"
        # растущий рынок: первый запуск войдёт в LONG
        rows_up = make_rows(120, drift=0.005)
        r1 = t2.run_daily(state, log, rows_up)
        check("вход в LONG", r1["position"] == "LONG")
        st = json.loads(state.read_text())
        check("издержки 0.15% применены (вход)", abs(st["equity"] - 10000 * 0.9985) < 1e-6, f"equity {st['equity']}")
        check("трейд записан", len(st["trades"]) == 1)
        check("entry_price = close", st["entry_price"] == rows_up[-1]["close"])
        # теперь падающий рынок: новые данные -> выход в CASH.
        # последний день делаем плоским (close == prev), чтобы изолировать издержки
        rows_down = rows_up[:-1] + make_rows(60, drift=-0.01, start_close=rows_up[-1]["close"] * 0.95)
        rows_down[-1] = dict(rows_down[-2])
        eq_before_exit = json.loads(state.read_text())["equity"]
        r2 = t2.run_daily(state, log, rows_down)
        check("выход в CASH", r2["position"] == "CASH")
        st = json.loads(state.read_text())
        check(
            "издержки 0.15% при выходе",
            abs(st["equity"] - eq_before_exit * 0.9985) < 1e-6,
            f"{st['equity']} vs {eq_before_exit * 0.9985}",
        )
        check("2 трейда", len(st["trades"]) == 2)
        check("exit: entry_price None", st["entry_price"] is None)
        check("equity > 0 (сохранена)", st["equity"] > 0)


def test_equity_marking():
    print("\n[T5] equity: close/close в позиции")
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        log = Path(tmp) / "log.jsonl"
        # входим в LONG
        rows_up = make_rows(120, drift=0.005)
        t2.run_daily(state, log, rows_up)
        st0 = json.loads(state.read_text())
        eq0 = st0["equity"]
        # следующий день: цена +1% -> equity должна вырасти на 1%
        last = rows_up[-1]
        nxt = {"date": "2099-01-01", "close": last["close"] * 1.01}
        rows2 = [*rows_up, nxt]
        t2.run_daily(state, log, rows2)
        st = json.loads(state.read_text())
        check("equity *1.01 в позиции", abs(st["equity"] - eq0 * 1.01) < 1e-6, f"{st['equity']} vs {eq0 * 1.01}")


def test_bh_reference():
    print("\n[T6] buy&hold эталон (cash_equiv)")
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        log = Path(tmp) / "log.jsonl"
        rows = make_rows(120, drift=0.005)
        t2.run_daily(state, log, rows)
        st = json.loads(state.read_text())
        exp_bh = 10000.0 * rows[-1]["close"] / rows[-2]["close"]
        check(
            "cash_equiv = close[-1]/close[-2]", abs(st["cash_equiv"] - exp_bh) < 1e-6, f"{st['cash_equiv']} vs {exp_bh}"
        )
        # повторный запуск того же дня не меняет cash_equiv (идемпотентность)
        t2.run_daily(state, log, rows)
        st2 = json.loads(state.read_text())
        check("идемпотентность BH", abs(st2["cash_equiv"] - st["cash_equiv"]) < 1e-9)


def test_price_discrepancy():
    print("\n[U4] сверка цен Yahoo vs Binance")
    rows = [{"date": "2026-01-01", "close": 100.0}]

    def transport(url, timeout=25):
        if "ticker/price" in url:
            return json.dumps({"price": "100.2"}).encode()  # 0.2% - ок
        raise AssertionError(url)

    check("расхождение <0.5% -> None", t2.check_price_discrepancy(rows, transport) is None)

    def transport2(url, timeout=25):
        if "ticker/price" in url:
            return json.dumps({"price": "101.5"}).encode()  # 1.5% - предупреждение
        raise AssertionError(url)

    warn = t2.check_price_discrepancy(rows, transport2)
    check("расхождение >0.5% -> предупреждение", warn is not None and "⚠️" in warn)

    def transport3(url, timeout=25):
        raise RuntimeError("down")

    check("сбой API -> None (без падения)", t2.check_price_discrepancy(rows, transport3) is None)


def test_symbol_state_paths():
    print("\n[T8] дефолтные state/log пути по символу")
    # проверим через main-подобную логику: вызываем run_daily с явными путями
    # и убеждаемся, что per-symbol файлы не пересекаются
    with tempfile.TemporaryDirectory() as tmp:
        s_btc = Path(tmp) / "state_btc.json"
        l_btc = Path(tmp) / "log_btc.jsonl"
        s_eth = Path(tmp) / "state_eth.json"
        l_eth = Path(tmp) / "log_eth.jsonl"
        rows = make_rows(120, drift=0.005)
        t2.run_daily(s_btc, l_btc, rows)
        t2.run_daily(s_eth, l_eth, rows)
        check("state BTC создан", s_btc.exists())
        check("state ETH создан", s_eth.exists())
        # лог ETH пустой (только 1 запись для BTC? нет - оба пишут по 1 записи)
        check("логи независимы", l_btc.exists() and l_eth.exists())


def test_hysteresis_signal():
    print("\n[U5] гистерезис: вход SMA50, выход SMA40")
    # растущий рынок -> LONG (вход по 50)
    rows = make_rows(120, drift=0.005)
    sig = t2.compute_signal(rows, in_w=50, out_w=40)
    check("растущий -> LONG", sig["signal"] == "LONG", str(sig))
    check("sma_in/sma_out есть", sig["sma_in"] > 0 and sig["sma_out"] > 0)
    # падающий -> CASH
    rows2 = make_rows(120, drift=-0.005)
    sig2 = t2.compute_signal(rows2, in_w=50, out_w=40)
    check("падающий -> CASH", sig2["signal"] == "CASH")
    # run_daily с variant
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "s.json"
        log = Path(tmp) / "l.jsonl"
        r = t2.run_daily(state, log, rows, variant={"in_w": 50, "out_w": 40})
        check("run_daily с variant ok", r["status"] == "ok" and r["position"] == "LONG")


def test_log_format():
    print("\n[T7] формат лога")
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        log = Path(tmp) / "log.jsonl"
        rows = make_rows(120, drift=0.005)
        t2.run_daily(state, log, rows)
        entry = json.loads(log.read_text().splitlines()[0])
        for k in ("date", "close", "sma50", "signal", "position", "equity", "bh_equity"):
            check(f"поле {k}", k in entry)
