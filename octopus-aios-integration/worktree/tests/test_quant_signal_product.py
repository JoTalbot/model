import csv
import json

from scripts.aios.research.generate_quant_signal_product import build_report, markdown


def test_signal_product_is_read_only_and_marks_stale(tmp_path):
    root = tmp_path / "quant"
    p = root / "BTC" / "kraken" / "BTC_1h.csv"
    p.parent.mkdir(parents=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_ms", "open", "high", "low", "close", "volume", "collected_at"])
        for i in range(150):
            w.writerow([i * 3600000, 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100 + i * 0.1, 1000, "x"])
    (root / "ml_signals.json").write_text(json.dumps({"signals": [{"symbol": "BTC", "prob_up": 0.7}]}))
    (root / "rl_signals.json").write_text(json.dumps({"signals": [{"asset": "BTC", "position": 0.8}]}))
    report = build_report(root, root / "ml_signals.json", root / "rl_signals.json", now_ms=150 * 3600000)
    assert report["execution"] == "read_only"
    assert report["trading_entry_mode"] == "freeze"
    assert len(report["signals"]) == 1
    assert "AIOS Quant Signal Monitor" in markdown(report)
