"""PA registry — tenant-scoped persistence for `PARunResponse`-shaped records.

v1.0 GA: every method takes a `tenant_id`. Two implementations:

- `InMemoryPARegistry`: nested dict-of-dicts keyed by tenant.
- `SqlPARegistry`: SQLAlchemy async + JSON payload column; the schema adds a
  `(tenant_id, updated_at DESC)` index for fast per-tenant listing.

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
    """Async append + lookup store, partitioned by `tenant_id`."""

    async def put(
        self, tenant_id: str, request_id: UUID, payload: dict[str, Any]
    ) -> None: ...
    async def get(
        self, tenant_id: str, request_id: UUID
    ) -> dict[str, Any] | None: ...
    async def list_recent(
        self, tenant_id: str, *, limit: int = 50
    ) -> Iterable[dict[str, Any]]: ...


class InMemoryPARegistry:
    """Default backend — process-local dict-of-dicts. Loses data on restart."""

    def __init__(self) -> None:
        # tenant_id → rid → payload
        self._by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        # tenant_id → ordered list of rids (insertion order)
        self._order: dict[str, list[str]] = {}

    async def put(
        self, tenant_id: str, request_id: UUID, payload: dict[str, Any]
    ) -> None:
        rid = str(request_id)
        bucket = self._by_tenant.setdefault(tenant_id, {})
        if rid not in bucket:
            self._order.setdefault(tenant_id, []).append(rid)
        bucket[rid] = payload

    async def get(
        self, tenant_id: str, request_id: UUID
    ) -> dict[str, Any] | None:
        return self._by_tenant.get(tenant_id, {}).get(str(request_id))

    async def list_recent(
        self, tenant_id: str, *, limit: int = 50
    ) -> Iterable[dict[str, Any]]:
        if limit <= 0:
            return []
        bucket = self._by_tenant.get(tenant_id, {})
        order = self._order.get(tenant_id, [])
        return [bucket[r] for r in order[-limit:][::-1] if r in bucket]


class SqlPARegistry:
    """SQLAlchemy-async backed store. Works on Postgres + SQLite."""

    DDL_SQLITE = """
    CREATE TABLE IF NOT EXISTS pa_runs (
        tenant_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (tenant_id, request_id)
    )
    """

    DDL_SQLITE_IDX = """
    CREATE INDEX IF NOT EXISTS pa_runs_tenant_updated
        ON pa_runs (tenant_id, updated_at DESC)
    """

    DDL_PG = """
    CREATE TABLE IF NOT EXISTS pa_runs (
        tenant_id TEXT NOT NULL,
        request_id UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payload JSONB NOT NULL,
        PRIMARY KEY (tenant_id, request_id)
    )
    """

    DDL_PG_IDX = """
    CREATE INDEX IF NOT EXISTS pa_runs_tenant_updated
        ON pa_runs (tenant_id, updated_at DESC)
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

        ddls = (
            (self.DDL_PG, self.DDL_PG_IDX)
            if self._is_postgres
            else (self.DDL_SQLITE, self.DDL_SQLITE_IDX)
        )
        async with self._engine.begin() as conn:
            for ddl in ddls:
                await conn.execute(text(ddl))
        self._initialized = True

    # ------------------------------------------------------------------

    async def put(
        self, tenant_id: str, request_id: UUID, payload: dict[str, Any]
    ) -> None:
        from sqlalchemy import text

        await self._ensure_schema()
        now = datetime.now(UTC).isoformat()
        rid = str(request_id)
        if self._is_postgres:
            query = text(
                """
                INSERT INTO pa_runs (tenant_id, request_id, created_at, updated_at, payload)
                VALUES (:tid, :rid, :now, :now, :payload::jsonb)
                ON CONFLICT (tenant_id, request_id) DO UPDATE
                  SET updated_at = EXCLUDED.updated_at,
                      payload    = EXCLUDED.payload
                """
            )
        else:
            query = text(
                """
                INSERT OR REPLACE INTO pa_runs (tenant_id, request_id, created_at, updated_at, payload)
                VALUES (
                    :tid,
                    :rid,
                    COALESCE(
                      (SELECT created_at FROM pa_runs
                        WHERE tenant_id = :tid AND request_id = :rid),
                      :now
                    ),
                    :now,
                    :payload
                )
                """
            )
        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {"tid": tenant_id, "rid": rid, "now": now, "payload": json.dumps(payload)},
            )

    async def get(
        self, tenant_id: str, request_id: UUID
    ) -> dict[str, Any] | None:
        from sqlalchemy import text

        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT payload FROM pa_runs "
                        "WHERE tenant_id = :tid AND request_id = :rid"
                    ),
                    {"tid": tenant_id, "rid": str(request_id)},
                )
            ).first()
        if row is None:
            return None
        raw = row[0]
        return raw if isinstance(raw, dict) else json.loads(raw)

    async def list_recent(
        self, tenant_id: str, *, limit: int = 50
    ) -> Iterable[dict[str, Any]]:
        from sqlalchemy import text

        await self._ensure_schema()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT payload FROM pa_runs "
                        "WHERE tenant_id = :tid "
                        "ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"tid": tenant_id, "limit": int(limit)},
                )
            ).all()
        return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


__all__ = ["InMemoryPARegistry", "PARegistry", "SqlPARegistry"]
