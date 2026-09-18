"""Autoglass business domain: catalog, VIN decoder, price comparison.

All data persists through the swarm's MemoryRepository, so it inherits
every redundancy/replication layer the memory facade provides.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swarm.llm.router import LLMRouter
from swarm.media.processor import MediaStore

logger = logging.getLogger(__name__)

# ── VIN Decoder ────────────────────────────────────────────────────────────

# WMI (World Manufacturer Identifier) — первые 3 символа VIN.
# Маппинг расширяемый; достаточно для MVP.
_WMI_MAP: dict[str, tuple[str, str | None]] = {
    # (марка, страна_подсказка)
    "XTA": ("Lada", "Россия"),
    "XTK": ("Lada", "Россия"),
    "Y6D": ("Lada", "Россия"),
    "X7L": ("Renault", "Россия"),
    "X7M": ("Renault", "Россия"),
    "WBA": ("BMW", "Германия"),
    "WBS": ("BMW M", "Германия"),
    "WDB": ("Mercedes-Benz", "Германия"),
    "WDC": ("Mercedes-Benz", "Германия"),
    "WDD": ("Mercedes-Benz", "Германия"),
    "WAU": ("Audi", "Германия"),
    "WVW": ("Volkswagen", "Германия"),
    "WF0": ("Ford", "Германия"),
    "1FA": ("Ford", "США"),
    "1G1": ("Chevrolet", "США"),
    "1GC": ("Chevrolet", "США"),
    "1HD": ("Harley-Davidson", "США"),
    "1HG": ("Honda", "США"),
    "1N4": ("Nissan", "США"),
    "2HG": ("Honda", "Канада"),
    "3FA": ("Ford", "Мексика"),
    "5YJ": ("Tesla", "США"),
    "7AT": ("Tesla", "США"),
    "JTD": ("Toyota", "Япония"),
    "JTE": ("Toyota", "Япония"),
    "JHM": ("Honda", "Япония"),
    "JN1": ("Nissan", "Япония"),
    "KMH": ("Hyundai", "Корея"),
    "KNA": ("Kia", "Корея"),
    "LVS": ("Changan", "Китай"),
    "LFV": ("FAW-Volkswagen", "Китай"),
    "SAL": ("Land Rover", "Великобритания"),
    "SAJ": ("Jaguar", "Великобритания"),
    "ZAR": ("Alfa Romeo", "Италия"),
    "ZFA": ("Fiat", "Италия"),
}

# Год выпуска по 10-му символу VIN (стандарт FMVSS/ISO)
_YEAR_CODE: dict[str, int] = {}
_YEAR_LETTERS = "ABCDEFGHJKLMNPRSTVWXY123456789"
for _i, _ch in enumerate(_YEAR_LETTERS):
    _YEAR_CODE[_ch] = 2010 + _i  # A=2010, B=2011, ... 9=2038
# Добавим старые годы для полноты
_OLD_LETTERS = "ABCDEFGHJKLMNPRSTVWXY123456789"
for _i, _ch in enumerate(_OLD_LETTERS):
    if _ch not in _YEAR_CODE:
        _YEAR_CODE[_ch] = 1980 + _i

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)


@dataclass
class VINInfo:
    """Результат декодирования VIN."""

    vin: str
    make: str | None = None
    country: str | None = None
    year: int | None = None
    valid: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vin": self.vin,
            "make": self.make,
            "country": self.country,
            "year": self.year,
            "valid": self.valid,
            "error": self.error,
        }


def decode_vin(vin: str) -> VINInfo:
    """Декодировать VIN: марка, страна, год выпуска.

    Офлайн-декодер по WMI-таблице + 10-й символ.
    """
    raw = vin.strip().upper()
    if not _VIN_RE.match(raw):
        return VINInfo(vin=raw, valid=False, error="invalid_vin_format")

    wmi = raw[:3]
    make, country = _WMI_MAP.get(wmi, (None, None))

    # Попробуем 2-символьный WMI для расширенных кодов
    if make is None:
        make, country = _WMI_MAP.get(raw[:2], (None, None))  # type: ignore[arg-type]

    year_char = raw[9]
    year = _YEAR_CODE.get(year_char)

    return VINInfo(vin=raw, make=make, country=country, year=year)


# ── Catalog (CRUD) ────────────────────────────────────────────────────────

TABLE_CATALOG = "autoglass_catalog"
TABLE_PRICE_HISTORY = "autoglass_price_history"


@dataclass
class GlassItem:
    """Единица каталога автостёкол."""

    name: str
    glass_type: str = ""  # "лобовое", "боковое", "заднее"
    makes: list[str] = field(default_factory=list)  # совместимые марки
    models: list[str] = field(default_factory=list)  # совместимые модели
    years: list[int] = field(default_factory=list)  # годы выпуска
    oem_code: str = ""  # OEM-код стекла
    price: float = 0.0
    currency: str = "RUB"
    supplier: str = ""
    in_stock: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "glass_type": self.glass_type,
            "makes": list(self.makes),
            "models": list(self.models),
            "years": list(self.years),
            "oem_code": self.oem_code,
            "price": self.price,
            "currency": self.currency,
            "supplier": self.supplier,
            "in_stock": self.in_stock,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GlassItem:
        return cls(
            name=d.get("name", ""),
            glass_type=d.get("glass_type", ""),
            makes=list(d.get("makes") or []),
            models=list(d.get("models") or []),
            years=list(d.get("years") or []),
            oem_code=d.get("oem_code", ""),
            price=float(d.get("price", 0)),
            currency=d.get("currency", "RUB"),
            supplier=d.get("supplier", ""),
            in_stock=bool(d.get("in_stock", True)),
            notes=d.get("notes", ""),
        )


class GlassCatalog:
    """CRUD-обёртка над MemoryRepository для каталога автостёкол."""

    def __init__(self, repository) -> None:
        self._repo = repository

    async def add(self, item: GlassItem, *, tags: list[str] | None = None) -> str:
        """Добавить позицию в каталог. Возвращает ref."""
        tag_list = list(tags or [])
        tag_list.append("autoglass")
        if item.glass_type:
            tag_list.append(f"type:{item.glass_type}")
        for make in item.makes:
            tag_list.append(f"make:{make.lower()}")

        return await self._repo.save(
            data=item.to_dict(),
            table=TABLE_CATALOG,
            tags=tag_list,
            attrs={
                "kind": "glass_item",
                "oem_code": item.oem_code,
                "price": item.price,
                "currency": item.currency,
            },
        )

    async def search(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        glass_type: str | None = None,
        text: str | None = None,
        in_stock: bool | None = None,
        limit: int = 50,
    ) -> list[GlassItem]:
        """Поиск по каталогу."""
        rows = await self._repo.query(
            table=TABLE_CATALOG,
            text=text,
            order_by="attrs._ts:desc",
            limit=limit * 5,
        )

        items: list[GlassItem] = []
        for row in rows:
            item = GlassItem.from_dict(row.data)
            if make and make.lower() not in [m.lower() for m in item.makes]:
                continue
            if glass_type and item.glass_type.lower() != glass_type.lower():
                continue
            if model and model.lower() not in [m.lower() for m in item.models]:
                continue
            if in_stock is not None and item.in_stock != in_stock:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def search_by_vin(self, vin: str, *, limit: int = 20) -> tuple[VINInfo, list[GlassItem]]:
        """Найти стёкла, совместимые с авто по VIN."""
        info = decode_vin(vin)
        if not info.valid or not info.make:
            return info, []

        items = await self.search(make=info.make, limit=limit)

        # Фильтруем по году, если известен
        if info.year:
            compatible = [
                item for item in items
                if not item.years or info.year in item.years
            ]
            # Если по году ничего — вернём всё по марке
            if compatible:
                items = compatible

        return info, items

    async def list_all(self, *, limit: int = 100) -> list[GlassItem]:
        """Все позиции каталога."""
        rows = await self._repo.query(
            table=TABLE_CATALOG,
            order_by="attrs._ts:desc",
            limit=limit,
        )
        return [GlassItem.from_dict(row.data) for row in rows]

    async def count(self) -> int:
        """Количество позиций."""
        return await self._repo.count(table=TABLE_CATALOG)

    async def add_price_snapshot(
        self,
        *,
        source_url: str,
        items: list[dict],
        query: str = "",
    ) -> str:
        """Сохранить снимок цен конкурентов (результат парсера)."""
        return await self._repo.save(
            data={
                "source_url": source_url,
                "items": items,
                "query": query,
                "timestamp": time.time(),
            },
            table=TABLE_PRICE_HISTORY,
            tags=["autoglass", "price_snapshot", "competitor"],
        )

    async def price_history(self, *, limit: int = 20) -> list[dict]:
        """Последние снимки цен конкурентов."""
        rows = await self._repo.query(
            table=TABLE_PRICE_HISTORY,
            order_by="attrs._ts:desc",
            limit=limit,
        )
        return [row.data for row in rows]


# ── OCR Business Processor ───────────────────────────────────────────────

OCR_STRUCTURE_PROMPT = """You are an autoglass inventory assistant. Analyze the following OCR text from a receipt or invoice.
Extract glass products into a JSON array of objects.

Field mapping:
- name: Full product name (e.g. "Лобовое стекло BMW X5 E70")
- glass_type: "лобовое", "боковое" or "заднее"
- makes: List of car makes (e.g. ["BMW", "Audi"])
- models: List of models (e.g. ["X5", "A6"])
- years: List of integers (years) if mentioned
- price: Float value
- currency: "RUB", "USD", etc.
- supplier: Name of vendor/supplier if mentioned

OCR Text:
{text}

Return ONLY the JSON array, nothing else."""

class AutoglassOCRProcessor:
    """Processes images of receipts/invoices into GlassCatalog items using LLM."""

    def __init__(self, catalog: GlassCatalog, media_store: MediaStore, llm: LLMRouter) -> None:
        self.catalog = catalog
        self.media_store = media_store
        self.llm = llm

    async def process_file(self, path: str | Path) -> list[GlassItem]:
        """Import image, run OCR, use LLM to structure, and save to catalog."""
        # 1. Import and OCR
        ref, meta = await self.media_store.import_file(path, ocr=True)
        if not meta.ocr_text:
            logger.warning("No OCR text extracted from %s", path)
            return []

        # 2. Extract items via LLM
        items_data = await self._extract_items(meta.ocr_text)
        
        # 3. Save to catalog
        imported_items = []
        for data in items_data:
            item = GlassItem.from_dict(data)
            await self.catalog.add(item, tags=["ocr_import", f"source:{ref}"])
            imported_items.append(item)
            
        return imported_items

    async def _extract_items(self, text: str) -> list[dict]:
        """Ask LLM to structure OCR text into JSON."""
        prompt = OCR_STRUCTURE_PROMPT.format(text=text)
        raw = await self.llm.complete([{"role": "user", "content": prompt}])
        
        try:
            # Cleanup potential markdown fences
            clean_raw = raw.strip()
            if clean_raw.startswith("```json"):
                clean_raw = clean_raw[7:].strip()
            if clean_raw.endswith("```"):
                clean_raw = clean_raw[:-3].strip()
            
            data = json.loads(clean_raw)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse LLM OCR JSON: %s", exc)
            return []
