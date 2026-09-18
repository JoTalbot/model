"""Calibration threshold helpers for the Directional-v2 ML entry gate."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

# Sanity band for a deployable q90 threshold. Outside of it the model's
# probability distribution is degenerate and the gate would be meaningless.
CALIBRATION_BAND = (0.40, 0.90)


def calibrated_ml_threshold(path: str) -> float | None:
    """Read q90 threshold from the calibration file; None on any failure.

    No cache on purpose: the file is read a few dozen times per 15-minute
    scan, and this host's filesystem can return identical st_mtime_ns for
    consecutive rewrites, so mtime-based caching would serve stale values.
    """

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return float(data.get("threshold_q90"))
    except (OSError, ValueError, TypeError):
        return None


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile (matches numpy.quantile default)."""

    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def compute_quantiles(prob_up: Sequence[float]) -> dict[str, float]:
    """Quantiles of the model's prob_up distribution (single source of truth)."""

    # NOTE(octopus-wave4): stdlib replacement for np.quantile (no numpy in prod venv).
    vals = sorted(float(v) for v in prob_up)
    if not vals:
        return {"q50": 0.5, "q75": 0.5, "q90": 0.5, "q95": 0.5, "q99": 0.5}
    return {
        "q50": round(_quantile(vals, 0.50), 4),
        "q75": round(_quantile(vals, 0.75), 4),
        "q90": round(_quantile(vals, 0.90), 4),
        "q95": round(_quantile(vals, 0.95), 4),
        "q99": round(_quantile(vals, 0.99), 4),
    }


def threshold_is_sane(threshold: float) -> bool:
    """True when the q90 threshold is inside the deployable band."""

    lo, hi = CALIBRATION_BAND
    return lo <= threshold <= hi
