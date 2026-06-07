"""RAG service tests — jurisdiction filtering + payer filtering."""
from __future__ import annotations

import pytest

from pa_guard.core.config import Jurisdiction
from pa_guard.services.rag import HashEmbedder, PolicyCorpus

pytestmark = pytest.mark.asyncio


async def test_search_returns_us_evidence_for_us_query() -> None:
    corpus = PolicyCorpus()
    results = corpus.search(
        "lumbar epidural steroid injection medical necessity",
        jurisdiction=Jurisdiction.US_STATE,
        top_k=3,
    )
    assert results
    assert all(
        Jurisdiction.US_FEDERAL.value in [t.value if hasattr(t, "value") else t for t in e.jurisdiction_tags]
        or Jurisdiction.US_STATE.value in [t.value if hasattr(t, "value") else t for t in e.jurisdiction_tags]
        for e in results
    )


async def test_uk_query_excludes_us_only_docs() -> None:
    corpus = PolicyCorpus()
    results = corpus.search(
        "specialised commissioning prior authorisation",
        jurisdiction=Jurisdiction.UK,
        top_k=5,
    )
    assert results
    for e in results:
        tags = {t.value if hasattr(t, "value") else t for t in e.jurisdiction_tags}
        assert Jurisdiction.UK.value in tags


async def test_canada_query_returns_canadian_docs() -> None:
    corpus = PolicyCorpus()
    results = corpus.search(
        "specialty drug prior therapy failures",
        jurisdiction=Jurisdiction.CA_PROVINCE,
        top_k=3,
    )
    assert results
    for e in results:
        tags = {t.value if hasattr(t, "value") else t for t in e.jurisdiction_tags}
        assert Jurisdiction.CA_FEDERAL.value in tags or Jurisdiction.CA_PROVINCE.value in tags


async def test_payer_filter_narrows_results() -> None:
    corpus = PolicyCorpus()
    results = corpus.search(
        "lumbar epidural steroid",
        jurisdiction=Jurisdiction.US_STATE,
        payer_id="anthem",
        top_k=5,
    )
    if results:
        assert all(e.payer_id in {"anthem", None} for e in results)


async def test_add_document_is_searchable() -> None:
    corpus = PolicyCorpus()
    corpus.add_document(
        source="Custom payer ABC — denial reason X",
        jurisdictions=(Jurisdiction.US_FEDERAL,),
        payer_id="abc",
        excerpt="custom payer abc requires documented failure of step therapy for biologics",
    )
    results = corpus.search(
        "custom payer abc step therapy",
        jurisdiction=Jurisdiction.US_FEDERAL,
        top_k=2,
    )
    assert any("Custom payer ABC" in e.source for e in results)


async def test_embedder_is_deterministic() -> None:
    e = HashEmbedder(dim=64)
    v1 = e.embed("hello world prior authorization")
    v2 = e.embed("hello world prior authorization")
    assert v1 == v2
