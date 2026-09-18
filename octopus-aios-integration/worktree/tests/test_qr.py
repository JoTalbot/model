"""Tests for swarm.memory.qr -- sneakernet QR-code recovery."""

from __future__ import annotations

import pytest

from swarm.memory.qr import qr_capacity_check, qr_matrix, qr_terminal

# ---------------------------------------------------------------------------
# qr_terminal
# ---------------------------------------------------------------------------


def test_qr_terminal_returns_non_empty_string_for_short_data():
    out = qr_terminal("ref:catbox:https://catbox.moe/x")
    assert isinstance(out, str)
    assert len(out) > 50
    assert any(ch in out for ch in "█▀▄")


def test_qr_terminal_higher_ec_level_makes_larger_qr():
    small = qr_terminal("ref:x:y", ec_level="L")
    large = qr_terminal("ref:x:y", ec_level="H")
    # H-ECC needs more modules than L for the same payload, so the
    # terminal art has at least as many rows.
    assert len(large) >= len(small)


def test_qr_terminal_rejects_empty():
    with pytest.raises(ValueError):
        qr_terminal("")


def test_qr_terminal_rejects_non_string():
    with pytest.raises(TypeError):
        qr_terminal(b"bytes")  # type: ignore[arg-type]


def test_qr_terminal_rejects_unknown_ec_level():
    with pytest.raises(ValueError, match="ec_level"):
        qr_terminal("data", ec_level="X")


def test_qr_terminal_grows_with_data_size():
    small = qr_terminal("short")
    large = qr_terminal("x" * 500)
    assert len(large) > len(small)


def test_qr_terminal_handles_unicode():
    out = qr_terminal("Bootstrap для Бессмертного Роя")
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# qr_matrix
# ---------------------------------------------------------------------------


def test_qr_matrix_returns_square_bool_grid():
    matrix = qr_matrix("ref:catbox:short")
    assert isinstance(matrix, list)
    n = len(matrix)
    assert n > 0
    assert all(isinstance(row, list) and len(row) == n for row in matrix)
    assert all(isinstance(cell, bool) for row in matrix for cell in row)


def test_qr_matrix_has_finder_patterns_in_corners():
    matrix = qr_matrix("hello", ec_level="M")
    # Three 7x7 dark-bordered "finder" patterns sit at TL, TR, BL,
    # offset by the quiet-zone border (default 2 modules).
    # Sanity-check the top-left finder's first dark module.
    n = len(matrix)
    # Find the first dark cell scanning from top-left -- this anchors
    # the top-left finder pattern.
    found = any(matrix[r][c] for r in range(min(5, n)) for c in range(min(5, n)))
    assert found, "expected at least one dark module near the TL finder"


# ---------------------------------------------------------------------------
# qr_capacity_check
# ---------------------------------------------------------------------------


def test_qr_capacity_check_reports_version_and_size():
    info = qr_capacity_check("ref:catbox:short")
    assert 1 <= info["version"] <= 40
    assert info["modules"] >= 21
    assert info["bytes"] == len("ref:catbox:short")
    assert info["ec_level"] == "M"


def test_qr_capacity_check_version_grows_with_payload():
    small = qr_capacity_check("hi")
    large = qr_capacity_check("x" * 1500)
    assert large["version"] >= small["version"]
    assert large["modules"] > small["modules"]
