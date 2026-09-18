#!/usr/bin/env python3
"""Score historical news headlines with Gemini sentiment (batched, rate-limited).

Reads data/quant/news_historical.jsonl, scores entries without a 'sentiment'
field, appends scores back (rewrites file). Batches of 8, 4s sleep between
requests (Gemini free tier ~15 RPM), 3 keys rotated.

Usage:
    python scripts/score_historical_sentiment.py [--batch-limit 200]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("OCTOPUS_DATA") or (REPO_ROOT / "data"))
SRC = DATA / "quant" / "news_historical.jsonl"
OUT = DATA / "quant" / "news_historical_scored.jsonl"

PROMPT = (
    "You are a crypto sentiment analyst. For each news headline return a JSON "
    'array of objects: {"sentiment": <float -1..1>} - one per headline, same '
    "order. Positive news (adoption, growth, ETF inflow, price rise) -> positive; "
    "negative (hacks, bans, liquidations, price fall) -> negative. Reply ONLY "
    "with the JSON array, no other text."
)


def gemini_keys() -> list[str]:
    """Return keys not ruled out by DEFINITIVE auth errors (401/403/404).

    429 (rate limit) and timeouts are transient -> key kept (scoring retries
    with backoff anyway). If every request fails transiently, return all
    candidates rather than giving up.
    """
    env = (REPO_ROOT / ".env").read_text()
    candidates = [m.group(1) for m in re.finditer(r"^GEMINI_API_KEY_[0-9]+=(\S+)", env, re.M)]
    if not candidates:
        return []
    good = []
    transient = 0
    for k in candidates:
        body = json.dumps({"contents": [{"parts": [{"text": "Reply: ok"}]}]}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={k}"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                json.loads(r.read().decode())
            good.append(k)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                continue  # definitively bad key/model
            transient += 1  # 429/5xx: keep
            good.append(k)
        except Exception:
            transient += 1  # timeout/network: keep
            good.append(k)
    return good or (candidates if transient else [])


def score_batch(key: str, titles: list[str]) -> list[float] | None:
    body = json.dumps(
        {
            "contents": [
                {"parts": [{"text": PROMPT + "\n\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))}]}
            ],
        }
    ).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    m = re.search(r"\[.*\]", cleaned, re.S)
    if not m:
        return None
    arr = json.loads(m.group(0))
    out = []
    for item in arr:
        try:
            out.append(max(-1.0, min(1.0, float(item.get("sentiment", 0.0)))))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-limit", type=int, default=200)
    _args = ap.parse_args()  # validated only; --batch-limit not applied upstream

    keys = gemini_keys()
    if not keys:
        print("нет Gemini ключей")
        return 1

    # merge: scored file accumulates; source may still be appended by the collector
    scored_rows = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                r = json.loads(line)
                scored_rows[r["url"]] = r
            except Exception:
                pass
    fresh = {}
    if SRC.exists():
        for line in SRC.read_text().splitlines():
            try:
                r = json.loads(line)
                fresh[r["url"]] = r
            except Exception:
                pass
    # merge source into scored (keep existing scores)
    for url, r in fresh.items():
        if url not in scored_rows:
            scored_rows[url] = r
    rows = list(scored_rows.values())
    todo = [r for r in rows if "sentiment" not in r]
    print(f"всего: {len(rows)}, к оценке: {len(todo)}", flush=True)

    ki = 0
    done = 0
    for i in range(0, len(todo), 8):
        batch = todo[i : i + 8]
        titles = [b["title"] for b in batch]
        scores = None
        for attempt in range(4):
            key = keys[ki % len(keys)]
            ki += 1
            try:
                scores = score_batch(key, titles)
                if scores is not None:
                    break
            except Exception as e:
                wait = 6 + attempt * 8
                print(f"  попытка {attempt + 1} fail: {e} (жду {wait}s)", flush=True)
                time.sleep(wait)
        if scores is None:
            print("  батч не оценён — квота/сеть недоступны, прерываю (resume позже)", flush=True)
            break
        for b, s in zip(batch, scores, strict=False):
            b["sentiment"] = round(s, 3)
            b["label"] = "positive" if s > 0.2 else ("negative" if s < -0.2 else "neutral")
        done += len(batch)
        if done % 40 <= 8:
            print(f"  оценено: {done}/{len(todo)}", flush=True)
        time.sleep(12)  # ~5 батчей/мин (1 рабочий ключ, 15 RPM лимит)

    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pos = sum(1 for r in rows if r.get("sentiment", 0) > 0.2)
    neg = sum(1 for r in rows if r.get("sentiment", 0) < -0.2)
    print(
        f"готово: оценено {done}, всего с сентиментом {pos + neg + sum(1 for r in rows if r.get('label') == 'neutral')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
