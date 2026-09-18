"""Structured Telegram/LLM latency metrics without message contents or secrets."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from swarm.tgbot.paths import state_path

METRICS_FILE = state_path("telegram_metrics.jsonl")
SUMMARY_FILE = state_path("telegram_metrics_summary.json")
_LOCK = threading.Lock()
_ALLOWED = {
    "event",
    "status",
    "provider",
    "model",
    "gen_sec",
    "send_sec",
    "total_sec",
    "attempts",
    "error_class",
    "timestamp",
    "source",
}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(float(ordered[index]), 3)


def _compact_metrics_file(path: Path) -> None:
    try:
        if path.stat().st_size < int(
            os.environ.get("TELEGRAM_METRICS_COMPACT_BYTES", "5242880")
        ):
            return
        cutoff = (
            time.time()
            - max(1, int(os.environ.get("TELEGRAM_METRICS_RETENTION_DAYS", "30")))
            * 86400
        )
        kept: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if float(row.get("timestamp", 0)) >= cutoff:
                kept.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        kept = kept[-10000:]
        fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        tmp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(kept) + ("\n" if kept else ""))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError:
        return


def record_telegram_event(event: dict, path: Path | None = None) -> None:
    """Append one redacted metric and refresh a compact 24-hour summary."""
    if os.environ.get("TELEGRAM_METRICS_ENABLED", "1").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    target = path or METRICS_FILE
    clean = {key: value for key, value in event.items() if key in _ALLOWED}
    clean.setdefault("timestamp", time.time())
    clean.setdefault("event", "telegram_send")
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
        _compact_metrics_file(target)
        if target == METRICS_FILE:
            _atomic_json(
                SUMMARY_FILE, summarize_telegram_metrics(hours=24, path=target)
            )


def summarize_telegram_metrics(hours: float = 24, path: Path | None = None) -> dict:
    target = path or METRICS_FILE
    cutoff = time.time() - max(0.0, hours) * 3600
    rows: list[dict] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines()[-10000:]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if float(row.get("timestamp", 0)) >= cutoff:
                rows.append(row)
    except OSError:
        pass

    # Delivery SLOs are calculated from real telegram_send events only. Canary
    # failures are tracked separately and must not poison one hour of user-send
    # success metrics after an expected Colab recovery.
    deliveries = [row for row in rows if row.get("event") == "telegram_send"]
    canaries = [row for row in rows if row.get("event") == "canary"]
    sent = [row for row in deliveries if row.get("status") == "sent"]
    providers: dict[str, int] = {}
    errors: dict[str, int] = {}
    for row in deliveries:
        provider = str(row.get("provider") or "unknown")
        providers[provider] = providers.get(provider, 0) + 1
        if row.get("status") != "sent":
            error = str(row.get("error_class") or row.get("status") or "unknown")
            errors[error] = errors.get(error, 0) + 1

    def nums(name: str) -> list[float]:
        return [float(row.get(name, 0)) for row in sent]

    return {
        "window_hours": hours,
        "generated_at": time.time(),
        "total_events": len(rows),
        "events": len(deliveries),
        "canary_events": len(canaries),
        "canary_failures": sum(1 for row in canaries if row.get("status") != "sent"),
        "sent": len(sent),
        "failed": len(deliveries) - len(sent),
        "success_rate": round(len(sent) / len(deliveries), 4) if deliveries else 1.0,
        "providers": providers,
        "errors": errors,
        "latency": {
            "gen_p50": _percentile(nums("gen_sec"), 0.50),
            "gen_p95": _percentile(nums("gen_sec"), 0.95),
            "send_p50": _percentile(nums("send_sec"), 0.50),
            "send_p95": _percentile(nums("send_sec"), 0.95),
            "total_p50": _percentile(nums("total_sec"), 0.50),
            "total_p95": _percentile(nums("total_sec"), 0.95),
        },
    }


def _prom_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _sqlite_status_counts(path: Path, table: str) -> dict[str, int]:
    import sqlite3

    if not path.exists():
        return {}
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2) as db:
            return {
                str(status): int(count)
                for status, count in db.execute(
                    f"SELECT status, COUNT(*) FROM {table} GROUP BY status"
                ).fetchall()
            }
    except (OSError, sqlite3.Error):
        return {}


def render_telegram_prometheus(hours: float = 24) -> str:
    """Render redacted Telegram delivery, queue and canary metrics."""
    summary = summarize_telegram_metrics(hours=hours)
    lines = [
        "# HELP aios_telegram_delivery_events Delivery events in the rolling metrics window.",
        "# TYPE aios_telegram_delivery_events gauge",
        f'aios_telegram_delivery_events{{status="sent"}} {int(summary["sent"])}',
        f'aios_telegram_delivery_events{{status="failed"}} {int(summary["failed"])}',
        "# HELP aios_telegram_delivery_success_ratio Successful delivery ratio in the rolling window.",
        "# TYPE aios_telegram_delivery_success_ratio gauge",
        f"aios_telegram_delivery_success_ratio {float(summary['success_rate']):.6f}",
        "# HELP aios_telegram_latency_seconds Delivery latency percentile by phase.",
        "# TYPE aios_telegram_latency_seconds gauge",
    ]
    for phase in ("gen", "send", "total"):
        for percentile in ("p50", "p95"):
            value = float(summary["latency"].get(f"{phase}_{percentile}", 0))
            quantile = "0.5" if percentile == "p50" else "0.95"
            lines.append(
                f'aios_telegram_latency_seconds{{phase="{phase}",quantile="{quantile}"}} {value:.6f}'
            )
    lines.extend(
        [
            "# HELP aios_telegram_provider_events Delivery events by selected provider.",
            "# TYPE aios_telegram_provider_events gauge",
        ]
    )
    for provider, count in sorted(summary.get("providers", {}).items()):
        lines.append(
            f'aios_telegram_provider_events{{provider="{_prom_label(provider)}"}} {int(count)}'
        )
    lines.extend(
        [
            "# HELP aios_telegram_delivery_errors Delivery failures by exception class.",
            "# TYPE aios_telegram_delivery_errors gauge",
        ]
    )
    for error, count in sorted(summary.get("errors", {}).items()):
        lines.append(
            f'aios_telegram_delivery_errors{{error_class="{_prom_label(error)}"}} {int(count)}'
        )

    queue_specs = (
        (
            "outbox",
            Path(
                os.environ.get("TELEGRAM_OUTBOX_DB", "")
                or state_path("telegram_outbox.sqlite3")
            ),
            "telegram_outbox",
        ),
        (
            "generation",
            Path(
                os.environ.get("TELEGRAM_GENERATION_DB", "")
                or state_path("telegram_generation.sqlite3")
            ),
            "telegram_generation",
        ),
    )
    lines.extend(
        [
            "# HELP aios_telegram_queue_jobs Current durable queue rows by queue and status.",
            "# TYPE aios_telegram_queue_jobs gauge",
        ]
    )
    known_statuses = {
        "outbox": (
            "pending",
            "sending",
            "sent",
            "failed",
            "failed_unknown",
            "resend_queued",
        ),
        "generation": ("pending", "generating", "completed", "failed", "dead_letter"),
    }
    for queue_name, db_path, table in queue_specs:
        counts = _sqlite_status_counts(db_path, table)
        for status in known_statuses[queue_name]:
            lines.append(
                f'aios_telegram_queue_jobs{{queue="{queue_name}",status="{status}"}} '
                f"{int(counts.get(status, 0))}"
            )

    canary_state_path = state_path("telegram_colab_canary.json")
    try:
        canary = json.loads(canary_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        canary = {}
    timestamp = float(canary.get("timestamp", 0) or 0)
    age = max(0.0, time.time() - timestamp) if timestamp else -1.0
    colab_mode = _prom_label(canary.get("mode") or "unknown")
    human_action_required = colab_mode == "human_action_required"
    lines.extend(
        [
            "# HELP aios_telegram_canary_ok Whether the latest Colab and Telegram canary passed.",
            "# TYPE aios_telegram_canary_ok gauge",
            f"aios_telegram_canary_ok {1 if canary.get('ok') else 0}",
            "# HELP aios_telegram_canary_consecutive_failures Consecutive full-canary failures.",
            "# TYPE aios_telegram_canary_consecutive_failures gauge",
            f"aios_telegram_canary_consecutive_failures {int(canary.get('consecutive_failures', 0) or 0)}",
            "# HELP aios_telegram_canary_age_seconds Age of the latest canary result; -1 means absent.",
            "# TYPE aios_telegram_canary_age_seconds gauge",
            f"aios_telegram_canary_age_seconds {age:.3f}",
            "# HELP aios_colab_mode Current owner-selected Colab operating mode.",
            "# TYPE aios_colab_mode gauge",
            f'aios_colab_mode{{mode="{colab_mode}"}} 1',
            "# HELP aios_colab_human_action_required Whether Colab waits for owner action such as CAPTCHA.",
            "# TYPE aios_colab_human_action_required gauge",
            f"aios_colab_human_action_required {1 if human_action_required else 0}",
        ]
    )

    alert_state_path = Path(
        os.environ.get(
            "AIOS_ALERT_CANARY_STATE", "/var/lib/aios-alert-canary/state.json"
        )
    )
    try:
        alert_canary = json.loads(alert_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        alert_canary = {}
    alert_timestamp = float(alert_canary.get("timestamp", 0) or 0)
    alert_age = max(0.0, time.time() - alert_timestamp) if alert_timestamp else -1.0
    lines.extend(
        [
            "# HELP aios_alertmanager_delivery_canary_ok Whether Alertmanager delivered and deleted the latest silent Telegram canary.",
            "# TYPE aios_alertmanager_delivery_canary_ok gauge",
            f"aios_alertmanager_delivery_canary_ok {1 if alert_canary.get('ok') else 0}",
            "# HELP aios_alertmanager_delivery_canary_age_seconds Age of the latest end-to-end alert canary; -1 means absent.",
            "# TYPE aios_alertmanager_delivery_canary_age_seconds gauge",
            f"aios_alertmanager_delivery_canary_age_seconds {alert_age:.3f}",
            "# HELP aios_alertmanager_delivery_canary_duration_seconds Latest end-to-end alert delivery latency.",
            "# TYPE aios_alertmanager_delivery_canary_duration_seconds gauge",
            f"aios_alertmanager_delivery_canary_duration_seconds {float(alert_canary.get('duration_seconds', 0) or 0):.3f}",
        ]
    )

    offsite_path = state_path("offsite_backup_state.json")
    try:
        offsite = json.loads(offsite_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        offsite = {}
    offsite_timestamp = float(offsite.get("timestamp", 0) or 0)
    offsite_age = (
        max(0.0, time.time() - offsite_timestamp) if offsite_timestamp else -1.0
    )
    lines.extend(
        [
            "# HELP aios_telegram_offsite_backup_configured Whether immutable off-host backup credentials are configured.",
            "# TYPE aios_telegram_offsite_backup_configured gauge",
            f"aios_telegram_offsite_backup_configured {1 if offsite.get('configured') else 0}",
            "# HELP aios_telegram_offsite_backup_ok Whether the latest configured off-host upload passed verification.",
            "# TYPE aios_telegram_offsite_backup_ok gauge",
            f"aios_telegram_offsite_backup_ok {1 if offsite.get('ok') else 0}",
            "# HELP aios_telegram_offsite_backup_age_seconds Age of the latest off-host backup attempt; -1 means absent.",
            "# TYPE aios_telegram_offsite_backup_age_seconds gauge",
            f"aios_telegram_offsite_backup_age_seconds {offsite_age:.3f}",
        ]
    )

    recovery_path = state_path("colab_recovery_metrics.json")
    try:
        recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recovery = {}
    recovery_mode = _prom_label(recovery.get("mode") or "unknown")
    lines.extend(
        [
            "# HELP aios_colab_recovery_duration_seconds Duration of the latest Colab recovery by mode.",
            "# TYPE aios_colab_recovery_duration_seconds gauge",
            f'aios_colab_recovery_duration_seconds{{mode="{recovery_mode}"}} {float(recovery.get("duration_seconds", 0) or 0):.3f}',
            "# HELP aios_colab_recovery_slo_seconds SLO budget for the latest Colab recovery mode.",
            "# TYPE aios_colab_recovery_slo_seconds gauge",
            f'aios_colab_recovery_slo_seconds{{mode="{recovery_mode}"}} {float(recovery.get("slo_seconds", 0) or 0):.3f}',
            "# HELP aios_colab_recovery_slo_met Whether the latest Colab recovery met its mode-specific SLO.",
            "# TYPE aios_colab_recovery_slo_met gauge",
            f'aios_colab_recovery_slo_met{{mode="{recovery_mode}"}} {1 if recovery.get("slo_met") else 0}',
        ]
    )
    return "\n".join(lines) + "\n"
