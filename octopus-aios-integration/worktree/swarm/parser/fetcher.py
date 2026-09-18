"""HTTP page fetcher with polite delay and size cap."""

from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from swarm.parser.models import ParseResult

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


class Fetcher:
    """Fetch page HTML with size cap, UA rotation, and polite delay."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_bytes: int = 524_288,
        polite_delay: float = 1.0,
        proxy: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._polite_delay = polite_delay
        self._proxy = proxy

    async def fetch_many(self, urls: list[str]) -> list[ParseResult]:
        """Fetch each URL sequentially with polite delay between requests.

        Returns one :class:`ParseResult` per URL with ``raw_text_excerpt``
        populated on success or ``errors`` populated on failure.  The
        ``items`` list is always empty — the caller (extractor) fills it.
        """
        results: list[ParseResult] = []
        for i, url in enumerate(urls):
            result = await self._fetch_one(url)
            results.append(result)
            # polite delay between requests (not after the last one)
            if i < len(urls) - 1 and self._polite_delay > 0:
                await asyncio.sleep(self._polite_delay)
        return results

    async def _fetch_one(self, url: str) -> ParseResult:
        t0 = time.time()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                proxy=self._proxy,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": random.choice(_USER_AGENTS)},
                )
                if resp.status_code >= 400:
                    return ParseResult(
                        source_url=url,
                        errors=[f"HTTP {resp.status_code}"],
                        fetched_at=t0,
                    )
                # Truncate body to max_bytes
                raw = resp.text
                if len(raw) > self._max_bytes:
                    raw = raw[: self._max_bytes]
                return ParseResult(
                    source_url=url,
                    raw_text_excerpt=raw,
                    fetched_at=t0,
                )
        except httpx.TimeoutException:
            return ParseResult(
                source_url=url,
                errors=["timeout"],
                fetched_at=t0,
            )
        except httpx.HTTPError as exc:
            return ParseResult(
                source_url=url,
                errors=[f"fetch_error: {exc}"],
                fetched_at=t0,
            )
        except Exception as exc:  # pragma: no cover
            return ParseResult(
                source_url=url,
                errors=[f"unexpected_error: {exc}"],
                fetched_at=t0,
            )
