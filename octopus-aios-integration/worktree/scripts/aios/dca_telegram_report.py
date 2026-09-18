#!/usr/bin/env python3
"""Send a weekly DCA portfolio summary to the owner via Telegram.

Reads credentials from systemd-style credential files:
  /etc/octopus/credentials/telegram_token
  /etc/octopus/credentials/telegram_owner_chat_id
(no secrets in code; falls back to env vars for manual runs).

Usage:
    python scripts/dca_telegram_report.py [--weekly]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def load_credential(name: str) -> str | None:
    p = (
        Path(
            os.environ.get("OCTOPUS_CREDENTIAL_SOURCE_DIR", "/etc/octopus/credentials")
        )
        / name
    )
    if p.exists():
        return p.read_text().strip()
    return None


def load_state() -> dict:
    try:
        return json.loads((DATA / "dca_paper_state.json").read_text())
    except (OSError, ValueError):
        return {}


def load_value_log() -> list[dict]:
    p = DATA / "dca_paper_value.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def send_message(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        print(f"send fail: {e}", flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weekly", action="store_true", help="weekly summary mode")
    args = ap.parse_args()


    token = load_credential("telegram_token")
    chat_id = load_credential("telegram_owner_chat_id")
    if not token or not chat_id:
        print("credentials not found", flush=True)
        return 1

    state = load_state()
    log = load_value_log()
    # контрольный портфель (plain DCA) для сравнения
    # NOTE(octopus-wave3): в апстриме AIOS здесь был lines.append() ДО создания
    # lines -> NameError глотался except'ом и строка контроля терялась всегда.
    # Считаем строку отдельно, добавляем после lines = [...].
    control_line = None
    try:
        import json as _j

        cstate = _j.loads((DATA / "dca_paper_state_control.json").read_text())
        cvlog = [
            _j.loads(line)
            for line in (DATA / "dca_paper_value_control.jsonl").read_text().splitlines()
            if line
        ]
        cval = cvlog[-1]["value_usd"] if cvlog else 0.0
        cdep = float(cstate.get("deposited_usd", 0))
        cpnl = cval - cdep
        control_line = (
            f"🔁 <b>Контроль (DCA):</b> ${cdep:.0f} → ${cval:.2f} ({cpnl:+.2f}$)"
        )
    except Exception:
        pass
    deposited = float(state.get("deposited_usd", 0.0))
    fees = float(state.get("fees_usd", 0.0))
    holdings = state.get("holdings", {})
    buys = state.get("buys", [])
    value = log[-1]["value_usd"] if log else 0.0
    pnl = value - deposited
    pnl_pct = pnl / deposited * 100.0 if deposited else 0.0
    last_deposit = state.get("last_deposit", "—")

    lines = [
        "📊 <b>DCA-портфель (paper)</b>",
        f"💵 Вложено: <b>${deposited:.2f}</b>",
        f"💰 Стоимость: <b>${value:.2f}</b> ({pnl:+.2f}$ / {pnl_pct:+.2f}%)",
        f"🧾 Комиссии: ${fees:.2f} | Позиций: {len(holdings)}",
        f"📅 Последний депозит: {last_deposit}",
    ]
    if control_line:
        lines.append(control_line)
    if args.weekly:
        if buys:
            recent = buys[-10:]
            lines.append("")
            lines.append("🛒 <b>Последние покупки:</b>")
            for b in recent:
                lines.append(
                    f"• {b['date']} {b['symbol']} @ {b['price']:.6f} ({b['usd']:.2f}$)"
                )
        lines.append("")
        lines.append("⏭ Следующий депозит: через 7 дней | Ребаланс: раз в 90 дней")

    ok = send_message(token, chat_id, "\n".join(lines))
    print(f"sent: {ok}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
