#!/usr/bin/env python3
"""Monthly strategy scoreboard: automated "who wins" backtest verdict.

Runs the two read-only harnesses with the deployed parameters and appends one
row per month to data/reports/strategy_scoreboard.jsonl, plus a cumulative
markdown table. Owner decision 2026-08-17 ("как лучше"): instead of adding
M2 to the paper loop (OOS -46%/2y fails the honest gate), the strategy test
now repeats automatically every month.

Verdict rules (mechanical, documented):
  - winner = momentum variant ONLY if month PnL > top-10 basket AND OOS CAGR > 0;
  - else winner = top-10 basket if it beats every active strategy and is > 0;
  - else winner = Directional v2 if its PnL >= all momentum month PnLs;
  - otherwise best month performer flagged "unstable (OOS<0)".

Usage:
    python scripts/quant_strategy_scoreboard.py [--skip-run] [--repo-root .]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# DCA paper basket (top-10 majors, equal weight) — same set as data/dca_portfolio.json
TOP10 = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "TRX", "TON", "ADA", "LINK"]

SCOREBOARD_JSONL = REPO_ROOT / "data" / "reports" / "strategy_scoreboard.jsonl"
SCOREBOARD_MD = REPO_ROOT / "data" / "reports" / "strategy_scoreboard.md"


# ---------------------------------------------------------------- pure parts --
def parse_momentum_md(text: str) -> list[dict]:
    """Parse the momentum MD table into rows (variant, month PnL, OOS CAGR)."""

    rows: list[dict] = []
    # столбцы: имя | total PnL | CAGR | MaxDD | Sharpe | сделок | OOS CAGR | last30 PnL | last30 DD
    for line in text.splitlines():
        m = re.match(
            r"\|\s*([MT][0-9C]):[^|]+\|\s*([+-][\d.]+)\s*\|\s*([+-][\d.]+)\s*\|\s*"
            r"([+-][\d.]+)\s*\|\s*([+-][\d.]+)\s*\|\s*(\d+)\s*\|\s*([+-][\d.]+)\s*\|\s*"
            r"([+-][\d.]+)\s*\|",
            line,
        )
        if not m:
            continue
        rows.append({
            "name": m.group(1),
            "month_pnl_pct": float(m.group(8)),   # last30d PnL
            "n_trades": int(m.group(6)),
            "oos_cagr_pct": float(m.group(7)),    # OOS CAGR
        })
    return rows


def top_basket_pnl(buy_hold: dict, assets: list[str],
                  min_present: int = 8) -> tuple:
    """Equal-weight buy&hold PnL of the top-10 basket for the month.

    Returns (pnl, n_present). Missing symbols (e.g. TON delisted from the
    binance proxy) are skipped; requires at least min_present of the basket
    to stay representative, otherwise (None, n_present).
    """

    per = buy_hold.get("per_symbol_pct") or {}
    present = [float(per[s]) for s in assets if s in per]
    if len(present) < min_present:
        return None, len(present)
    return round(sum(present) / len(present), 3), len(present)


def verdict(dv2_pnl: float, basket_pnl: float | None,
            momentum: list[dict]) -> dict:
    """Mechanical winner selection (documented rules)."""

    best_mom = max(momentum, key=lambda r: r["month_pnl_pct"]) if momentum else None
    result: dict[str, object] = {}
    if best_mom is not None:
        result["best_momentum"] = {
            "name": best_mom["name"],
            "month_pnl_pct": best_mom["month_pnl_pct"],
            "oos_cagr_pct": best_mom["oos_cagr_pct"],
        }
        if (basket_pnl is not None
                and best_mom["month_pnl_pct"] > basket_pnl
                and best_mom["oos_cagr_pct"] > 0):
            result["winner"] = best_mom["name"]
            result["reason"] = ("моментум-вариант лучше корзины в месяце И имеет "
                                "положительный OOS CAGR")
            return result
    if basket_pnl is not None:
        active_best = max([dv2_pnl] + [r["month_pnl_pct"] for r in momentum])
        if basket_pnl > active_best and basket_pnl > 0:
            result["winner"] = "top10_basket"
            result["reason"] = (f"пассивная корзина топ-10 ({basket_pnl:+.2f}%) "
                                "лучше всех активных стратегий и положительна")
            return result
    if best_mom is None or dv2_pnl >= best_mom["month_pnl_pct"]:
        result["winner"] = "directional_v2"
        result["reason"] = "Directional v2 сохранил капитал лучше активных аналогов"
        return result
    result["winner"] = best_mom["name"]
    result["reason"] = "лучший в месяце, но OOS отрицателен — неустойчив"
    result["unstable"] = True
    return result


# ------------------------------------------------------------------- runner --
def run_harness(args: argparse.Namespace) -> tuple[dict, list[dict]]:
    """Run both harnesses with deployed parameters; return parsed outputs."""

    monthly_out = REPO_ROOT / "data" / "reports" / "monthly_score_deployed"
    momentum_out = REPO_ROOT / "data" / "reports" / "momentum_score.md"
    monthly_cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "aios" / "research" / "quant_monthly_backtest.py"),
        "--months", "1", "--ml-min-prob", "0.5061", "--trail-ratio", "1.0",
        "--output", str(monthly_out),
    ]
    momentum_cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "aios" / "freqtrade" / "momentum_strategies.py"),
        "--eval-last-days", "30", "--out", str(momentum_out),
    ]
    for cmd in (monthly_cmd, momentum_cmd):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                              cwd=REPO_ROOT)
        if proc.returncode != 0:
            raise RuntimeError(f"harness failed ({cmd[2]}): "
                               f"{(proc.stdout + proc.stderr)[-800:]}")
    monthly_json = json.loads(
        monthly_out.with_suffix(".current_algorithm.json").read_text(encoding="utf-8"))
    momentum_md = momentum_out.read_text(encoding="utf-8")
    return monthly_json, parse_momentum_md(momentum_md)


def load_rows(jsonl: Path) -> list[dict]:
    if not jsonl.exists():
        return []
    rows = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def rebuild_md(rows: list[dict], md_path: Path) -> None:
    lines = [
        "# Scoreboard стратегий (ежемесячный бэктест, развёрнутые параметры)",
        "",
        "| Месяц | Directional v2 | Корзина топ-10 | Рынок (средн.) | Лучший моментум | Победитель |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        bm = (r.get("verdict") or {}).get("best_momentum") or {}
        mom = (f"{bm.get('name')} {bm.get('month_pnl_pct'):+.1f}%"
               if bm else "—")
        basket = r.get("top10_basket_pct")
        basket_str = f"{basket:+.2f}%" if basket is not None else "—"
        v = r.get("verdict") or {}
        winner = v.get("winner") or "—"
        if v.get("unstable"):
            winner += " ⚠️"
        lines.append(
            f"| {r['date']} | {r['dv2']['pnl_pct']:+.2f}% ({r['dv2']['trades']} сд.) "
            f"| {basket_str} | {r['market_mean_pct']:+.2f}% "
            f"| {mom} | {winner} |"
        )
    lines.append("")
    lines.append("Правило вердикта: моментум — только при PnL>корзины И OOS CAGR>0; "
                 "иначе корзина топ-10, если лучше всех активных; иначе Directional v2.")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def append_row(row: dict, jsonl: Path, md_path: Path) -> None:
    """Append the monthly row and regenerate the cumulative table."""

    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    rebuild_md(load_rows(jsonl), md_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-run", action="store_true",
                    help="пересобрать MD из существующего jsonl без прогона")
    args = ap.parse_args()

    if args.skip_run:
        rebuild_md(load_rows(SCOREBOARD_JSONL), SCOREBOARD_MD)
        print(f"scoreboard md rebuilt -> {SCOREBOARD_MD}")
        return 0

    monthly, momentum = run_harness(args)
    dv2 = {
        "pnl_pct": round(float(monthly["portfolio_pnl_pct"]), 3),
        "trades": int(monthly["total_trades"]),
        "win_rate_pct": round(float(monthly["win_rate_pct"]), 2),
    }
    market_mean = round(float((monthly.get("buy_hold") or {}).get("mean_pct", 0.0)), 3)
    basket, basket_n = top_basket_pnl(monthly.get("buy_hold") or {}, TOP10)
    basket_for_verdict = basket if basket is not None else market_mean
    row = {
        "date": datetime.now(UTC).strftime("%Y-%m"),
        "dv2": dv2,
        "market_mean_pct": market_mean,
        "top10_basket_pct": basket,
        "top10_basket_n": basket_n,
        "momentum": momentum,
        "verdict": verdict(dv2["pnl_pct"], basket_for_verdict, momentum),
    }
    append_row(row, SCOREBOARD_JSONL, SCOREBOARD_MD)
    v = row["verdict"]
    print(json.dumps(row, ensure_ascii=False, indent=2))
    print(f"scoreboard -> {SCOREBOARD_JSONL} | winner: {v.get('winner')} "
          f"({v.get('reason')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
