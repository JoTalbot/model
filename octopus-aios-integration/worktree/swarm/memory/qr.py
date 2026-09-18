"""Sneakernet recovery via QR codes.

Bootstrap manifests + dropbox refs can be huge (multi-line JSON), but
the *URL* that fetches them is tiny -- 30-40 ASCII bytes for a catbox /
telegra.ph / 0x0.st link.  A single QR code holds ~2 KB of text, so the
typical workflow is:

1. Publish the manifest / dropbox to one or more pastebins
2. Run ``memory bootstrap-qr <ref>`` -- prints a QR you can photograph
3. On the recovery side, scan the QR with any phone reader, paste the
   URL into ``memory bootstrap-restore`` and the swarm wakes back up

The whole module is a thin, dependency-honest wrapper around the
``qrcode`` library so the rest of the codebase can call one function
and not care about ECC levels or version negotiation.

The library is listed as a hard requirement in ``requirements.txt``;
:func:`qr_terminal` falls back to a graceful error if it ever goes
missing (so a stripped-down deployment still loads the module).
"""

from __future__ import annotations

import io
from typing import Any

_TERMINAL_QR_NOT_AVAILABLE = (
    "qrcode library is not installed -- pip install qrcode>=7.4 to enable "
    "sneakernet QR recovery"
)


def _qr_factory(data: str, *, ec_level: str = "M") -> Any:
    try:
        import qrcode  # type: ignore[import-untyped]
        from qrcode.constants import (  # type: ignore[import-untyped]
            ERROR_CORRECT_H,
            ERROR_CORRECT_L,
            ERROR_CORRECT_M,
            ERROR_CORRECT_Q,
        )
    except ImportError as exc:
        raise RuntimeError(_TERMINAL_QR_NOT_AVAILABLE) from exc

    ec_map = {
        "L": ERROR_CORRECT_L,
        "M": ERROR_CORRECT_M,
        "Q": ERROR_CORRECT_Q,
        "H": ERROR_CORRECT_H,
    }
    if ec_level not in ec_map:
        raise ValueError(
            f"ec_level must be one of {sorted(ec_map.keys())}, got {ec_level!r}"
        )

    q = qrcode.QRCode(
        version=None,
        error_correction=ec_map[ec_level],
        box_size=1,
        border=2,
    )
    q.add_data(data)
    q.make(fit=True)
    return q


def qr_terminal(data: str, *, ec_level: str = "M") -> str:
    """Render ``data`` as a terminal-printable QR code (UTF-8 block art).

    Parameters
    ----------
    data:
        The payload to encode.  Strings only -- callers wanting to encode
        a manifest should publish it to a pastebin first and pass the ref.
        Practical upper bound is around 2 KB before the QR becomes too
        dense for a phone camera to decode.
    ec_level:
        Reed-Solomon error correction level.  One of ``L`` (~7 %),
        ``M`` (~15 %, default), ``Q`` (~25 %), ``H`` (~30 %).
    """
    if not isinstance(data, str):
        raise TypeError(f"qr_terminal needs str, got {type(data).__name__}")
    if not data:
        raise ValueError("qr_terminal needs non-empty data")

    q = _qr_factory(data, ec_level=ec_level)
    buf = io.StringIO()
    q.print_ascii(out=buf, invert=True)
    return buf.getvalue().rstrip("\n")


def qr_matrix(data: str, *, ec_level: str = "M") -> list[list[bool]]:
    """Return the raw QR module matrix as a list of lists of bools.

    Useful for callers that want their own renderer (SVG, PNG, BMP).
    ``True`` = dark module, ``False`` = light.
    """
    q = _qr_factory(data, ec_level=ec_level)
    return [list(row) for row in q.get_matrix()]


def qr_capacity_check(data: str, *, ec_level: str = "M") -> dict[str, Any]:
    """Cheap sanity report for callers worried about scan reliability.

    Returns the picked QR ``version`` (1..40), the module count, and the
    encoded byte length.  Versions above ~25 get hard to scan from a
    phone, so prefer publishing the body and passing the short ref.
    """
    q = _qr_factory(data, ec_level=ec_level)
    return {
        "version": q.version,
        "modules": q.modules_count,
        "bytes": len(data.encode("utf-8")),
        "ec_level": ec_level,
    }


__all__ = ["qr_capacity_check", "qr_matrix", "qr_terminal"]
