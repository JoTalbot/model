from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lower-case, unicode-friendly word tokenisation."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t]


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

@dataclass
class HashingEmbedder:
    """Hashing-trick embedder: each token bumps a fixed coordinate."""
    dims: int = 256

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for tok in tokenize(text):
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:8], "big") % self.dims
            sign = 1.0 if (digest[8] & 0x01) == 0 else -1.0
            vec[idx] += sign
        return _l2_normalise(vec)


@dataclass
class TfIdfEmbedder:
    """Classic TF-IDF embedder."""
    vocabulary: dict[str, int] = field(default_factory=dict)
    idf: list[float] = field(default_factory=list)

    def fit(self, corpus: Iterable[str]) -> TfIdfEmbedder:
        docs = [tokenize(t) for t in corpus]
        df: dict[str, int] = {}
        for doc in docs:
            for tok in set(doc):
                df[tok] = df.get(tok, 0) + 1
        n = max(1, len(docs))
        self.vocabulary = {tok: i for i, tok in enumerate(sorted(df.keys()))}
        self.idf = [0.0] * len(self.vocabulary)
        for tok, i in self.vocabulary.items():
            self.idf[i] = math.log((1 + n) / (1 + df[tok])) + 1.0
        return self

    def embed(self, text: str) -> list[float]:
        if not self.vocabulary:
            return []
        vec = [0.0] * len(self.vocabulary)
        toks = tokenize(text)
        if not toks:
            return vec
        tf: dict[str, int] = {}
        for tok in toks:
            tf[tok] = tf.get(tok, 0) + 1
        n_toks = len(toks)
        for tok, cnt in tf.items():
            idx = self.vocabulary.get(tok)
            if idx is None:
                continue
            vec[idx] = (cnt / n_toks) * self.idf[idx]
        return _l2_normalise(vec)


@dataclass
class OllamaEmbedder:
    """Embedder that uses local Ollama API with L2 normalization."""
    model: str = "nomic-embed-text"
    base_url: str = "http://127.0.0.1:11434/api/embeddings"

    def embed(self, text: str) -> list[float]:
        try:
            import json, urllib.request
            data = json.dumps({"model": self.model, "prompt": text}).encode()
            req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as f:
                vec = json.loads(f.read())["embedding"]
                return _l2_normalise(vec)
        except Exception as e:
            import logging
            logging.getLogger("swarm.memory.vector_store").error("Ollama embedding failed: %s", e)
            return []


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _l2_normalise(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n == 0:
        return vec
    return [x / n for x in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length L2-normalised vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

@dataclass
class VectorRecord:
    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorMatch:
    record: VectorRecord
    score: float


class VectorStore:
    """In-process vector store with cosine search and optional persistence."""

    def __init__(
        self,
        embedder: HashingEmbedder | TfIdfEmbedder | OllamaEmbedder | None = None,
    ) -> None:
        self._embedder = embedder or HashingEmbedder()
        self._records: dict[str, VectorRecord] = {}

    @property
    def embedder(self):
        return self._embedder

    def add(self, *, id: str, text: str, metadata: dict[str, Any] | None = None) -> VectorRecord:
        vec = self._embedder.embed(text)
        rec = VectorRecord(id=id, text=text, vector=vec, metadata=dict(metadata or {}))
        self._records[id] = rec
        return rec

    def remove(self, id: str) -> bool:
        return self._records.pop(id, None) is not None

    def rebuild_tfidf(self) -> "VectorStore":
        """Переучивает TF-IDF эмбеддер на всех записях и пересчитывает векторы."""
        if isinstance(self._embedder, TfIdfEmbedder):
            self._embedder.fit(r.text for r in self._records.values())
            for rec in self._records.values():
                rec.vector = self._embedder.embed(rec.text)
        return self

    def __len__(self) -> int:
        return len(self._records)

    def all(self) -> list[VectorRecord]:
        return list(self._records.values())

    def get(self, id: str) -> VectorRecord | None:
        return self._records.get(id)

    def search(self, query: str, *, top_k: int = 5) -> list[VectorMatch]:
        qv = self._embedder.embed(query)
        if not qv:
            return []
        scored: list[VectorMatch] = []
        for rec in self._records.values():
            score = cosine(qv, rec.vector)
            if score > 0:
                scored.append(VectorMatch(record=rec, score=score))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[: max(0, top_k)]


# ---------------------------------------------------------------------------
# Persistence over MemoryRepository
# ---------------------------------------------------------------------------

class PersistentVectorIndex:
    TABLE = "vector_index"

    @staticmethod
    def encode(rec) -> str:
        """Детерминированная сериализация записи (стабильная для индекса)."""
        payload = {
            "id": rec.id,
            "text": rec.text,
            "vector": list(rec.vector),
            "metadata": dict(getattr(rec, "metadata", {}) or {}),
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def __init__(self, store: VectorStore, repository) -> None:
        self._store = store
        self._repo = repository

    async def save(self, record: VectorRecord, *, attrs: dict[str, Any] | None = None) -> str:
        data = {
            "id": record.id,
            "text": record.text,
            "vector": record.vector,
            "metadata": record.metadata,
        }
        merged = {
            "vector_id": record.id,
            "dims": len(record.vector),
            **(attrs or {}),
        }
        return await self._repo.save(
            data=data, table=self.TABLE, tags=["vector"], attrs=merged
        )

    async def load_all(self) -> int:
        rows = await self._repo.query(table=self.TABLE, limit=10000)
        n = 0
        import logging; logger = logging.getLogger("swarm.memory.vector_store"); logger.info("Loading vectors from table %s", self.TABLE)
        for row in rows:
            d = row.data
            try:
                rec = VectorRecord(
                    id=str(d["id"]),
                    text=str(d.get("text", "")),
                    vector=list(d.get("vector") or []),
                    metadata=dict(d.get("metadata") or {}),
                )
            except KeyError:
                continue
            self._store._records[rec.id] = rec
            logger.info(" - Loaded vector ID: %s", rec.id)
            n += 1
        return n
