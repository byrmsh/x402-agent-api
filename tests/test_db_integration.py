"""Postgres-backed path: data lookup and receipt persistence.

Skipped unless DATABASE_URL points at a reachable Postgres. Operates only on its own
throwaway rows (unique ticker / transaction) and cleans them up, so it is safe to run
against the seeded EDGAR database.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from app import data
from app.db import close_db, get_pool, init_db
from app.receipts import list_settlements, record_settlement

load_dotenv()

TEST_TICKER = "ZZINTEG"
TEST_TX = "0xINTEGRATIONTEST0000000000000000000000000000000000000000000000000"


@pytest.fixture
async def pool():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        await init_db(url)
    except Exception as exc:  # unreachable DB, wrong creds, etc.
        pytest.skip(f"Postgres not reachable: {exc}")
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM companies WHERE ticker = $1", TEST_TICKER)
        await conn.execute("DELETE FROM settlements WHERE transaction = $1", TEST_TX)
    try:
        yield p
    finally:
        async with p.acquire() as conn:
            await conn.execute("DELETE FROM companies WHERE ticker = $1", TEST_TICKER)
            await conn.execute("DELETE FROM settlements WHERE transaction = $1", TEST_TX)
        await close_db()


async def test_get_company_reads_from_postgres(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO companies (ticker, cik, title) VALUES ($1, $2, $3)",
            TEST_TICKER, 999001, "Integration Test Corp",
        )
    record = await data.get_company(TEST_TICKER.lower())
    assert record is not None
    assert record["cik"] == 999001
    assert record["cik_str"] == "CIK0000999001"


async def test_search_treats_wildcards_literally(pool):
    # q='%' must not match every row; with ILIKE escaping it matches only literal '%'.
    results = await data.search_companies("%", limit=50)
    assert all("%" in r["ticker"] or "%" in r["title"] for r in results)


async def test_record_and_list_settlement(pool):
    await record_settlement(
        transaction=TEST_TX,
        network="eip155:84532",
        payer="0xpayer",
        amount="1000",
        pay_to="0xreceiver",
        resource="/v1/company/ZZINTEG",
    )
    rows = await list_settlements(limit=50)
    mine = [r for r in rows if r["transaction"] == TEST_TX]
    assert len(mine) == 1
    assert mine[0]["resource"] == "/v1/company/ZZINTEG"
    assert mine[0]["explorer"].startswith("https://sepolia.basescan.org/tx/")
