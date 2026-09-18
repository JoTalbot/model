#!/usr/bin/env python3
"""Parse freqtrade backtest result zips into a summary table."""

import glob
import json
import sys
import time
import zipfile

for d in sys.argv[1:]:
    zips = sorted(glob.glob(d + "/*.zip"))
    print(f"zips: {len(zips)} in {d}")
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
                jname = [n for n in names if n.endswith(".json") and "config" not in n][0]  # noqa: RUF015
                cname = [n for n in names if "config" in n][0]  # noqa: RUF015
                data = json.loads(zf.read(jname))
                cfg = json.loads(zf.read(cname))
                st = data["strategy"]
                strat_name = list(st.keys())[0]  # noqa: RUF015
                st = st[strat_name]
                pair = cfg["exchange"]["pair_whitelist"][0]
                tr = st.get("timerange", "?")
                ts = time.strftime("%H:%M", time.gmtime(st["backtest_start_ts"]))
                p = st["profit_total"] * 100
                dd = st["max_drawdown_account"] * 100
                sharpe = st.get("sharpe")
                sortino = st.get("sortino")
                line = (
                    f"{ts} | {pair:10s} | {strat_name:16s} | {tr} | "
                    f"profit={p:8.1f}% dd={dd:5.1f} "
                    f"sh={sharpe if sharpe is not None else -1:.2f} "
                    f"so={sortino if sortino is not None else -1:.2f} "
                    f"tr={st['total_trades']}"
                )
                print(line)
        except Exception as e:
            print(z.split("/")[-1], "ERR", str(e)[:100])
