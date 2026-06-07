"""PA registry — persistence for `PARunResponse`-shaped run records.

Two implementations:

- `InMemoryPARegistry`: the Phase 1 / Phase 2 default for dev + tests.
- `SqlPARegistry`: SQLAlchemy async + JSON payload column. Works on
  Postgres in production, SQLite in tests. Schema is intentionally tiny
  — we trade query speed for shape-flexibility so Phase-N domain-model
  edits don't require migrations.

Both expose the same Protocol so swapping is a one-line change in the
FastAPI lifespan.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


class PARegistry(Protocol):
    """Async append + lookup store keyed by PA `request_id`."""

    async def put(self, request_id: UUID, payload: dict[str, Any]) -> None: ...
    async def get(self, request_id: UUID) -> dict[str, Any] | None: ...
    async def list_recent(self, *, limit: int = 50) -> Iterable[dict[str, Any]]: ...


class InMemoryPARegistry:
    """Default backend — process-local dict. Loses data on restart."""

    def __init__(self) -> None:
        self._by_rid: dict[str, dict[str, Any]] = {}
        # Insertion order preserves `list_recent` semantics without sorting.
        self._rid_order: list[str] = []

    async def put(self, request_id: UUID, payload: dict[str, Any]) -> None:
        rid = str(request_id)
        if rid not in self._by_rid:
            self._rid_order.append(rid)
        self._by_rid[rid] = payload

    async def get(self, request_id: UUID) -> dict[str, Any] | None:
        return self._by_rid.get(str(request_id))

    async def list_recent(self, *, limit: int = 50) -> Iterable[dict[str, Any]]:
        if limit <= 0:
            return []
        rids = self._rid_order[-limit:][::-1]
        return [self._by_rid[r] for r in rids]


class SqlPARegistry:
    """SQLAlchemy-async backed store. Works on Postgres + SQLite."""

    DDL_SQLITE = """
    CREATE TABLE IF NOT EXISTS pa_runs (
        request_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """

    DDL_PG = """
    CREATE TABLE IF NOT EXISTS pa_runs (
        request_id UUID PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payload JSONB NOT NULL
    )
    """

    def __init__(self, database_url: str) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        self._url = database_url
        self._engine = create_async_engine(database_url, future=True)
        self._is_postgres = database_url.startswith(("postgresql", "postgres"))
        self._initialized = False

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return
        from sqlalchemy import text

        ddl = self.DDL_PG if self._is_postgres else self.DDL_SQLITE
        async with self._engine.begin() as conn:
            await conn.execute(text(ddl))
        self._initialized = True

    # ------------------------------------------------------------------

    async def put(self, request_id: UUID, payload: dict[str, Any]) -> None:
        from sqlalchemy import text

        await self._ensure_schema()
        now = datetime.now(UTC).isoformat()
        rid = str(request_id)
        # Idempotent upsert; SQLite needs an explicit replace, Postgres uses
        # ON CONFLICT.
        if self._is_postgres:
            query = text(
                """
                INSERT INTO pa_runs (request_id, created_at, updated_at, payload)
                VALUES (:rid, :now, :now, :payload::jsonb)
                ON CONFLICT (request_id) DO UPDATE
                  SET updated_at = EXCLUDED.updated_at,
                      payload    = EXCLUDED.payload
                """
            )
        else:
            query = text(
                """
                INSERT OR REPLACE INTO pa_runs (request_id, created_at, updated_at, payload)
                VALUES (
                    :rid,
                    COALESCE((SELECT created_at FROM pa_runs WHERE request_id = :rid), :now),
                    :now,
                    :payload
                )
                """
            )
        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {"rid": rid, "now": now, "payload": json.dumps(payload)},
            )

    async def get(self, request_id: UUID) -> dict[str, Any] | None:
        from sqlalchemy import text

        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT payload FROM pa_runs WHERE request_id = :rid"),
                    {"rid": str(request_id)},
                )
            ).first()
        if row is None:
            return None
        raw = row[0]
        return raw if isinstance(raw, dict) else json.loads(raw)

    async def list_recent(self, *, limit: int = 50) -> Iterable[dict[str, Any]]:
        from sqlalchemy import text

        await self._ensure_schema()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT payload FROM pa_runs "
                        "ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"limit": int(limit)},
                )
            ).all()
        return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


__all__ = ["InMemoryPARegistry", "PARegistry", "SqlPARegistry"]
