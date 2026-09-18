#!/usr/bin/env python3
"""Bounded-read-only external data fetcher for Octopus.

Integrates free external APIs:
- CoinGecko: crypto prices
- Wikipedia: knowledge/fact-checking
- OpenAlex: academic papers
- ip-api.com: IP geolocation
- crt.sh: SSL certificate monitoring
- Open-Meteo: weather data

Read-only by default. Caches results in experience/.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(os.path.expanduser("~/agents/-Octopus"))
EXPERIENCE_DIR = BASE / "experience"
CACHE_DIR = BASE / "logs" / "external_cache"
CACHE_TTL_SECONDS = 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _get_cached(key: str) -> Dict[str, Any] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        ts = datetime.fromisoformat(data.get("_ts", ""))
        if (datetime.now(timezone.utc) - ts).total_seconds() > CACHE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _set_cache(key: str, value: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    value["_ts"] = _now()
    _cache_path(key).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def _get_json(url: str, timeout: int = 10) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Octopus-Agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "data": json.loads(r.read().decode())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def fetch_coingecko(ids: str = "bitcoin,ethereum,solana", vs_currency: str = "usd") -> Dict[str, Any]:
    key = f"coingecko_{ids}_{vs_currency}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={urllib.parse.quote(ids)}&vs_currencies={urllib.parse.quote(vs_currency)}"
    result = _get_json(url)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def fetch_wikipedia(title: str, lang: str = "en") -> Dict[str, Any]:
    key = f"wiki_{lang}_{title}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    result = _get_json(url)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def fetch_openalex(search: str, per_page: int = 5) -> Dict[str, Any]:
    key = f"openalex_{search}_{per_page}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(search)}&per-page={per_page}"
    result = _get_json(url)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def fetch_ip_info(ip: str = "") -> Dict[str, Any]:
    key = f"ipapi_{ip or 'me'}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?fields=status,message,country,regionName,city,isp,org,as,query"
    result = _get_json(url)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def fetch_crt_sh(domain: str) -> Dict[str, Any]:
    key = f"crt_{domain}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"https://crt.sh/?q={urllib.parse.quote(domain)}&output=json"
    result = _get_json(url, timeout=15)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def fetch_open_meteo(lat: float = 50.11, lon: float = 8.68, hours: int = 12) -> Dict[str, Any]:
    key = f"meteo_{lat}_{lon}_{hours}"
    cached = _get_cached(key)
    if cached:
        return cached
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&forecast_hours={hours}&current_weather=true"
    result = _get_json(url)
    if result.get("ok"):
        _set_cache(key, result)
    return result


def run(source: str = "all") -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    score = 1000

    if source in ("all", "crypto"):
        results["coingecko"] = fetch_coingecko()
        if not results["coingecko"].get("ok"):
            score -= 20

    if source in ("all", "wiki"):
        results["wikipedia"] = {
            "octopus": fetch_wikipedia("Octopus"),
            "ai_agent": fetch_wikipedia("Artificial_intelligence_agent"),
        }
        failed = sum(1 for v in results["wikipedia"].values() if not v.get("ok"))
        score -= failed * 10

    if source in ("all", "research"):
        results["openalex"] = fetch_openalex("autonomous agents", 5)
        if not results["openalex"].get("ok"):
            score -= 10

    if source in ("all", "network"):
        results["ipapi"] = fetch_ip_info()
        if not results["ipapi"].get("ok"):
            score -= 10

    if source in ("all", "ssl"):
        results["crt_sh"] = fetch_crt_sh("octopus-production-71fe.up.railway.app")
        if not results["crt_sh"].get("ok"):
            score -= 10

    if source in ("all", "weather"):
        results["open_meteo"] = fetch_open_meteo()
        if not results["open_meteo"].get("ok"):
            score -= 10

    grade = "S" if score >= 950 else "A" if score >= 900 else "B" if score >= 800 else "C" if score >= 600 else "D" if score >= 400 else "F"
    return {
        "skill": "octopus-external-data",
        "timestamp": _now(),
        "score": score,
        "grade": grade,
        "status": "healthy" if grade in {"S", "A"} else "degraded" if grade in {"B", "C"} else "critical",
        "results": results,
    }


if __name__ == "__main__":
    import sys
    payload = run(sys.argv[1] if len(sys.argv) > 1 else "all")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
