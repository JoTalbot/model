"""Tests for swarm.memory.doctor — bulk ref health probing."""

from __future__ import annotations

import asyncio

import pytest

from swarm.memory.doctor import (
    RefHealth,
    format_report,
    probe_many,
    probe_ref,
    summarize,
)

# ---------------------------------------------------------------------------
# Tiny ports for tests
# ---------------------------------------------------------------------------


class StaticExistsPort:
    def __init__(self, mapping: dict[str, bool], delay: float = 0.0) -> None:
        self._mapping = mapping
        self._delay = delay

    async def exists(self, ref: str) -> bool:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._mapping.get(ref, False)


class RaisingExistsPort:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def exists(self, ref: str) -> bool:
        raise self._exc


class HangingPort:
    async def exists(self, ref: str) -> bool:
        await asyncio.sleep(10)
        return True


# ---------------------------------------------------------------------------
# probe_ref
# ---------------------------------------------------------------------------


async def test_probe_ref_returns_healthy_true():
    port = StaticExistsPort({"ref:catbox:url": True})
    result = await probe_ref(port, "ref:catbox:url")
    assert result.healthy is True
    assert result.scheme == "catbox"
    assert result.error is None
    assert result.latency_ms >= 0


async def test_probe_ref_returns_healthy_false_for_missing():
    port = StaticExistsPort({"ref:catbox:url": False})
    result = await probe_ref(port, "ref:catbox:url")
    assert result.healthy is False
    assert result.error == "not found"


async def test_probe_ref_traps_exceptions():
    port = RaisingExistsPort(RuntimeError("network down"))
    result = await probe_ref(port, "ref:catbox:x")
    assert result.healthy is False
    assert "RuntimeError" in result.error
    assert "network down" in result.error


async def test_probe_ref_honors_timeout():
    port = HangingPort()
    result = await probe_ref(port, "ref:catbox:x", timeout=0.05)
    assert result.healthy is False
    assert "timeout" in result.error.lower() or "TimeoutError" in result.error  # case-insensitive


async def test_probe_ref_handles_bad_ref_string():
    port = StaticExistsPort({"not-a-ref": True})
    result = await probe_ref(port, "not-a-ref")
    assert result.scheme is None
    assert result.healthy is True


# ---------------------------------------------------------------------------
# probe_many
# ---------------------------------------------------------------------------


async def test_probe_many_preserves_order():
    refs = ["ref:a:1", "ref:a:2", "ref:a:3"]
    port = StaticExistsPort({r: True for r in refs})
    results = await probe_many(port, refs)
    assert [r.ref for r in results] == refs


async def test_probe_many_empty_list():
    port = StaticExistsPort({})
    assert await probe_many(port, []) == []


async def test_probe_many_concurrency_caps_parallelism():
    refs = [f"ref:catbox:{i}" for i in range(20)]
    port = StaticExistsPort({r: True for r in refs}, delay=0.005)
    results = await probe_many(port, refs, concurrency=4)
    assert len(results) == 20
    assert all(r.healthy for r in results)


async def test_probe_many_mixed_outcomes():
    refs = ["ref:catbox:good", "ref:catbox:bad", "ref:nullpointer:good"]
    port = StaticExistsPort({
        "ref:catbox:good": True,
        "ref:catbox:bad": False,
        "ref:nullpointer:good": True,
    })
    results = await probe_many(port, refs)
    assert [r.healthy for r in results] == [True, False, True]


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


def test_summarize_empty():
    s = summarize([])
    assert s["total"] == 0
    assert s["healthy"] == 0
    assert s["broken"] == 0
    assert s["per_scheme_healthy"] == {}
    assert s["latency_ms_avg"] == 0.0


def test_summarize_counts_healthy_and_broken():
    results = [
        RefHealth("ref:a:1", "a", True, 10.0),
        RefHealth("ref:a:2", "a", False, 20.0, "x"),
        RefHealth("ref:b:1", "b", True, 30.0),
    ]
    s = summarize(results)
    assert s["total"] == 3
    assert s["healthy"] == 2
    assert s["broken"] == 1
    assert s["per_scheme_healthy"] == {"a": 1, "b": 1}
    assert s["per_scheme_broken"] == {"a": 1}


def test_summarize_latency_percentiles():
    results = [
        RefHealth(f"ref:a:{i}", "a", True, float(i)) for i in range(1, 101)
    ]
    s = summarize(results)
    assert s["latency_ms_avg"] == pytest.approx(50.5)
    assert 45 <= s["latency_ms_p50"] <= 55
    assert 90 <= s["latency_ms_p95"] <= 100


def test_summarize_handles_none_scheme():
    results = [
        RefHealth("notaref", None, False, 5.0, "bad"),
    ]
    s = summarize(results)
    assert s["per_scheme_broken"] == {"?": 1}


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_includes_per_ref_and_summary():
    results = [
        RefHealth("ref:catbox:x", "catbox", True, 12.34),
        RefHealth("ref:nullpointer:y", "nullpointer", False, 99.0, "HTTP 500"),
    ]
    summary = summarize(results)
    text = format_report(results, summary)
    assert "ref:catbox:x" in text
    assert "ref:nullpointer:y" in text
    assert "OK" in text
    assert "ERR" in text
    assert "HTTP 500" in text
    assert "total=2" in text
    assert "healthy=1" in text


def test_format_report_empty():
    text = format_report([], summarize([]))
    assert "no refs supplied" in text
    assert "total=0" in text


# ---------------------------------------------------------------------------
# RefHealth dict round-trip
# ---------------------------------------------------------------------------


def test_ref_health_to_dict():
    h = RefHealth("ref:a:1", "a", True, 1.5, None)
    d = h.to_dict()
    assert d == {
        "ref": "ref:a:1",
        "scheme": "a",
        "healthy": True,
        "latency_ms": 1.5,
        "error": None,
    }
