"""Tests for the Phase 5 PA registry (in-memory + SQLite SqlPARegistry)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pa_guard.storage.pa_registry import InMemoryPARegistry, SqlPARegistry

pytestmark = pytest.mark.asyncio


def _payload(rid: str, status: str = "submitted") -> dict:
    return {
        "status": status,
        "pa_request": {"meta": {"request_id": rid}},
    }


# ---------------------------------------------------------------------------
# InMemoryPARegistry
# ---------------------------------------------------------------------------

async def test_in_memory_put_get_roundtrip() -> None:
    reg = InMemoryPARegistry()
    rid = uuid4()
    await reg.put(rid, _payload(str(rid)))
    out = await reg.get(rid)
    assert out is not None
    assert out["pa_request"]["meta"]["request_id"] == str(rid)


async def test_in_memory_missing_returns_none() -> None:
    reg = InMemoryPARegistry()
    assert await reg.get(uuid4()) is None


async def test_in_memory_list_recent_orders_newest_first() -> None:
    reg = InMemoryPARegistry()
    rids = [uuid4() for _ in range(5)]
    for rid in rids:
        await reg.put(rid, _payload(str(rid)))
    rows = list(await reg.list_recent(limit=3))
    assert [r["pa_request"]["meta"]["request_id"] for r in rows] == [
        str(rids[-1]), str(rids[-2]), str(rids[-3])
    ]


async def test_in_memory_upsert_does_not_duplicate() -> None:
    reg = InMemoryPARegistry()
    rid = uuid4()
    await reg.put(rid, _payload(str(rid), status="awaiting"))
    await reg.put(rid, _payload(str(rid), status="submitted"))
    rows = list(await reg.list_recent(limit=10))
    assert len(rows) == 1
    assert rows[0]["status"] == "submitted"


# ---------------------------------------------------------------------------
# SqlPARegistry (SQLite)
# ---------------------------------------------------------------------------

async def test_sql_registry_sqlite_roundtrip(tmp_path: Path) -> None:
    try:
        db = tmp_path / "pa.sqlite"
        reg = SqlPARegistry(database_url=f"sqlite+aiosqlite:///{db}")
        rid = uuid4()
        await reg.put(rid, _payload(str(rid)))
        out = await reg.get(rid)
        assert out is not None
        assert out["status"] == "submitted"
    except ModuleNotFoundError as e:
        pytest.skip(f"aiosqlite missing: {e}")


async def test_sql_registry_list_recent(tmp_path: Path) -> None:
    try:
        db = tmp_path / "pa-list.sqlite"
        reg = SqlPARegistry(database_url=f"sqlite+aiosqlite:///{db}")
        rids = [uuid4() for _ in range(3)]
        for rid in rids:
            await reg.put(rid, _payload(str(rid)))
        rows = list(await reg.list_recent(limit=2))
        assert len(rows) == 2
    except ModuleNotFoundError as e:
        pytest.skip(f"aiosqlite missing: {e}")
