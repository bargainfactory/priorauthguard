"""PA registry — tenant-scoped persistence for `PARunResponse`-shaped records.

v1.0.3: filters (status / urgency / payer_id) push **into** the registry so
SQL backends translate them to indexed JSON predicates rather than
over-fetching and post-filtering in Python.

Two implementations:

- `InMemoryPARegistry`: nested dict-of-dicts keyed by tenant.
- `SqlPARegistry`: SQLAlchemy async + JSON payload column; uses
  Postgres `payload->'pa_request'->'meta'->>'payer_id'` predicates and
  the equivalent SQLite `json_extract(payload, '$.pa_request.meta.payer_id')`
  so filters are evaluated server-side.

Both expose the same Protocol so swapping is a one-line change in the
FastAPI lifespan.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class PAListFilters:
    """Server-side filter shape for `list_recent`.

    Every field is optional; `None` means "no constraint".
    """

    status: str | None = None
    urgency: str | None = None
    payer_id: str | None = None

    def is_empty(self) -> bool:
        return self.status is None and self.urgency is None and self.payer_id is None


class PARegistry(Protocol):
    """Async append + lookup store, partitioned by `tenant_id`."""

    async def put(
        self, tenant_id: str, request_id: UUID, payload: dict[str, Any]
    ) -> None: ...
    async def get(
        self, tenant_id: str, request_id: UUID
    ) -> dict[str, Any] | None: ...
    async def list_recent(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        filters: PAListFilters | None = None,
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
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        filters: PAListFilters | None = None,
    ) -> Iterable[dict[str, Any]]:
        if limit <= 0:
            return []
        bucket = self._by_tenant.get(tenant_id, {})
        order = self._order.get(tenant_id, [])
        f = filters or PAListFilters()
        out: list[dict[str, Any]] = []
        for rid in reversed(order):
            if rid not in bucket:
                continue
            row = bucket[rid]
            if not _row_matches(row, f):
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out


def _row_matches(row: dict[str, Any], f: PAListFilters) -> bool:
    if f.status is not None and row.get("status") != f.status:
        return False
    meta = (row.get("pa_request") or {}).get("meta") if row.get("pa_request") else None
    if f.urgency is not None or f.payer_id is not None:
        if meta is None:
            return False
        if f.urgency is not None and meta.get("urgency") != f.urgency:
            return False
        if f.payer_id is not None and meta.get("payer_id") != f.payer_id:
            return False
    return True


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
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        filters: PAListFilters | None = None,
    ) -> Iterable[dict[str, Any]]:
        from sqlalchemy import text

        await self._ensure_schema()
        f = filters or PAListFilters()

        # Build the WHERE clause with dialect-specific JSON predicates.
        clauses: list[str] = ["tenant_id = :tid"]
        params: dict[str, Any] = {"tid": tenant_id, "limit": int(limit)}

        if f.status is not None:
            clauses.append(self._json_eq("status") + " = :status")
            params["status"] = f.status
        if f.payer_id is not None:
            clauses.append(self._json_meta_eq("payer_id") + " = :payer_id")
            params["payer_id"] = f.payer_id
        if f.urgency is not None:
            clauses.append(self._json_meta_eq("urgency") + " = :urgency")
            params["urgency"] = f.urgency

        # `where` is composed exclusively from `clauses`, which come from
        # a fixed set of dialect-aware JSON predicates plus bound params.
        # No user input ever lands inside the `text(...)` literal — safe
        # by construction.
        where = " AND ".join(clauses)
        sql = (
            "SELECT payload FROM pa_runs "  # noqa: S608
            f"WHERE {where} "
            "ORDER BY updated_at DESC LIMIT :limit"
        )
        query = text(sql)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query, params)).all()
        return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]

    # ------------------------------------------------------------------
    # Dialect-aware JSON path expressions.
    # ------------------------------------------------------------------

    def _json_eq(self, key: str) -> str:
        """Top-level scalar (e.g. payload['status'])."""
        if self._is_postgres:
            return f"payload->>'{key}'"
        return f"json_extract(payload, '$.{key}')"

    def _json_meta_eq(self, key: str) -> str:
        """Nested scalar at payload['pa_request']['meta'][key]."""
        if self._is_postgres:
            return f"payload->'pa_request'->'meta'->>'{key}'"
        return f"json_extract(payload, '$.pa_request.meta.{key}')"


__all__ = ["InMemoryPARegistry", "PAListFilters", "PARegistry", "SqlPARegistry"]
