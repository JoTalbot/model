"""Pure regime features and correlation clustering for Directional v3."""

from __future__ import annotations

import math
import statistics

REGIMES = {"trend_up", "trend_down", "range", "high_volatility", "illiquid"}


def _ema(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    result = []
    current = values[0] if values else 0.0
    for value in values:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def _percentile_rank(history: list[float], value: float) -> float:
    if not history:
        return 0.5
    return sum(item <= value for item in history) / len(history)


def compute_regime_features(
    rows: list[dict[str, float]],
) -> list[dict[str, float | str]]:
    """Compute causal features; each row uses only current/past observations."""

    if not rows:
        return []
    closes = [row["close"] for row in rows]
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    true_ranges = []
    for index, row in enumerate(rows):
        previous = closes[index - 1] if index else row["open"]
        true_ranges.append(
            max(
                row["high"] - row["low"],
                abs(row["high"] - previous),
                abs(row["low"] - previous),
            )
        )
    features = []
    for index, row in enumerate(rows):
        start = max(0, index - 13)
        atr = statistics.mean(true_ranges[start : index + 1])
        atr_pct = atr / row["close"] * 100.0 if row["close"] > 0 else math.inf
        atr_history = [
            statistics.mean(true_ranges[max(0, j - 13) : j + 1]) / closes[j] * 100.0
            for j in range(max(0, index - 99), index + 1)
            if closes[j] > 0
        ]
        volumes = [rows[j]["volume"] for j in range(max(0, index - 99), index + 1)]
        changes = [
            closes[j] - closes[j - 1] for j in range(max(1, index - 13), index + 1)
        ]
        strength = (
            abs(sum(changes)) / sum(abs(change) for change in changes) * 100.0
            if changes and sum(abs(x) for x in changes) > 0
            else 0.0
        )
        slope = (
            (fast[index] - fast[max(0, index - 3)]) / row["close"] * 100.0
            if row["close"] > 0
            else 0.0
        )
        vol_rank = _percentile_rank(atr_history, atr_pct)
        volume_rank = _percentile_rank(volumes, row["volume"])
        range_pct = (
            (row["high"] - row["low"]) / row["close"] * 100.0
            if row["close"] > 0
            else math.inf
        )
        fresh = (
            index == 0
            or 0 < row["timestamp"] - rows[index - 1]["timestamp"] <= 2 * 3_600_000
        )
        if not fresh or row["volume"] <= 0 or range_pct > 8.0 or volume_rank < 0.05:
            regime = "illiquid"
        elif vol_rank >= 0.90:
            regime = "high_volatility"
        elif strength >= 35.0 and slope > 0.02 and fast[index] > slow[index]:
            regime = "trend_up"
        elif strength >= 35.0 and slope < -0.02 and fast[index] < slow[index]:
            regime = "trend_down"
        else:
            regime = "range"
        features.append(
            {
                "regime": regime,
                "ema_fast": fast[index],
                "ema_slow": slow[index],
                "ema_slope_pct": slope,
                "trend_strength": strength,
                "atr_pct": atr_pct,
                "atr_percentile": vol_rank,
                "volume_percentile": volume_rank,
                "range_pct": range_pct,
            }
        )
    return features


def correlation(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size < 3:
        return 0.0
    a, b = left[-size:], right[-size:]
    ma, mb = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    denominator = math.sqrt(
        sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)
    )
    return numerator / denominator if denominator else 0.0


def correlation_clusters(
    series: dict[str, list[float]], threshold: float = 0.75
) -> dict[str, int]:
    """Deterministic union-find clusters from return correlations."""

    names = sorted(series)
    parent = {name: name for name in names}

    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if abs(correlation(series[left], series[right])) >= threshold:
                a, b = find(left), find(right)
                parent[max(a, b)] = min(a, b)
    roots = {
        root: idx for idx, root in enumerate(sorted({find(name) for name in names}))
    }
    return {name: roots[find(name)] for name in names}
