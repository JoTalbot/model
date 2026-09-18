"""Tests for swarm.parser.extractor."""

import json
from unittest.mock import AsyncMock

import pytest

from swarm.parser.extractor import (
    Extractor,
    _parse_llm_json,
    extract_text_from_html,
)
from swarm.parser.models import ParseResult


class TestExtractTextFromHtml:
    def test_basic(self):
        html = "<html><body><p>Hello world</p></body></html>"
        text = extract_text_from_html(html)
        assert "Hello world" in text

    def test_strips_tags(self):
        html = "<html><body><b>Bold</b> <i>italic</i></body></html>"
        text = extract_text_from_html(html)
        assert "<b>" not in text
        assert "Bold" in text

    def test_truncation(self):
        html = "<html><body>" + "A" * 10_000 + "</body></html>"
        text = extract_text_from_html(html, max_chars=100)
        assert len(text) <= 100

    def test_no_body(self):
        # selectolax falls back to raw html
        html = "<html><head><title>T</title></head></html>"
        text = extract_text_from_html(html)
        assert isinstance(text, str)

    def test_empty(self):
        text = extract_text_from_html("")
        assert isinstance(text, str)


class TestParseLlmJson:
    def test_valid_items(self):
        raw = json.dumps({
            "items": [
                {"name": "Glass A", "price": "5000", "currency": "RUB"},
                {"name": "Glass B", "price": "3000"},
            ]
        })
        items = _parse_llm_json(raw)
        assert items is not None
        assert len(items) == 2
        assert items[0].name == "Glass A"
        assert items[0].price == "5000"

    def test_valid_with_markdown_fences(self):
        raw = '```json\n{"items": [{"name": "X", "price": "1"}]}\n```'
        items = _parse_llm_json(raw)
        assert items is not None
        assert len(items) == 1
        assert items[0].name == "X"

    def test_valid_bare_list(self):
        raw = json.dumps([{"name": "Y", "price": "2"}])
        items = _parse_llm_json(raw)
        assert items is not None
        assert len(items) == 1

    def test_empty_items(self):
        raw = json.dumps({"items": []})
        items = _parse_llm_json(raw)
        assert items is not None
        assert items == []

    def test_invalid_json(self):
        assert _parse_llm_json("not json at all") is None

    def test_wrong_structure(self):
        assert _parse_llm_json(json.dumps({"data": "x"})) is None

    def test_non_dict_items(self):
        raw = json.dumps({"items": ["string", 123]})
        items = _parse_llm_json(raw)
        assert items is not None
        assert items == []  # non-dict entries skipped

    def test_items_without_name(self):
        raw = json.dumps({"items": [{"price": "100"}]})
        items = _parse_llm_json(raw)
        assert items is not None
        assert items == []  # name is required

    def test_number_json(self):
        assert _parse_llm_json("42") is None

    def test_items_with_nulls(self):
        raw = json.dumps({
            "items": [
                {"name": "A", "price": None, "in_stock": None},
            ]
        })
        items = _parse_llm_json(raw)
        assert items is not None
        assert items[0].price is None
        assert items[0].in_stock is None


class TestExtractor:
    @pytest.mark.asyncio
    async def test_extract_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=json.dumps({
            "items": [{"name": "Glass", "price": "5000", "currency": "RUB"}]
        }))

        extractor = Extractor(llm)
        result = ParseResult(
            source_url="https://shop.com",
            raw_text_excerpt="<html><body><p>Glass 5000 RUB</p></body></html>",
        )

        result = await extractor.extract(result)
        assert len(result.items) == 1
        assert result.items[0].name == "Glass"
        assert result.items[0].price == "5000"
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_extract_llm_returns_bad_json(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="I cannot parse this page sorry")

        extractor = Extractor(llm)
        result = ParseResult(
            source_url="https://shop.com",
            raw_text_excerpt="<html><body><p>some text</p></body></html>",
        )

        result = await extractor.extract(result)
        assert result.items == []
        assert "llm_json_parse_failed" in result.errors

    @pytest.mark.asyncio
    async def test_extract_llm_raises(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("API down"))

        extractor = Extractor(llm)
        result = ParseResult(
            source_url="https://shop.com",
            raw_text_excerpt="<html><body><p>text</p></body></html>",
        )

        result = await extractor.extract(result)
        assert result.items == []
        assert any("llm_call_failed" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_extract_empty_html(self):
        """Empty raw_text_excerpt → skip extraction."""
        llm = AsyncMock()
        extractor = Extractor(llm)
        result = ParseResult(
            source_url="https://shop.com",
            raw_text_excerpt="",
            errors=["HTTP 500"],
        )

        result = await extractor.extract(result)
        assert result.items == []
        # Should not have called LLM
        llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_blank_body_text(self):
        """HTML that parses to blank text."""
        llm = AsyncMock()
        extractor = Extractor(llm)
        result = ParseResult(
            source_url="https://shop.com",
            raw_text_excerpt="<html><body>   </body></html>",
        )

        result = await extractor.extract(result)
        assert "empty_body_text" in result.errors
        llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_text_excerpt_truncated_to_500(self):
        """After extraction, raw_text_excerpt is truncated to 500 chars."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value='{"items": []}')

        extractor = Extractor(llm)
        long_body = "<html><body>" + "A" * 2000 + "</body></html>"
        result = ParseResult(
            source_url="https://x.com",
            raw_text_excerpt=long_body,
        )

        result = await extractor.extract(result)
        assert len(result.raw_text_excerpt) <= 500
