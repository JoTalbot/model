"""Web Parser Pipeline — orchestrator that ties resolver, fetcher, and extractor."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from swarm.parser.extractor import Extractor
from swarm.parser.fetcher import Fetcher
from swarm.parser.models import ParseResult
from swarm.parser.resolver import Resolver

logger = logging.getLogger(__name__)


def _looks_like_url(text: str) -> bool:
    """Return True if *text* looks like a direct HTTP(S) URL."""
    text = text.strip()
    if not text.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(text)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


class WebParserPipeline:
    """End-to-end pipeline: input → resolve → fetch → extract → results."""

    def __init__(
        self,
        llm,
        *,
        resolver: Resolver | None = None,
        fetcher: Fetcher | None = None,
        extractor: Extractor | None = None,
        fetch_timeout: float = 15.0,
        max_response_bytes: int = 524_288,
        max_text_chars: int = 4000,
        polite_delay: float = 1.0,
        proxy: str | None = None,
    ) -> None:
        self.resolver = resolver or Resolver(timeout=fetch_timeout, proxy=proxy)
        self.fetcher = fetcher or Fetcher(
            timeout=fetch_timeout,
            max_bytes=max_response_bytes,
            polite_delay=polite_delay,
            proxy=proxy,
        )
        self.extractor = extractor or Extractor(
            llm,
            max_text_chars=max_text_chars,
        )

    async def run(
        self,
        input_text: str,
        *,
        search: bool = False,
        limit: int = 3,
    ) -> list[ParseResult]:
        """Run the full pipeline.

        Parameters
        ----------
        input_text:
            A URL (when *search* is False) or a free-text query (when True).
        search:
            If True, resolve *input_text* as a search query first.
        limit:
            Maximum number of URLs to process (applies to search mode).

        Returns
        -------
        list[ParseResult]
            One result per URL processed, never raises on single-URL failure.
        """
        limit = max(1, min(limit, 10))  # hard cap

        # 1. Build URL list
        if search:
            urls = await self.resolver.resolve(input_text, limit=limit)
            if not urls:
                return [
                    ParseResult(
                        source_url="(search)",
                        errors=[f"resolver_returned_no_urls_for: {input_text}"],
                    )
                ]
        else:
            if _looks_like_url(input_text):
                urls = [input_text.strip()]
            else:
                # Not a URL and search not requested — hint the user
                from click import ClickException

                raise ClickException(
                    f"Input does not look like a URL: {input_text!r}. "
                    "Pass --search to treat it as a search query, "
                    "or provide a full http(s) URL."
                )

        # 2. Fetch
        fetch_results = await self.fetcher.fetch_many(urls)

        # 3. Extract
        final: list[ParseResult] = []
        for result in fetch_results:
            try:
                result = await self.extractor.extract(result)
            except Exception as exc:  # pragma: no cover
                result.errors.append(f"extractor_error: {exc}")
            final.append(result)

        return final
