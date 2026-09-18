"""Data models for the web parser pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedItem:
    """A single product/offer extracted from a web page."""

    name: str
    price: str | None = None
    currency: str | None = None
    shop: str | None = None
    url: str | None = None
    in_stock: bool | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "currency": self.currency,
            "shop": self.shop,
            "url": self.url,
            "in_stock": self.in_stock,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ParsedItem:
        return cls(
            name=d.get("name", ""),
            price=d.get("price"),
            currency=d.get("currency"),
            shop=d.get("shop"),
            url=d.get("url"),
            in_stock=d.get("in_stock"),
        )


@dataclass
class ParseResult:
    """Result of parsing a single URL."""

    source_url: str
    items: list[ParsedItem] = field(default_factory=list)
    raw_text_excerpt: str = ""
    errors: list[str] = field(default_factory=list)
    fetched_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "items": [item.to_dict() for item in self.items],
            "raw_text_excerpt": self.raw_text_excerpt,
            "errors": list(self.errors),
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ParseResult:
        return cls(
            source_url=d.get("source_url", ""),
            items=[ParsedItem.from_dict(i) for i in d.get("items", [])],
            raw_text_excerpt=d.get("raw_text_excerpt", ""),
            errors=list(d.get("errors", [])),
            fetched_at=d.get("fetched_at", 0.0),
        )
