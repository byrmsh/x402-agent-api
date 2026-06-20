"""Postgres pool (asyncpg) and schema. No-op when DATABASE_URL is unset.

Neon serverless in prod, local docker Postgres in dev. The pool is created in the FastAPI
lifespan and shared across requests; scale-to-zero friendly (small pool, opened on startup).
"""

from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    cik    BIGINT NOT NULL,
    title  TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS companies_title_idx ON companies (title);

CREATE TABLE IF NOT EXISTS settlements (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction TEXT NOT NULL,
    network     TEXT NOT NULL,
    payer       TEXT,
    pay_to      TEXT,
    amount      TEXT,
    resource    TEXT,
    settled_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS settlements_settled_at_idx ON settlements (settled_at DESC);
"""


def get_pool() -> asyncpg.Pool | None:
    return _pool


async def init_db(database_url: str) -> None:
    """Open the pool and ensure the schema exists."""
    global _pool
    if not database_url:
        return
    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
