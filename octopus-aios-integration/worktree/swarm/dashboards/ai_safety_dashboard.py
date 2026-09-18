"""AI Safety Dashboard for Octopus (ported from AIOS v10.14.0).

Safety dashboard: real-time safety metric monitoring,
incident tracking, safety score calculation, trend
visualization, alert management, status reporting,
safety compliance auditing, metric correlation analysis,
incident severity classification, and historical snapshot.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["SafetyDashboard"]


class SafetyDashboard:
    """Real-time safety monitoring dashboard.

    Features:
    - Metric monitoring with alert thresholds
    - Incident tracking and severity classification
    - Safety score calculation (capped at 1.0)
    - Trend analysis and correlation detection
    - Compliance auditing
    - Historical snapshots
    """

    def __init__(self) -> None:
        """Initialize SafetyDashboard."""
        self.metrics: dict[str, float] = {}
        self.incidents: list[dict[str, Any]] = []
        self.safety_score: float = 1.0
        self._metric_history: dict[str, list[float]] = {}
        self._alerts: list[dict[str, Any]] = []
        self._alert_thresholds: dict[str, float] = {
            "harm": 0.3,
            "bias": 0.4,
            "deception": 0.2,
        }
        self._snapshots: list[dict[str, Any]] = []

    def update_metric(self, name: str, value: float) -> None:
        """Update metric (backward-compatible)."""
        self.metrics[name] = value
        self._metric_history.setdefault(name, []).append(value)
        if name in self._alert_thresholds and value > self._alert_thresholds[name]:
            self._alerts.append(
                {
                    "metric": name,
                    "value": value,
                    "threshold": self._alert_thresholds[name],
                }
            )
        self._recalculate_safety_score()

    def add_incident(self, incident: dict[str, Any]) -> None:
        """Add incident with severity classification."""
        severity = incident.get("severity", "medium")
        # Normalize severity
        valid_severities = ["critical", "high", "medium", "low", "info"]
        if severity not in valid_severities:
            severity = "medium"
        incident["severity"] = severity
        incident["timestamp"] = incident.get("timestamp", time.time())
        self.incidents.append(incident)
        self._recalculate_safety_score()

    def _recalculate_safety_score(self) -> None:
        """Recalculate composite safety score (capped at 1.0)."""
        incident_penalty = min(1.0, len(self.incidents) * 0.05)
        # Severity-weighted penalty
        for inc in self.incidents:
            if inc.get("severity") == "critical":
                incident_penalty += 0.03
            elif inc.get("severity") == "high":
                incident_penalty += 0.02
        # Metric penalty: sum of metrics exceeding thresholds
        metric_penalty = 0.0
        for name, threshold in self._alert_thresholds.items():
            value = self.metrics.get(name, 0)
            if value > threshold:
                metric_penalty += (value - threshold) * 0.5
        metric_penalty = min(0.3, metric_penalty)  # Cap metric penalty
        self.safety_score = round(
            max(0.0, min(1.0, 1.0 - incident_penalty - metric_penalty)), 3
        )

    def get_dashboard(self) -> dict[str, Any]:
        """Get dashboard data (backward-compatible)."""
        return {
            "safety_score": round(self.safety_score, 3),
            "metrics": self.metrics,
            "recent_incidents": self.incidents[-5:],
            "status": "healthy"
            if self.safety_score > 0.8
            else ("warning" if self.safety_score > 0.5 else "critical"),
            "active_alerts": len(
                [a for a in self._alerts if a.get("value", 0) > a.get("threshold", 1)]
            ),
            "compliance_status": "compliant"
            if self.safety_score > 0.7
            else "non-compliant",
        }

    def trend_report(self, metric: str, window: int = 10) -> dict[str, Any]:
        """Generate trend report for a metric."""
        history = self._metric_history.get(metric, [])
        if len(history) < 2:
            return {"metric": metric, "trend": "insufficient_data"}
        recent = history[-window:]
        trend = (
            "improving"
            if recent[-1] > recent[0]
            else ("declining" if recent[-1] < recent[0] else "stable")
        )
        return {
            "metric": metric,
            "trend": trend,
            "latest": recent[-1],
            "change": round(recent[-1] - recent[0], 3),
        }

    def add_alert_threshold(self, metric: str, threshold: float) -> None:
        """Add custom alert threshold."""
        self._alert_thresholds[metric] = threshold

    def compliance_audit(self) -> dict[str, Any]:
        """Audit safety compliance across all metrics."""
        violations: list[str] = []
        for name, threshold in self._alert_thresholds.items():
            value = self.metrics.get(name, 0)
            if value > threshold:
                violations.append(f"{name} exceeds threshold ({value} > {threshold})")
        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "metrics_checked": len(self._alert_thresholds),
            "overall_score": self.safety_score,
        }

    def metric_correlation(self, metric_a: str, metric_b: str) -> dict[str, Any]:
        """Compute correlation between two metrics over history."""
        hist_a = self._metric_history.get(metric_a, [])
        hist_b = self._metric_history.get(metric_b, [])
        min_len = min(len(hist_a), len(hist_b))
        if min_len < 3:
            return {"correlation": "insufficient_data"}
        # Simplified Pearson correlation
        a_vals = hist_a[-min_len:]
        b_vals = hist_b[-min_len:]
        mean_a = sum(a_vals) / min_len
        mean_b = sum(b_vals) / min_len
        cov = (
            sum(
                (a - mean_a) * (b - mean_b)
                for a, b in zip(a_vals, b_vals, strict=False)
            )
            / min_len
        )
        std_a = math.sqrt(sum((a - mean_a) ** 2 for a in a_vals) / min_len)
        std_b = math.sqrt(sum((b - mean_b) ** 2 for b in b_vals) / min_len)
        correlation = (
            round(cov / max(1e-10, std_a * std_b), 3)
            if std_a > 0 and std_b > 0
            else 0.0
        )
        return {"metric_a": metric_a, "metric_b": metric_b, "correlation": correlation}

    def snapshot(self) -> dict[str, Any]:
        """Capture current dashboard state as a historical snapshot."""
        snap = {
            "timestamp": time.time(),
            "safety_score": self.safety_score,
            "metrics": dict(self.metrics),
            "incidents_count": len(self.incidents),
            "alerts_count": len(self._alerts),
        }
        self._snapshots.append(snap)
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-100:]
        return snap

    def incident_summary(self) -> dict[str, Any]:
        """Aggregate incident statistics by severity."""
        counts: dict[str, int] = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
        for inc in self.incidents:
            sev = inc.get("severity", "medium")
            counts[sev] = counts.get(sev, 0) + 1
        return {"total_incidents": len(self.incidents), "by_severity": counts}

    def stats(self) -> dict[str, Any]:
        """Return statistics dict."""
        return {
            "metrics": len(self.metrics),
            "incidents": len(self.incidents),
            "alerts": len(self._alerts),
            "safety_score": round(self.safety_score, 3),
            "snapshots": len(self._snapshots),
        }
