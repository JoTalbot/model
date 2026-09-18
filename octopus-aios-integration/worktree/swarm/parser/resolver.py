"""URL resolver: free-text query → list of URLs via search engines."""

from __future__ import annotations

import logging
import random
from urllib.parse import quote_plus, urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

_SKIP_DOMAINS = frozenset({
    "yandex.ru", "yandex.com", "ya.ru",
    "google.com", "google.ru",
    "duckduckgo.com",
    "bing.com",
    "mail.ru",
    "youtube.com",
})


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _is_organic_url(href: str) -> bool:
    """Return True if *href* looks like a real external result link."""
    if not href or not href.startswith(("http://", "https://")):
        return False
    try:
        host = urlparse(href).hostname or ""
    except Exception:
        return False
    # strip www. for comparison
    bare = host.lower().removeprefix("www.")
    return bare not in _SKIP_DOMAINS


def _extract_links_from_html(html: str, limit: int) -> list[str]:
    """Extract organic links from a search-engine result page using selectolax."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    seen: set[str] = set()
    result: list[str] = []

    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not _is_organic_url(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        result.append(href)
        if len(result) >= limit:
            break

    return result


class Resolver:
    """Resolve a free-text query into a list of web URLs.

    Primary: Yandex search HTML.
    Fallback: DuckDuckGo HTML lite.
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        proxy: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._proxy = proxy

    async def resolve(self, query: str, *, limit: int = 3) -> list[str]:
        """Return up to *limit* organic URLs for *query*."""
        urls = await self._try_yandex(query, limit=limit)
        if urls:
            return urls
        logger.info("Yandex yielded 0 results; falling back to DuckDuckGo")
        return await self._try_ddg(query, limit=limit)

    # -- internals --

    async def _fetch(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                proxy=self._proxy,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": _random_ua()},
                )
                if resp.status_code >= 400:
                    logger.warning("Search fetch %s returned HTTP %s", url, resp.status_code)
                    return None
                return resp.text
        except httpx.HTTPError as exc:
            logger.warning("Search fetch error for %s: %s", url, exc)
            return None

    async def _try_yandex(self, query: str, *, limit: int) -> list[str]:
        url = f"https://yandex.ru/search/?text={quote_plus(query)}"
        html = await self._fetch(url)
        if html is None:
            return []
        return _extract_links_from_html(html, limit)

    async def _try_ddg(self, query: str, *, limit: int) -> list[str]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        html = await self._fetch(url)
        if html is None:
            return []
        return _extract_links_from_html(html, limit)
