"""Seed the companies table from SEC EDGAR's public ticker->CIK map.

Downloads https://www.sec.gov/files/company_tickers.json (public domain, key-free; SEC only
requires a descriptive User-Agent naming a contact). Replaces the companies table with the full
set of ~10k issuers. Idempotent: truncates and reloads on every run.

    DATABASE_URL=postgresql://... uv run python scripts/seed_edgar.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import SCHEMA  # noqa: E402

load_dotenv()

EDGAR_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC returns 403 to requests without a descriptive User-Agent that names a contact.
USER_AGENT = "x402-agent-api/1.0 (contact@bayram.sh)"


def _fetch_rows() -> list[tuple[str, int, str]]:
    resp = httpx.get(EDGAR_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    # Shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    by_ticker: dict[str, tuple[str, int, str]] = {}
    for entry in resp.json().values():
        ticker = str(entry["ticker"]).strip().upper()
        if ticker:  # last writer wins on the rare shared-ticker collision; ticker is the PK
            by_ticker[ticker] = (ticker, int(entry["cik_str"]), str(entry["title"]).strip())
    return list(by_ticker.values())


async def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set; nothing to seed.")
        sys.exit(1)

    rows = _fetch_rows()
    print(f"fetched {len(rows)} issuers from EDGAR")

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SCHEMA)
        # Atomic so a failed COPY rolls back the TRUNCATE instead of leaving the table empty.
        async with conn.transaction():
            await conn.execute("TRUNCATE companies")
            await conn.copy_records_to_table(
                "companies", records=rows, columns=["ticker", "cik", "title"]
            )
        count = await conn.fetchval("SELECT count(*) FROM companies")
        print(f"companies table now holds {count} rows")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
