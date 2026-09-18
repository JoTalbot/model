"""HTML text extraction + LLM structuring into ParsedItems."""

from __future__ import annotations

import json
import logging

from swarm.parser.models import ParsedItem, ParseResult

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
I scraped the following text from {url}:

{text}

Extract ALL product offers you can find.  Return ONLY valid JSON (no markdown fences, no commentary) matching this exact schema:

{{
  "items": [
    {{
      "name": "string",
      "price": "string or null",
      "currency": "string or null",
      "shop": "string or null",
      "url": "string or null",
      "in_stock": true | false | null
    }}
  ]
}}

If no products are found, return {{"items": []}}.
"""


def extract_text_from_html(html: str, *, max_chars: int = 4000) -> str:
    """Use selectolax to pull visible text from *html*, truncated to *max_chars*."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    if tree.body:
        text = tree.body.text(separator="\n", strip=True)
    else:
        text = html
    return text[:max_chars]


class Extractor:
    """Extract structured items from raw HTML via LLM."""

    def __init__(
        self,
        llm,
        *,
        max_text_chars: int = 4000,
    ) -> None:
        self._llm = llm
        self._max_text_chars = max_text_chars

    async def extract(self, result: ParseResult) -> ParseResult:
        """Fill ``result.items`` by running selectolax + LLM on the fetched HTML.

        Mutates and returns *result*.  If the page had fetch errors (no
        ``raw_text_excerpt``), the result is returned as-is.
        """
        if not result.raw_text_excerpt:
            return result

        # 1. extract visible text
        text = extract_text_from_html(
            result.raw_text_excerpt,
            max_chars=self._max_text_chars,
        )
        if not text.strip():
            result.errors.append("empty_body_text")
            return result

        # keep a short excerpt for the final output
        result.raw_text_excerpt = text[:500]

        # 2. ask LLM
        prompt = _EXTRACTION_PROMPT.format(url=result.source_url, text=text)
        try:
            raw_response = await self._llm.complete(
                [{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", result.source_url, exc)
            result.errors.append(f"llm_call_failed: {exc}")
            return result

        # 3. parse JSON
        items = _parse_llm_json(raw_response)
        if items is None:
            result.errors.append("llm_json_parse_failed")
            logger.warning(
                "LLM returned unparseable JSON for %s: %.200s",
                result.source_url,
                raw_response,
            )
        else:
            result.items = items

        return result


def _parse_llm_json(raw: str) -> list[ParsedItem] | None:
    """Try to parse LLM output as a list of ParsedItem.

    Returns *None* if JSON is unparseable.
    """
    # Strip potential markdown fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # remove opening fence (possibly ```json)
        first_nl = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            return None
    elif isinstance(data, list):
        raw_items = data
    else:
        return None

    items: list[ParsedItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        items.append(ParsedItem.from_dict(entry))
    return items
