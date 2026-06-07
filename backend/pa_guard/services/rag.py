"""Policy-research RAG service.

This module gives `PolicyResearcherAgent` a stable, jurisdiction-aware
retrieval surface today, and ships a seam where a real pgvector + sentence
embedder is dropped in for production.

Phase 1 ships:
- A small **in-memory corpus** seeded with representative payer / clinical
  policy snippets across the supported jurisdictions.
- A **deterministic embedder** (`HashEmbedder`) so retrieval is reproducible
  in tests without pulling a heavy ML dependency.
- A **jurisdiction filter** so US-state PAs never get pulled into Canadian
  or UK rule snippets and vice versa.

Phase 2/3 plug-in points:
- `Embedder` protocol → replace with a sentence-transformers / OpenAI
  embedder.
- `VectorIndex` protocol → replace with pgvector.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from ..core.config import Jurisdiction
from ..core.models import PolicyEvidence

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class Embedder(Protocol):
    """Returns a fixed-dimension float vector for a string."""

    dim: int

    def embed(self, text: str) -> list[float]: ...


class VectorIndex(Protocol):
    def add(self, doc_id: str, vector: list[float], metadata: dict) -> None: ...
    def search(self, vector: list[float], *, top_k: int) -> list[tuple[str, float, dict]]: ...


# ---------------------------------------------------------------------------
# Deterministic embedder (no ML deps)
# ---------------------------------------------------------------------------

class HashEmbedder:
    """Token-hash bag-of-words embedder.

    Tokenizes lowercase, hashes each token into one of `dim` buckets, then
    L2-normalizes. Good enough for tests + the Phase 1 demo corpus; replace
    with a real embedder before production traffic.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _tokenize(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "big")
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0:
            v = [x / norm for x in v]
        return v


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if t]


# ---------------------------------------------------------------------------
# In-memory cosine index
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    doc_id: str
    vector: list[float]
    metadata: dict


class InMemoryIndex:
    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def add(self, doc_id: str, vector: list[float], metadata: dict) -> None:
        self._entries.append(_Entry(doc_id=doc_id, vector=vector, metadata=metadata))

    def search(
        self, vector: list[float], *, top_k: int
    ) -> list[tuple[str, float, dict]]:
        scored = [
            (e.doc_id, _cosine(vector, e.vector), e.metadata) for e in self._entries
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    # Both vectors are L2-normalized by HashEmbedder, so cosine = dot.
    return sum(x * y for x, y in zip(a, b, strict=False))


# ---------------------------------------------------------------------------
# Seed corpus — representative slice across jurisdictions / payers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SeedDoc:
    source: str
    jurisdictions: tuple[Jurisdiction, ...]
    payer_id: str | None
    excerpt: str
    citation_url: str | None = None


_SEED_DOCS: tuple[_SeedDoc, ...] = (
    _SeedDoc(
        source="CMS NCD 220.6 — PET imaging for oncology",
        jurisdictions=(Jurisdiction.US_FEDERAL, Jurisdiction.US_STATE),
        payer_id="cms-medicare",
        excerpt=(
            "Coverage for PET imaging is provided for initial treatment "
            "strategy and subsequent treatment strategy in oncologic conditions. "
            "Medical necessity must be documented per NCD 220.6."
        ),
    ),
    _SeedDoc(
        source="Anthem CG-MED-67 — Lumbar epidural steroid injection",
        jurisdictions=(Jurisdiction.US_FEDERAL, Jurisdiction.US_STATE),
        payer_id="anthem",
        excerpt=(
            "Lumbar transforaminal epidural steroid injections (CPT 64483) are "
            "considered medically necessary when conservative therapy of at "
            "least 4 weeks has failed for radicular pain confirmed by imaging."
        ),
    ),
    _SeedDoc(
        source="UnitedHealthcare — Step therapy biologics",
        jurisdictions=(Jurisdiction.US_FEDERAL, Jurisdiction.US_STATE),
        payer_id="uhc",
        excerpt=(
            "Biologic agents require documented failure of at least two "
            "conventional DMARDs prior to authorization unless contraindicated."
        ),
    ),
    _SeedDoc(
        source="Ontario INESSS — Specialty drug PA",
        jurisdictions=(Jurisdiction.CA_FEDERAL, Jurisdiction.CA_PROVINCE),
        payer_id="ohip",
        excerpt=(
            "Specialty drug claims require prescriber attestation of medical "
            "necessity and documented prior therapy failures."
        ),
    ),
    _SeedDoc(
        source="NHS England — Specialised commissioning PA",
        jurisdictions=(Jurisdiction.UK,),
        payer_id="nhs-england",
        excerpt=(
            "Prior authorization for specialised commissioning services "
            "requires multidisciplinary team confirmation and adherence to "
            "the relevant clinical commissioning policy."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PolicyCorpus:
    """Jurisdiction-aware retrieval over a payer / clinical policy corpus."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        index: VectorIndex | None = None,
    ) -> None:
        self._embedder = embedder or HashEmbedder()
        self._index = index or InMemoryIndex()
        self._docs: dict[str, _SeedDoc] = {}
        self._seed()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def _seed(self) -> None:
        for doc in _SEED_DOCS:
            doc_id = str(uuid4())
            self._docs[doc_id] = doc
            vector = self._embedder.embed(doc.excerpt + " " + doc.source)
            self._index.add(
                doc_id,
                vector,
                metadata={
                    "jurisdictions": [j.value for j in doc.jurisdictions],
                    "payer_id": doc.payer_id,
                },
            )

    def add_document(
        self,
        *,
        source: str,
        jurisdictions: tuple[Jurisdiction, ...],
        payer_id: str | None,
        excerpt: str,
        citation_url: str | None = None,
    ) -> str:
        doc = _SeedDoc(
            source=source,
            jurisdictions=jurisdictions,
            payer_id=payer_id,
            excerpt=excerpt,
            citation_url=citation_url,
        )
        doc_id = str(uuid4())
        self._docs[doc_id] = doc
        vector = self._embedder.embed(excerpt + " " + source)
        self._index.add(
            doc_id,
            vector,
            metadata={
                "jurisdictions": [j.value for j in jurisdictions],
                "payer_id": payer_id,
            },
        )
        return doc_id

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        jurisdiction: Jurisdiction,
        payer_id: str | None = None,
        top_k: int = 5,
    ) -> list[PolicyEvidence]:
        if not query.strip():
            return []
        qv = self._embedder.embed(query)
        # Over-fetch then filter post-hoc — simpler than indexing per filter.
        raw = self._index.search(qv, top_k=top_k * 4)
        out: list[PolicyEvidence] = []
        for doc_id, sim, meta in raw:
            if jurisdiction.value not in meta["jurisdictions"]:
                continue
            if payer_id and meta.get("payer_id") and meta["payer_id"] != payer_id:
                continue
            doc = self._docs[doc_id]
            out.append(
                PolicyEvidence(
                    source=doc.source,
                    jurisdiction_tags=list(doc.jurisdictions),
                    payer_id=doc.payer_id,
                    excerpt=doc.excerpt,
                    similarity=max(0.0, min(1.0, sim)),
                    citation_url=doc.citation_url,
                )
            )
            if len(out) >= top_k:
                break
        return out


__all__ = ["Embedder", "HashEmbedder", "InMemoryIndex", "PolicyCorpus", "VectorIndex"]
