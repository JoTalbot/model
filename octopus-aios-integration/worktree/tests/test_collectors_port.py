"""Wave 5c: collectors + quant engines (stdlib/network-free paths)."""

import importlib.util
import json
import sqlite3
import time

import pytest

from scripts.aios.collectors import collect_news_sentiment as news
from scripts.aios.collectors import collect_orderbook_snapshots as snaps
from scripts.aios.collectors import prune_orderbook_ws as prune
from scripts.aios.collectors import run_market_digest as digest
from swarm.quant import crypto_news_sentiment as cns
from swarm.quant import data_collector as dc
from swarm.quant import derivatives_orderbook_engine as doe
from swarm.quant import orderbook_analyzer as oba

try:
    from scripts.aios.collectors import collect_orderbook_ws as ws
except ImportError:
    ws = None

HAS_CCXT = importlib.util.find_spec("ccxt") is not None
needs_ws = pytest.mark.skipif(ws is None, reason="needs websockets")


def _book():
    return {
        "timestamp": 1700000000000,
        "bids": [[100.0, 1.0], [99.5, 2.0]],
        "asks": [[100.5, 1.5], [101.0, 2.0]],
    }


def test_normalize_valid_book():
    row = snaps.normalize("binance", "BTC", _book(), 12.5, depth=10)
    assert row["bid"] == 100.0 and row["ask"] == 100.5
    assert row["mid"] == pytest.approx(100.25)
    assert row["spread_bps"] == pytest.approx(0.5 / 100.25 * 10000)
    assert row["bid_depth_usd"] == pytest.approx(100.0 * 1.0 + 99.5 * 2.0)
    assert row["latency_ms"] == 12.5


def test_normalize_rejects_crossed_and_empty():
    assert snaps.normalize("x", "BTC", {"bids": [[101, 1]], "asks": [[100, 1]]}, 1.0) is None
    assert snaps.normalize("x", "BTC", {"bids": [], "asks": []}, 1.0) is None


def test_orderbook_store_add_and_prune(tmp_path):
    store = snaps.OrderbookStore(tmp_path / "ob.sqlite")
    row = snaps.normalize("binance", "BTC", _book(), 1.0)
    row["ts"] = time.time()
    old = dict(row)
    old["ts"] = time.time() - 20 * 86400
    store.add(row)
    store.add(old)
    store.prune(retention_days=14)
    n = store.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    store.close()
    assert n == 1


def test_build_clients_no_ccxt_contract():
    if HAS_CCXT:
        clients = snaps.build_clients(["binance"])
        assert "binance" in clients
    else:
        with pytest.raises(RuntimeError, match="ccxt is not installed"):
            snaps.build_clients(["binance"])


@needs_ws
def test_ws_depth_msg_parsing():
    snap = ws.depth_msg_to_snapshot({"bids": [["100", "1"]], "asks": [["101", "2"]]}, 1700000000000.0, 5.0)
    assert snap["mid"] == pytest.approx(100.5)
    assert snap["latency_ms"] == 5.0
    assert ws.depth_msg_to_snapshot({"bids": [], "asks": []}, 0.0) is None
    assert ws.depth_msg_to_snapshot({"bids": [["102", "1"]], "asks": [["101", "1"]]}, 0.0) is None


@needs_ws
def test_ws_latency_and_store(tmp_path):
    assert ws.snapshot_latency({"latency_ms": 42.0, "last_trade_seen_ts": time.time()}, time.time()) == 42.0
    assert ws.snapshot_latency({"latency_ms": 42.0, "last_trade_seen_ts": 0.0}, time.time()) == 0.0
    store = ws.WSStore(tmp_path / "w.sqlite")
    store.add_batch([(1.0, "src", "BTC", 100.0, 101.0, 100.5, 99.0, 1.0, 2.0, "[]", "[]", 5.0)])
    n = store.db.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0]
    store.db.close()
    assert n == 1


def _ws_db(path, now):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE snapshots_ws (ts REAL, symbol TEXT, bid REAL, ask REAL)")
    con.execute("CREATE TABLE trades_ws (ts REAL, symbol TEXT)")
    # raw window: 3 rows; middle window: 3 rows in ONE minute bucket
    # (bucket grid is relative to keep_cut, so align to it); tail: 1 row
    for ts in (now - 3600, now - 3590, now - 3580):
        con.execute("INSERT INTO snapshots_ws VALUES (?,?,?,?)", (ts, "BTC", 1, 2))
    mid = (now - 60 * 86400) + 10 * 86400 + 30
    for ts in (mid, mid + 5, mid + 10):
        con.execute("INSERT INTO snapshots_ws VALUES (?,?,?,?)", (ts, "BTC", 1, 2))
    con.execute("INSERT INTO snapshots_ws VALUES (?,?,?,?)", (now - 70 * 86400, "BTC", 1, 2))
    con.execute("INSERT INTO trades_ws VALUES (?,?)", (now - 70 * 86400, "BTC"))
    con.execute("INSERT INTO trades_ws VALUES (?,?)", (now - 3600, "BTC"))
    con.commit()
    con.close()


def test_prune_windows_and_dry_run(tmp_path, monkeypatch):
    now = 1750000000.0
    monkeypatch.setattr(prune.time, "time", lambda: now)
    db = tmp_path / "p.sqlite"
    _ws_db(db, now)
    stats = prune.prune(db, 7, 60, dry_run=True)
    assert stats["snapshots_ws_downsampled"] == 2  # 3 mid rows -> 1 kept
    assert stats["snapshots_ws_deleted_tail"] == 1
    assert stats["trades_ws_deleted_tail"] == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0] == 7
    con.close()
    prune.prune(db, 7, 60)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM trades_ws").fetchone()[0] == 1
    con.close()
    with pytest.raises(SystemExit):
        prune.prune(db, 60, 7)


def test_detect_coins():
    found = news.detect_coins("Solana ETF approval, BTC rally")
    assert "BTC" in found and found == sorted(found)


class _FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_score_batch_parses_gemini(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": '[{"sentiment": 0.5, "coins": ["BTC"]}]'}]}}]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp(payload))
    out = news.score_batch([{"provider": "gemini", "key": "k"}], ["BTC rallies"])
    assert out == [{"sentiment": 0.5, "coins": ["BTC"]}]


def test_market_digest_empty_and_trend(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DB", tmp_path / "olx.sqlite")
    monkeypatch.setattr(digest, "SNAPS", tmp_path / "snaps.json")
    assert digest.snapshot() == {}
    digest.save()
    assert digest.trend_lines() == []
    con = sqlite3.connect(tmp_path / "olx.sqlite")
    con.execute("CREATE TABLE ads (query TEXT, price_value REAL, active INT)")
    con.execute("INSERT INTO ads VALUES ('фара', 1000, 1)")
    con.execute("INSERT INTO ads VALUES ('фара', 3000, 1)")
    con.commit()
    con.close()
    snap = digest.snapshot()
    assert snap["фара"]["median"] == 2000 and snap["фара"]["n"] == 2


def test_data_collector_contract(tmp_path):
    assert "binance" in dc.EXCHANGE_IDS
    assert str(dc.QUANT_DIR).endswith("quant")
    if HAS_CCXT:
        c = dc.MarketDataCollector(symbols=["BTC"], exchanges=["binance"], quant_dir=tmp_path / "q")
        assert "binance" in c._clients
    else:
        with pytest.raises(RuntimeError, match="ccxt is not installed"):
            dc.MarketDataCollector(symbols=["BTC"], exchanges=["binance"], quant_dir=tmp_path / "q")
        # storage paths work without ccxt
        c = dc.MarketDataCollector.__new__(dc.MarketDataCollector)
        c.quant_dir = tmp_path / "q2"
        c.export_dir = c.quant_dir / "export"
        c.export_dir.mkdir(parents=True)
        (c.quant_dir / "BTC").mkdir(parents=True)
        (c.quant_dir / "BTC" / "x.csv").write_text("a,b\n")
        assert c.export_for_colab().endswith("latest.tar.gz")


def test_orderbook_analyzer_symbol_and_fallback(monkeypatch):
    assert oba.AIOSOrderbookAnalyzer._clean_symbol("KRAKEN_BTCUSDT") == "BTC"

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    oba._ORDERBOOK_CACHE.clear()
    res = oba.AIOSOrderbookAnalyzer.analyze_orderbook("ETH")
    assert res["status"] == "BALANCED" and res["bid_ask_imbalance_ratio"] == 1.0


def test_crypto_sentiment_fallback(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    res = cns.AIOSCryptoNewsSentiment.analyze_market_sentiment()
    assert res["headlines_analyzed"] == 3 and "verdict" in res


def test_derivatives_engine_math_and_fallback(monkeypatch):
    liq = doe.AIOSDerivativesEngine.detect_liquidation_clusters("BTC", 100000.0)
    assert liq["long_liquidation_clusters"]["100x_level"] == pytest.approx(99000.0)
    assert liq["short_liquidation_clusters"]["25x_level"] == pytest.approx(104000.0)

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert doe.AIOSDerivativesEngine.scan_futures_open_interest("BTC")["status"] == "UNKNOWN"


def test_market_data_runner_imports():
    import scripts.aios.collectors.run_market_data_collector as r

    assert r.DEFAULT_SYMBOLS and "BTC" in r.DEFAULT_SYMBOLS
