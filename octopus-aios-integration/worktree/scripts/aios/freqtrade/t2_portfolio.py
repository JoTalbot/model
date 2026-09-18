#!/usr/bin/env python3
"""T2 portfolio 50/50 (BTC+ETH): daily mark-to-market of the two paper loops.

Reads the per-symbol state files and produces a combined equity view:
  portfolio_equity = 0.5 * equity_btc + 0.5 * equity_eth (on $10k each).
Appends to data/t2_portfolio_equity.jsonl for charting in the weekly digest.

Usage:
    python t2_portfolio.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_T2_DATA") or os.environ.get("OCTOPUS_DATA") or (ROOT / "data"))
OUT = DATA / "t2_portfolio_equity.jsonl"


def load_state(name: str) -> dict:
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else {}


def main() -> int:
    import time

    names = [
        ("BTC", "t2_paper_state.json"),
        ("ETH", "t2_paper_state_ethusd.json"),
        ("SOL", "t2_paper_state_solusd.json"),
        ("BNB", "t2_paper_state_bnbusd.json"),
        ("NEAR", "t2_paper_state_nearusd.json"),
    ]
    eqs, bhs = {}, {}
    for tag, fname in names:
        st = load_state(fname)
        eqs[tag] = float(st.get("equity", 10000.0))
        bhs[tag] = float(st.get("cash_equiv", 10000.0))
    # Riskfolio-оптимизированные веса (Max Sharpe, обучены на 7-летних T2-кривых)
    OPT_WEIGHTS = {"BTC": 0.403, "ETH": 0.058, "SOL": 0.282, "BNB": 0.134, "NEAR": 0.123}
    port = sum(eqs[tag] * OPT_WEIGHTS.get(tag, 1 / len(names)) for tag in eqs)
    port_bh = sum(bhs[tag] * OPT_WEIGHTS.get(tag, 1 / len(names)) for tag in bhs)
    date = time.strftime("%Y-%m-%d")
    entry = {
        "date": date,
        "portfolio": round(port, 2),
        "bh": round(port_bh, 2),
        **{tag.lower(): round(v, 2) for tag, v in eqs.items()},
    }
    with open(OUT, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
