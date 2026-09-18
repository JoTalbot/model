#!/usr/bin/env python3
"""D5: portfolio value chart (VA main vs DCA control) -> Telegram photo.

Reads both value logs, plots cumulative value (and invested line), sends the
PNG to the owner via Telegram sendPhoto (no file persistence needed).

Usage:
    python scripts/dca_chart_report.py [--send]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def load_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def cred(name: str) -> str | None:
    p = (
        Path(
            os.environ.get("OCTOPUS_CREDENTIAL_SOURCE_DIR", "/etc/octopus/credentials")
        )
        / name
    )
    return p.read_text().strip() if p.exists() else None


def build_chart() -> Path:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as err:
        raise RuntimeError(
            "matplotlib not installed - chart skipped (text report still works)"
        ) from err
    va = load_log(DATA / "dca_paper_value.jsonl")
    dca = load_log(DATA / "dca_paper_value_control.jsonl")
    t2 = load_log(DATA / "t2_paper_equity.jsonl")
    fig, ax = plt.subplots(figsize=(9, 5))
    if va:
        x = [datetime.fromisoformat(r["date"]) for r in va]
        y = [r["value_usd"] for r in va]
        ax.plot(
            x, y, "-o", label=f"VA main (${va[-1]['value_usd']:.2f})", color="#2e7d32"
        )
        ax.plot(
            x,
            [r["deposited_usd"] for r in va],
            "--",
            color="#9e9e9e",
            label="invested VA",
        )
    if dca:
        x2 = [datetime.fromisoformat(r["date"]) for r in dca]
        y2 = [r["value_usd"] for r in dca]
        ax.plot(
            x2,
            y2,
            "-o",
            label=f"DCA control (${dca[-1]['value_usd']:.2f})",
            color="#1565c0",
        )
        ax.plot(
            x2,
            [r["deposited_usd"] for r in dca],
            ":",
            color="#9e9e9e",
            label="invested DCA",
        )
    if t2:
        x3 = [datetime.fromisoformat(r["date"]) for r in t2]
        y3 = [r["equity"] for r in t2]
        ax.plot(
            x3,
            y3,
            "-",
            label=f"T2-BTC (${y3[-1]:,.0f})",
            color="#c62828",
            linewidth=1.5,
        )
        ax.plot(x3, [r["bh_equity"] for r in t2], ":", color="#ef9a9a", label="T2 BH")
    ax.set_title("Портфели: DCA vs T2-момент")
    ax.set_ylabel("$")
    ax.grid(alpha=0.3)
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.tight_layout()
    out = DATA / "dca_chart.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def send_photo(token: str, chat_id: str, photo_path: Path, caption: str) -> bool:

    boundary = "----aiosdca"
    parts = []
    # caption
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
    )
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"{caption}\r\n"
    )
    data = photo_path.read_bytes()
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="photo"; filename="dca.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    )
    body = ("".join(parts)).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        print(f"sendPhoto fail: {e}", flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true", help="send to Telegram")
    args = ap.parse_args()

    try:
        chart = build_chart()
    except RuntimeError as e:
        print(e, flush=True)
        return 0
    print(f"chart -> {chart}", flush=True)
    if args.send:
        token, chat = cred("telegram_token"), cred("telegram_owner_chat_id")
        if token and chat:
            ok = send_photo(
                token, chat, chart, "📈 DCA-портфели: VA (main) vs DCA (control)"
            )
            print(f"sent: {ok}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
