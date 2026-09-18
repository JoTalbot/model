# REFERENCE ONLY (Wave 5, item 2): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires freqtrade venv (not installed)
#!/usr/bin/env python3
"""T2 hyperopt variant: window optimization per pair (no per-pair hardcode).

Extends T2Momentum (freqtrade_t2.py) for hyperopt:
- per-pair windows (BNB/NEAR 50/50) are NOT applied - the pair under
  optimization always uses the hyperopt-able in_w/out_w parameters;
- safety: out_w is clamped to in_w (hysteresis makes sense only with out<=in;
  results with out>in would silently flip the hysteresis and are invalid);
- defaults can be overridden via env T2_IN_W / T2_OUT_W for quick backtests
  of the best-found parameters.

NOTE: this file is for hyperopt/validation runs only. The production dry-run
bot uses freqtrade_t2.py (T2Momentum) unchanged.

Usage (per pair, e.g. BTC):
    freqtrade hyperopt --strategy T2MomentumHyper --strategy-path scripts \
        --config data/freqtrade/configs/config_t2_BTC.json \
        --hyperopt-loss SortinoHyperOptLoss --spaces buy sell --epochs 300
"""

import os

from freqtrade_t2 import T2Momentum
from pandas import DataFrame


class T2MomentumHyper(T2Momentum):
    """T2 with hyperopt-able windows, no per-pair override, out<=in clamp."""

    INTERFACE_VERSION = 3

    def __init__(self, config) -> None:
        super().__init__(config)
        # env overrides (validation of best params without editing the file)
        env_in = os.environ.get("T2_IN_W")
        env_out = os.environ.get("T2_OUT_W")
        if env_in:
            self.in_w.value = int(env_in)
        if env_out:
            self.out_w.value = int(env_out)

    def _windows(self, pair: str) -> tuple[int, int]:
        in_w, out_w = self.in_w.value, self.out_w.value
        return in_w, min(out_w, in_w)  # clamp: out <= in

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        in_w, out_w = self._windows(metadata["pair"])
        dataframe["sma_in"] = dataframe["close"].rolling(in_w).mean()
        dataframe["sma_out"] = dataframe["close"].rolling(out_w).mean()
        return dataframe
