#!/usr/bin/env python3
"""N1: crypto news collector + LLM sentiment scoring (GROQ).

Fetches RSS feeds (CoinTelegraph, CoinDesk), extracts titles, batched LLM
sentiment analysis via GROQ (key from .env), appends to
data/quant/news_sentiment.jsonl. One row per news item:
  ts, source, title, url, sentiment (float -1..1), label, coins (mentions)

Usage:
    python scripts/collect_news_sentiment.py [--limit 30]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
OUT = DATA / "quant" / "news_sentiment.jsonl"
FEEDS = [
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cryptoslate", "https://cryptoslate.com/feed/"),
]

COINS = [
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "BNB",
    "DOGE",
    "ADA",
    "TRX",
    "TON",
    "LINK",
    "AVAX",
    "UNI",
    "NEAR",
    "LTC",
    "DOT",
    "SUI",
    "APT",
    "ARB",
    "OP",
    "INJ",
    "bitcoin",
    "ethereum",
    "tether",
    "XRP",
    "solana",
    "binance",
    "cardano",
]

SYSTEM_PROMPT = (
    "You are a crypto sentiment analyst. For each news headline return a JSON "
    'object {"sentiment": <float -1..1>, "coins": [<ticker symbols mentioned>]}. '
    "Positive news (adoption, growth, ETF inflow) -> positive; negative news "
    "(hacks, bans, liquidations) -> negative. Reply ONLY with a JSON array, "
    "one object per headline, no other text."
)


def fetch_rss(url: str, timeout: int = 20) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception as e:
        print(f"  rss fail {url}: {e}", flush=True)
        return []
    items = []
    try:
        root = ET.fromstring(raw)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if title:
                items.append({"title": title, "link": link})
    except Exception as e:
        print(f"  parse fail {url}: {e}", flush=True)
    return items


def all_keys() -> list[dict]:
    """All LLM keys: GROQ_API_KEY*, OPENROUTER_API_KEY."""
    try:
        env = (REPO_ROOT / ".env").read_text()
    except Exception:
        return []
    keys = []
    for m0 in re.finditer(r"^(GEMINI_API_KEY_[0-9]+)=(\S+)", env, re.M):
        keys.append({"provider": "gemini", "key": m0.group(2)})
    m = re.search(r"^OPENROUTER_API_KEY=(\S+)", env, re.M)
    if m:
        keys.append({"provider": "openrouter", "key": m.group(1)})
    for m2 in re.finditer(r"^(GROQ_API_KEY[A-Z_0-9]*)=(\S+)", env, re.M):
        keys.append({"provider": "groq", "key": m2.group(2)})
    return keys


def score_batch(keys: list[dict], titles: list[str]) -> list[dict]:
    """Try each key/provider until one works."""
    for k in keys:
        if k["provider"] == "gemini":
            body = json.dumps(
                {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": SYSTEM_PROMPT
                                    + "\n\n"
                                    + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
                                }
                            ]
                        }
                    ],
                }
            ).encode()
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={k['key']}"
            )
        elif k["provider"] == "groq":
            body = json.dumps(
                {
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))},
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                }
            ).encode()
            url = "https://api.groq.com/openai/v1/chat/completions"
        else:  # openrouter
            body = json.dumps(
                {
                    "model": "meta-llama/llama-3.3-70b-instruct",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))},
                    ],
                    "temperature": 0,
                }
            ).encode()
            url = "https://openrouter.ai/api/v1/chat/completions"
        try:
            hdrs = {"Content-Type": "application/json"}
            if k["provider"] != "gemini":
                hdrs["Authorization"] = f"Bearer {k['key']}"
            req = urllib.request.Request(url, data=body, headers=hdrs)
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.loads(r.read().decode())
            if k["provider"] == "gemini":
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                text = data["choices"][0]["message"]["content"]
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            m = re.search(r"\[.*\]", cleaned, re.S)
            if m:
                try:
                    arr = json.loads(m.group(0))
                    if isinstance(arr, list):
                        return arr
                except Exception:
                    pass
            return []
        except Exception as e:
            print(f"  {k['provider']} fail: {e}", flush=True)
            continue
    return []


def detect_coins(title: str) -> list[str]:
    found = set()
    upper = title.upper()
    for c in COINS:
        if re.search(rf"\b{c}\b", upper):
            found.add(c if len(c) <= 5 else c.upper())
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=30)
    _args = ap.parse_args()  # validated only; --limit not applied upstream

    keys = all_keys()
    if not keys:
        print("no LLM keys found in .env")
        return 1
    print(f"ключей: {len(keys)} ({', '.join(k['provider'] for k in keys)})", flush=True)

    seen = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            with contextlib.suppress(Exception):
                seen.add(json.loads(line)["url"])

    items = []
    for src, url in FEEDS:
        for it in fetch_rss(url):
            if it["link"] not in seen and not any(
                k in it["title"].lower() for k in ("sponsored", "opinion", "podcast")
            ):
                it["source"] = src
                items.append(it)
    print(f"новых новостей: {len(items)}", flush=True)
    if not items:
        print("нет новых — выход")
        return 0

    # батчим по 8 заголовков
    rows = []
    for i in range(0, len(items), 8):
        batch = items[i : i + 8]
        scores = score_batch(keys, [b["title"] for b in batch])
        for j, b in enumerate(batch):
            sc = scores[j] if j < len(scores) and isinstance(scores[j], dict) else {}
            try:
                sent = float(sc.get("sentiment", 0.0))
            except (TypeError, ValueError):
                sent = 0.0
            sent = max(-1.0, min(1.0, sent))
            coins = sc.get("coins") or detect_coins(b["title"])
            rows.append(
                {
                    "ts": time.time(),
                    "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
                    "source": b["source"],
                    "title": b["title"][:300],
                    "url": b["link"],
                    "sentiment": round(sent, 3),
                    "label": "positive" if sent > 0.2 else ("negative" if sent < -0.2 else "neutral"),
                    "coins": [str(c) for c in coins][:5],
                }
            )
        time.sleep(0.5)

    with open(OUT, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # сводка
    pos = sum(1 for r in rows if r["sentiment"] > 0.2)
    neg = sum(1 for r in rows if r["sentiment"] < -0.2)
    print(f"записано: {len(rows)} (pos {pos}, neg {neg}, neutral {len(rows) - pos - neg})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
