"""Tests for swarm.memory.prom -- Prometheus exposition-format exporter."""

from __future__ import annotations

from swarm.memory.port import MemoryMetrics
from swarm.memory.prom import render_metrics


def _populated_metrics() -> MemoryMetrics:
    m = MemoryMetrics()
    m.record_put("catbox")
    m.record_put("catbox")
    m.record_put("nullpointer")
    m.record_get("catbox", ok=True)
    m.record_get("catbox", ok=False)
    m.record_get("nullpointer", ok=True)
    m.record_bytes_in("catbox", 100)
    m.record_bytes_in("catbox", 200)
    m.record_bytes_out("catbox", 50)
    m.record_latency("catbox", "put", 0.001)
    m.record_latency("catbox", "put", 0.010)
    m.record_latency("catbox", "get", 0.005)
    m.record_error("catbox", "boom")
    return m


def test_render_includes_required_metric_headers():
    text = render_metrics(_populated_metrics())
    for name in (
        "swarm_memory_puts_total",
        "swarm_memory_gets_total",
        "swarm_memory_bytes_in_total",
        "swarm_memory_bytes_out_total",
        "swarm_memory_availability",
        "swarm_memory_latency_ms",
    ):
        assert f"# HELP {name}" in text
        assert f"# TYPE {name}" in text


def test_render_emits_counters_with_scheme_labels():
    text = render_metrics(_populated_metrics())
    assert 'swarm_memory_puts_total{scheme="catbox"} 2' in text
    assert 'swarm_memory_puts_total{scheme="nullpointer"} 1' in text


def test_render_emits_ok_and_err_gets_status():
    text = render_metrics(_populated_metrics())
    assert 'swarm_memory_gets_total{scheme="catbox",status="ok"} 1' in text
    assert 'swarm_memory_gets_total{scheme="catbox",status="err"} 1' in text


def test_render_includes_availability_gauge():
    text = render_metrics(_populated_metrics())
    assert 'swarm_memory_availability{scheme="catbox"} 0.5' in text
    assert 'swarm_memory_availability{scheme="nullpointer"} 1' in text


def test_render_includes_latency_with_quantile_label():
    text = render_metrics(_populated_metrics())
    assert "swarm_memory_latency_ms" in text
    assert 'op="put"' in text
    assert 'quantile="0.5"' in text
    assert 'quantile="0.95"' in text


def test_render_handles_empty_metrics():
    text = render_metrics(MemoryMetrics())
    assert "swarm_memory_puts_total" in text
    assert "swarm_memory_latency_ms" in text


def test_render_escapes_label_quotes_and_newlines():
    m = MemoryMetrics()
    m.record_put('bad"scheme')
    text = render_metrics(m)
    assert 'scheme="bad\\"scheme"' in text


def test_render_audit_stats_emits_extra_counters():
    audit_stats = {
        "total": 5,
        "per_op": {"put": 3, "get": 2},
        "per_scheme_ok": {"catbox": 4},
        "per_scheme_err": {"catbox": 1},
        "bytes_total": 1234,
    }
    text = render_metrics(_populated_metrics(), audit_stats=audit_stats)
    assert 'swarm_memory_audit_total{ok="true",scheme="catbox"} 4' in text
    assert 'swarm_memory_audit_total{ok="false",scheme="catbox"} 1' in text
    assert "swarm_memory_audit_bytes 1234" in text


def test_render_audit_stats_omitted_when_none():
    text = render_metrics(_populated_metrics())
    assert "swarm_memory_audit_total" not in text
    assert "swarm_memory_audit_bytes" not in text


def test_render_output_ends_with_newline():
    text = render_metrics(_populated_metrics())
    assert text.endswith("\n")


def test_render_output_is_parseable_by_a_naive_parser():
    text = render_metrics(_populated_metrics())
    samples: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("# HELP "):
            current = line.split(" ", 2)[1]
            samples[current] = []
        elif line.startswith("# TYPE"):
            continue
        elif line.strip():
            assert current is not None
            samples[current].append(line)
    # Each emitted metric must have at least one sample line.
    for name, lines in samples.items():
        assert lines, f"metric {name} has no samples"
