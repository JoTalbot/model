#!/usr/bin/env python3
"""V3: weekly digest of all quant/portfolio services to Telegram."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("OCTOPUS_ROOT", "/opt/octopus"))
DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))


def cred(name):
    p = (
        Path(
            os.environ.get("OCTOPUS_CREDENTIAL_SOURCE_DIR", "/etc/octopus/credentials")
        )
        / name
    )
    return p.read_text().strip() if p.exists() else None


def send(text):
    t, c = cred("telegram_token"), cred("telegram_owner_chat_id")
    if not t or not c:
        print("no creds")
        return False
    data = urllib.parse.urlencode(
        {"chat_id": c, "text": text, "parse_mode": "HTML"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{t}/sendMessage", data=data
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("ok", False)


def main():
    lines = ["📋 <b>AIOS Quant-дайджест</b>", ""]
    # DCA
    try:
        s = json.loads((DATA / "dca_paper_state.json").read_text())
        vlog = [
            json.loads(line)
            for line in (DATA / "dca_paper_value.jsonl").read_text().splitlines()
            if line
        ]
        val = vlog[-1]["value_usd"] if vlog else 0
        dep = float(s.get("deposited_usd", 0))
        pnl = val - dep
        lines.append(
            f"📈 <b>DCA:</b> ${dep:.0f} → ${val:.2f} ({pnl:+.2f}$ / {pnl / dep * 100 if dep else 0:+.1f}%)"
        )
    except Exception as e:
        lines.append(f"📈 DCA: ошибка ({e})")
    # ws-данные
    try:
        con = sqlite3.connect(DATA / "quant/orderbooks.sqlite")
        n = con.execute("SELECT COUNT(*) FROM snapshots_ws").fetchone()[0]
        h = (
            con.execute("SELECT MAX(ts)-MIN(ts) FROM snapshots_ws").fetchone()[0] or 0
        ) / 3600
        lines.append(f"🌊 <b>ws-данные:</b> {n:,} снапшотов ({h:.1f} ч)")
        con.close()
    except Exception as e:
        lines.append(f"🌊 ws: ошибка ({e})")
    # A/B paper
    try:
        m = json.loads(
            (DATA / "multi_exchange_portfolios_owner_paper.json").read_text()
        )
        c = json.loads(
            (
                DATA / "multi_exchange_portfolios_owner_paper_control.json"
            ).read_text()
        )
        tm = sum(p.get("total_trades", 0) for p in m.values() if isinstance(p, dict))
        tc = sum(p.get("total_trades", 0) for p in c.values() if isinstance(p, dict))
        lines.append(
            f"⚖️ <b>A/B paper:</b> main (trail 1.0) {tm} сделок | control (0.988) {tc}"
        )
    except Exception as e:
        lines.append(f"⚖️ A/B: ошибка ({e})")
    # T2 momentum (BTC/ETH)
    try:
        import json as _j

        parts = []
        for tag, fname in (
            ("BTC", "t2_paper_state.json"),
            ("ETH", "t2_paper_state_ethusd.json"),
        ):
            st = _j.loads((DATA / fname).read_text())
            eq = float(st.get("equity", 0))
            pct = (eq / 10000 - 1) * 100 if eq else 0
            parts.append(f"{tag}:{st.get('position')} ({pct:+.1f}%)")
        lines.append(f"📈 <b>T2:</b> {' | '.join(parts)}")
    except Exception:
        pass
    # MM-сигналы: точность + экономика
    try:
        import subprocess as sp

        r = sp.run(
            ["sys.executable", "scripts/aios/mm_signal_score.py"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        last = [line for line in r.stdout.strip().split("\n") if "ИТОГО" in line]
        lines.append(f"📡 <b>MM-сигналы:</b> {last[0] if last else 'нет данных'}")
        # экономика: maker-вход (W4) - ключевая метрика
        r2 = sp.run(
            ["sys.executable", "scripts/aios/signal_pnl_maker.py"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        for line in r2.stdout.strip().split("\n"):
            if "ИТОГО" in line:
                lines.append(f"💰 <b>Экономика (maker-вход):</b> {line}")
                break
    except Exception as e:
        lines.append(f"📡 MM: ошибка ({e})")
    # новостной сентимент
    try:
        import json as _j

        rows = [
            _j.loads(line)
            for line in (DATA / "quant" / "news_sentiment.jsonl").read_text().splitlines()
            if line
        ]
        if rows:
            pos = sum(1 for r in rows if r["sentiment"] > 0.2)
            neg = sum(1 for r in rows if r["sentiment"] < -0.2)
            avg = sum(r["sentiment"] for r in rows[-50:]) / max(1, len(rows[-50:]))
            lines.append(
                f"📰 <b>Сентимент:</b> {len(rows)} новостей (pos {pos}/neg {neg}), avg50 {avg:+.2f}"
            )
    except Exception:
        pass
    # сервисы
    try:
        svc = subprocess.run(
            [
                "systemctl",
                "is-active",
                "aios-orderbook-ws.service",
                "aios-quant-trading.service",
                "aios-quant-trading-control.service",
                "aios-dca-paper.timer",
                "aios-dca-report.timer",
            ],
            capture_output=True,
            text=True,
        )
        st = svc.stdout.strip().split("\n")
        lines.append(f"🖥 <b>Сервисы:</b> {', '.join(st)}")
    except Exception as e:
        lines.append(f"🖥 сервисы: ошибка ({e})")
    ok = send("\n".join(lines))
    print("sent:", ok)


if __name__ == "__main__":
    main()
