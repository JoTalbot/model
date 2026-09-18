"""Wave 5b: T2 paper loop + executor + portfolio (stdlib only)."""

import json
import time

import pytest

from scripts.aios.freqtrade import run_t2_executor as ex
from scripts.aios.freqtrade import run_t2_momentum as t2
from scripts.aios.freqtrade import t2_portfolio as tp


def _rows(closes, base=1700000000):
    return [
        {"date": time.strftime("%Y-%m-%d", time.gmtime(base + i * 86400)), "close": float(c)}
        for i, c in enumerate(closes)
    ]


def _trend(n=120, start=100.0, step=1.005):
    closes, c = [], start
    for _ in range(n):
        closes.append(c)
        c *= step
    return _rows(closes)


def test_sma_basic_and_short():
    assert t2.sma([1.0] * 60, 50) == pytest.approx(1.0)
    assert t2.sma([1.0] * 10, 50) is None


def test_compute_signal_trend_and_short_history():
    assert t2.compute_signal(_trend(120, step=1.005))["signal"] == "LONG"
    assert t2.compute_signal(_trend(120, step=0.995))["signal"] == "CASH"
    short = t2.compute_signal(_trend(30))
    assert short["signal"] == "CASH" and short["reason"] == "not_enough_history"


def test_run_daily_transition_applies_cost_and_logs(tmp_path):
    state, log = tmp_path / "s.json", tmp_path / "l.jsonl"
    res = t2.run_daily(state, log, _trend(120, step=1.005))
    assert res["status"] == "ok" and res["position"] == "LONG"
    assert res["equity"] == pytest.approx(10000.0 * (1 - t2.COST))
    st = json.loads(state.read_text())
    assert len(st["trades"]) == 1 and st["trades"][0]["to"] == "LONG"
    entry = json.loads(log.read_text().splitlines()[0])
    assert {"date", "close", "sma50", "signal", "position", "equity", "bh_equity"} <= set(entry)


def test_run_daily_idempotent(tmp_path):
    state, log = tmp_path / "s.json", tmp_path / "l.jsonl"
    rows = _trend(120, step=1.005)
    t2.run_daily(state, log, rows)
    res = t2.run_daily(state, log, rows)
    assert res["status"] == "already_processed"
    assert len(log.read_text().splitlines()) == 1


def test_run_daily_exit_and_hysteresis(tmp_path):
    state, log = tmp_path / "s.json", tmp_path / "l.jsonl"
    # enter LONG first (rising market, small windows)
    rows = _rows([100.0 + i * 0.5 for i in range(10)])
    r1 = t2.run_daily(state, log, rows, variant={"in_w": 5, "out_w": 3})
    assert r1["position"] == "LONG"
    # dip below sma_in(5) but above sma_out(3) -> stays LONG (hysteresis)
    rows2 = _rows([100, 100, 100, 100, 100, 100, 100, 100, 96, 98.5])
    rows2[-1]["date"] = "2030-01-02"
    r2 = t2.run_daily(state, log, rows2, variant={"in_w": 5, "out_w": 3})
    assert r2["position"] == "LONG"
    # deep fall -> exit to CASH with cost
    rows3 = _rows([100, 100, 100, 100, 100, 100, 100, 100, 90, 85])
    rows3[-1]["date"] = "2030-01-03"
    r3 = t2.run_daily(state, log, rows3, variant={"in_w": 5, "out_w": 3})
    assert r3["position"] == "CASH"
    st = json.loads(state.read_text())
    assert [tr["to"] for tr in st["trades"]] == ["LONG", "CASH"]


def test_run_daily_entry_filter_denies(tmp_path):
    state, log = tmp_path / "s.json", tmp_path / "l.jsonl"
    res = t2.run_daily(state, log, _trend(120, step=1.005), entry_filter=lambda _sym: False)
    assert res["signal"] == "CASH" and res["position"] == "CASH"


def _binance_klines(n=120, start=100.0):
    return json.dumps(
        [
            [1700000000 * 1000 + i * 86400000, "0", "0", "0", str(start + i), "0", 0, "0", 0, "0", "0", "0"]
            for i in range(n)
        ]
    ).encode()


def _yahoo_payload(n=120, start=200.0):
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1700000000 + i * 86400 for i in range(n)],
                        "indicators": {"quote": [{"close": [start + i for i in range(n)]}]},
                    }
                ]
            }
        }
    ).encode()


def test_fetch_closes_binance_primary_and_yahoo_fallback():
    rows = t2.fetch_closes(lambda _u: _binance_klines(), "BTC-USD")
    assert len(rows) == 120 and rows[-1]["close"] == pytest.approx(219.0)

    def flaky(url):
        if "binance" in url:
            raise RuntimeError("binance down")
        return _yahoo_payload()

    rows2 = t2.fetch_closes(flaky, "ETH-USD")
    assert len(rows2) == 120 and rows2[0]["close"] == pytest.approx(200.0)


def test_price_discrepancy_none_on_transport_error():
    rows = _trend(120)
    assert t2.check_price_discrepancy(rows, transport=lambda _u: b"{}") is None
    assert t2.check_price_discrepancy([]) is None


def test_executor_signal_and_state(tmp_path):
    sig, s_in, s_out = ex.compute_signal(_trend(120, step=1.005), 50, 40)
    assert sig == "LONG" and s_in > 0 and s_out > 0
    assert ex.compute_signal(_trend(10), 50, 40)[0] == "CASH"
    st = ex.State(tmp_path / "ex.json")
    assert st.data["positions"] == {}
    st.data["positions"]["BTC/USDT"] = "LONG"
    st.save()
    assert ex.State(tmp_path / "ex.json").data["positions"]["BTC/USDT"] == "LONG"


def test_executor_fetch_closes_fake_transport():
    rows = ex.fetch_closes("BTC/USDT", transport=lambda _u: _binance_klines(70))
    assert len(rows) == 70
    with pytest.raises(RuntimeError):
        ex.fetch_closes("BTC/USDT", transport=lambda _u: b"[]")


def test_t2_state_roundtrip(tmp_path):
    p = tmp_path / "st.json"
    st = t2.T2State(p)
    assert st.data["position"] == "CASH" and st.data["equity"] == 10000.0
    st.data["position"] = "LONG"
    st.save()
    assert t2.T2State(p).data["position"] == "LONG"


def test_daily_report_format(tmp_path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"position": "LONG", "equity": 11000.0, "cash_equiv": 10500.0}))
    rep = t2.daily_report("BTC-USD", p)
    assert "T2-BTCUSD" in rep and "LONG" in rep and "+10.0%" in rep


def test_portfolio_defaults_and_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "DATA", tmp_path)
    monkeypatch.setattr(tp, "OUT", tmp_path / "pf.jsonl")
    assert tp.main() == 0
    entry = json.loads((tmp_path / "pf.jsonl").read_text().splitlines()[0])
    assert entry["portfolio"] == pytest.approx(10000.0)
    assert entry["btc"] == pytest.approx(10000.0)
    (tmp_path / "t2_paper_state.json").write_text(json.dumps({"equity": 12000.0, "cash_equiv": 11000.0}))
    assert tp.main() == 0
    entry2 = json.loads((tmp_path / "pf.jsonl").read_text().splitlines()[1])
    assert entry2["btc"] == pytest.approx(12000.0)
    assert entry2["portfolio"] > 10000.0
