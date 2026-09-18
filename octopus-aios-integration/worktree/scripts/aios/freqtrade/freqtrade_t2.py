# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires freqtrade venv (not installed)
#!/usr/bin/env python3
"""T2 momentum strategy ported to Freqtrade (TA-Lib free).

The validated AIOS T2 strategy (7-year backtest, docs/T2_VALIDATION_AND_EXPANSION):
- LONG while close > SMA(in_w), exit when close <= SMA(out_w)  (hysteresis)
- BNB/NEAR use in_w=out_w=50 (no hysteresis, per production run_t2_momentum.py)
- level-based signals, NOT crossings: freqtrade only evaluates entry signals
  when flat and exit signals when in position, so level conditions reproduce
  the production hysteresis state machine exactly.

IMPORTANT (validation finding 2026-08-16): the first port used crossing
conditions (close.shift(1) <= sma.shift(1) ...). That diverges from production
after hysteresis exits (production re-enters as soon as close > SMA50, the
crossing version waits for a new cross). Fixed to level-based.

IMPORTANT #2: the exit CANNOT be a plain signal column. Freqtrade's
should_exit() ignores the exit signal whenever the entry signal is also set on
the same candle (`exit_ and not enter`). In the zone between SMA50 and SMA40
(when SMA40 > SMA50, i.e. right after a local top), close <= SMA40 AND
close > SMA50 hold simultaneously, so the exit would be blocked and the
position would be kept far longer than production does. The exit is therefore
implemented in custom_exit() (checked every candle while in position,
independent of the entry signal) - reproduces production exactly.

SMA computed with pandas (no TA-Lib C dependency) - identical math to ta.SMA.

Usage (in freqtrade dir):
    freqtrade backtesting --strategy T2Momentum --config configs/config_t2_BTC.json
"""

import pandas as pd
from freqtrade.strategy import IntParameter, IStrategy
from pandas import DataFrame

# Production windows per pair (run_t2_momentum.py / t2_portfolio.py):
# BTC/ETH/SOL -> in=50, out=40 (hysteresis); BNB/NEAR -> 50/50 (single SMA).
PER_PAIR_WINDOWS = {
    "BNB/USDT": (50, 50),
    "NEAR/USDT": (50, 50),
}


class T2Momentum(IStrategy):
    """T2: time-series momentum with SMA in/out hysteresis (daily bars)."""

    INTERFACE_VERSION = 3

    # ---- config (defaults from validation; hyperopt-able) ----
    in_w = IntParameter(30, 100, default=50, space="buy")
    out_w = IntParameter(20, 90, default=40, space="sell")

    # ---- risk ----
    # Страховочный жёсткий стоп −15% (ревизия 2026-08-19): основной выход —
    # SMA-пересечение, а это аварийная защита капитала. Ранее стоял −0.99
    # (интерпретируется freqtrade как −99% → стоп-цена = 1% от входа —
    # недостижимый и вводящий в заблуждение).
    stoploss = -0.15
    trailing_stop = False
    use_custom_stoploss = False

    # ---- execution ----
    timeframe = "1d"
    can_short = False
    startup_candle_count = 200
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # ---- ROI ----
    minimal_roi = {"0": 1000000000}  # ROI disabled; only SMA exit

    def _windows(self, pair: str) -> tuple[int, int]:
        return PER_PAIR_WINDOWS.get(pair, (self.in_w.value, self.out_w.value))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        in_w, out_w = self._windows(metadata["pair"])
        dataframe["sma_in"] = dataframe["close"].rolling(in_w).mean()
        dataframe["sma_out"] = dataframe["close"].rolling(out_w).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # level condition: freqtrade only consults this while flat,
        # so this reproduces production "enter LONG when close > SMA(in)"
        dataframe.loc[
            (dataframe["close"] > dataframe["sma_in"]),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit is handled in custom_exit (see module docstring): the exit signal
        # column would be blocked whenever the entry level also holds.
        return dataframe

    def custom_exit(self, pair: str, trade, current_time, current_rate, current_profit, **kwargs) -> str | None:
        """Production exit: close <= SMA(out_w) on the last CLOSED bar.

        Uses only bars with date < current_time (no lookahead in backtest,
        same semantics in live). The exit is level-based and independent of
        the entry signal - exactly like production run_daily.
        """
        # Production never evaluates the exit rule on the entry bar (state
        # machine: exit checked only while LONG from a previous close). Skip
        # the entry candle here, otherwise a both-zone bar (close between
        # sma_out and sma_in with sma_out > sma_in) would enter AND exit on
        # the same candle.
        if trade.open_date_utc >= current_time:
            return None
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty or "sma_out" not in df.columns:
            return None
        closed = df[df["date"] < current_time]
        if closed.empty:
            return None
        last = closed.iloc[-1]
        sma_out = last.get("sma_out")
        close = last.get("close")
        if pd.isna(sma_out) or pd.isna(close):
            return None
        if close <= sma_out:
            return "t2_sma_out"
        return None
