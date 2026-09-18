"""Wave 5c: backfill pagination (ccxt-free paths)."""

from swarm.quant.data_collector import MarketDataCollector


def test_paginated_fetch_deduplicates_and_excludes_open_candle(monkeypatch):
    timeframe_ms = 3_600_000
    now_ms = 5_000 * timeframe_ms
    rows = [[i * timeframe_ms, 1, 2, 0.5, 1.5, 10] for i in range(2_000, 5_001)]

    class Client:
        def parse_timeframe(self, _timeframe):
            return 3600

        def fetch_ohlcv(self, _pair, *, timeframe, since=None, limit=500):
            selected = [row for row in rows if since is None or row[0] >= since]
            return selected[:limit]

    collector = MarketDataCollector.__new__(MarketDataCollector)
    collector._clients = {"fake": Client()}
    monkeypatch.setattr("swarm.quant.data_collector.time.time", lambda: now_ms / 1000)

    result = collector._fetch_ohlcv("fake", "BTC/USD", "1h", limit=2500)

    assert len(result) == 2500
    assert len({row[0] for row in result}) == 2500
    assert max(row[0] for row in result) < now_ms


def test_save_csv_merges_short_refresh_without_losing_history(tmp_path):
    import csv

    path = tmp_path / "BTC_1h.csv"
    header = ["timestamp_ms", "open", "high", "low", "close", "volume", "collected_at"]
    collector = MarketDataCollector.__new__(MarketDataCollector)
    collector._save_csv(path, [[i, 1, 2, 0.5, 1.5, 10, "old"] for i in range(1000)], header)
    collector._save_csv(path, [[i, 1, 2, 0.5, 2.0, 10, "new"] for i in range(900, 1100)], header)
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1100
    assert rows[-1]["timestamp_ms"] == "1099"
    assert rows[900]["close"] == "2.0"
