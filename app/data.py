"""The structured dataset agents pay to query: SEC EDGAR company reference (ticker -> CIK -> title).

Public-domain, key-free. Backed by Postgres when DATABASE_URL is set; otherwise a small bundled
sample keeps the service runnable for the 402 handshake and unit tests. The dataset is swappable:
a client's own data drops in behind the same two functions.
"""

from __future__ import annotations

from typing import Any

# Fallback sample (used when no Postgres is configured). Real seed: scripts/seed_edgar.py.
SAMPLE: list[dict[str, Any]] = [
    {"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."},
    {"ticker": "MSFT", "cik": 789019, "title": "Microsoft Corp"},
    {"ticker": "NVDA", "cik": 1045810, "title": "NVIDIA Corp"},
    {"ticker": "TSLA", "cik": 1318605, "title": "Tesla, Inc."},
    {"ticker": "COIN", "cik": 1679788, "title": "Coinbase Global, Inc."},
]
_SAMPLE_BY_TICKER = {row["ticker"]: row for row in SAMPLE}


def _cik_str(cik: int) -> str:
    """EDGAR's zero-padded 10-digit CIK, as used in filing URLs."""
    return f"CIK{cik:010d}"


def _enrich(row: dict[str, Any]) -> dict[str, Any]:
    cik = row["cik"]
    cik_str = _cik_str(cik)
    return {
        "ticker": row["ticker"],
        "cik": cik,
        "cik_str": cik_str,
        "title": row["title"],
        "filings_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K",
        "facts_api": f"https://data.sec.gov/api/xbrl/companyfacts/{cik_str}.json",
    }


async def get_company(ticker: str) -> dict[str, Any] | None:
    """One enriched company record by ticker (case-insensitive)."""
    ticker = ticker.strip().upper()
    from .db import get_pool

    pool = get_pool()
    if pool is None:
        row = _SAMPLE_BY_TICKER.get(ticker)
        return _enrich(row) if row else None
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT ticker, cik, title FROM companies WHERE ticker = $1", ticker
        )
    return _enrich(dict(rec)) if rec else None


async def search_companies(q: str, limit: int) -> list[dict[str, Any]]:
    """Companies whose ticker or title matches q (prefix on ticker, substring on title)."""
    q = q.strip()
    if not q:
        return []
    from .db import get_pool

    pool = get_pool()
    if pool is None:
        ql = q.lower()
        hits = [
            r for r in SAMPLE if r["ticker"].lower().startswith(ql) or ql in r["title"].lower()
        ]
        return [_enrich(r) for r in hits[:limit]]
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            """
            SELECT ticker, cik, title FROM companies
            WHERE ticker ILIKE $1 || '%' OR title ILIKE '%' || $1 || '%'
            ORDER BY ticker
            LIMIT $2
            """,
            q,
            limit,
        )
    return [_enrich(dict(r)) for r in recs]
