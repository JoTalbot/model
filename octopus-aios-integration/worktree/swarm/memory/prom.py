"""Prometheus exposition-format exporter for swarm memory metrics.

Produces the standard text format (one ``HELP``/``TYPE``/sample-line
triple per metric, ``\\n`` separated) so Prometheus' ``/metrics`` scrape
endpoint and OpenMetrics-compatible tools (Grafana Agent, VMagent,
Alloy, …) consume it without extra exporters or libraries.

No dependency on ``prometheus_client`` — we already have a
:class:`MemoryMetrics` instance and just need to flatten its snapshot
into Prometheus' line-oriented format.

Exposed metrics
---------------

============================= ==============================================
Name                          Description
============================= ==============================================
swarm_memory_puts_total       Counter of puts per scheme
swarm_memory_gets_total       Counter of gets, labelled ``status=ok|err``
swarm_memory_bytes_in_total   Counter of inbound bytes per scheme
swarm_memory_bytes_out_total  Counter of outbound bytes per scheme
swarm_memory_availability     Gauge 0..1, success rate per scheme
swarm_memory_latency_ms       Gauge, labelled ``op=put|get`` ``quantile=...``
swarm_memory_audit_total      Counter of audit events, labelled ``op`` ``ok``
swarm_memory_audit_bytes      Counter of bytes journalled per ``op``
============================= ==============================================

The audit counters are zero-cost when no audit log is wired in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from swarm.memory.port import MemoryMetrics

_LABEL_BAD = re.compile(r'["\n\\]')


def _esc(value: str) -> str:
    """Escape a Prometheus label value per exposition-format rules."""
    return _LABEL_BAD.sub(
        lambda m: {'"': r'\"', "\n": r"\n", "\\": r"\\"}[m.group(0)],
        value,
    )


def _emit(name: str, help_text: str, kind: str, samples: Iterable[tuple[dict[str, str], float]]) -> str:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
    for labels, value in samples:
        if labels:
            label_str = ",".join(f'{k}="{_esc(v)}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    return "\n".join(lines)


def render_metrics(metrics: MemoryMetrics, *, audit_stats: dict | None = None) -> str:
    """Render a :class:`MemoryMetrics` snapshot in Prometheus format.

    ``audit_stats`` is the optional return value of :meth:`AuditLog.stats`;
    when supplied, two extra counters are emitted so a single ``/metrics``
    page covers the entire memory subsystem (live + journalled).
    """
    snap = metrics.snapshot()
    chunks: list[str] = []

    chunks.append(_emit(
        "swarm_memory_puts_total",
        "Total successful puts, by scheme.",
        "counter",
        [({"scheme": s}, snap[s]["puts"]) for s in snap],
    ))
    chunks.append(_emit(
        "swarm_memory_gets_total",
        "Total gets, labelled by status (ok|err).",
        "counter",
        [
            (
                {"scheme": s, "status": status},
                snap[s]["gets_ok"] if status == "ok" else snap[s]["gets_err"],
            )
            for s in snap
            for status in ("ok", "err")
        ],
    ))
    chunks.append(_emit(
        "swarm_memory_bytes_in_total",
        "Total inbound bytes per scheme (put payload size).",
        "counter",
        [({"scheme": s}, snap[s]["bytes_in"]) for s in snap],
    ))
    chunks.append(_emit(
        "swarm_memory_bytes_out_total",
        "Total outbound bytes per scheme (get payload size).",
        "counter",
        [({"scheme": s}, snap[s]["bytes_out"]) for s in snap],
    ))
    chunks.append(_emit(
        "swarm_memory_availability",
        "Get success ratio per scheme (0..1).",
        "gauge",
        [({"scheme": s}, snap[s]["availability"]) for s in snap],
    ))

    latency_samples: list[tuple[dict[str, str], float]] = []
    for scheme, row in snap.items():
        for op in ("put", "get"):
            for q_str, key in (
                ("0.5", f"latency_{op}_p50_ms"),
                ("0.95", f"latency_{op}_p95_ms"),
            ):
                v = row.get(key)
                if v is None:
                    continue
                latency_samples.append((
                    {"scheme": scheme, "op": op, "quantile": q_str},
                    float(v),
                ))
    chunks.append(_emit(
        "swarm_memory_latency_ms",
        "Latency in milliseconds, labelled by scheme/op/quantile.",
        "gauge",
        latency_samples,
    ))

    if audit_stats:
        audit_total: list[tuple[dict[str, str], float]] = []
        per_scheme_ok = audit_stats.get("per_scheme_ok") or {}
        per_scheme_err = audit_stats.get("per_scheme_err") or {}
        all_schemes = sorted(set(per_scheme_ok) | set(per_scheme_err))
        for scheme in all_schemes:
            audit_total.append(({"scheme": scheme, "ok": "true"}, per_scheme_ok.get(scheme, 0)))
            audit_total.append(({"scheme": scheme, "ok": "false"}, per_scheme_err.get(scheme, 0)))
        chunks.append(_emit(
            "swarm_memory_audit_total",
            "Audit-log event counts by scheme and ok status.",
            "counter",
            audit_total,
        ))
        chunks.append(_emit(
            "swarm_memory_audit_bytes",
            "Total bytes journalled across all audit-log events.",
            "counter",
            [({}, float(audit_stats.get("bytes_total", 0)))],
        ))
    return "\n".join(chunks) + "\n"


__all__ = ["render_metrics"]
