"""Dataset functions on the bundled-sample path (no Postgres configured)."""

from __future__ import annotations

import pytest

from app import data


@pytest.fixture(autouse=True)
def _no_pool(monkeypatch):
    """Force the sample path: get_pool() returns None so no DB is touched."""
    monkeypatch.setattr("app.db.get_pool", lambda: None)


def test_cik_str_zero_pads_to_ten_digits():
    assert data._cik_str(320193) == "CIK0000320193"


def test_enrich_builds_edgar_urls():
    enriched = data._enrich({"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."})
    assert enriched["cik_str"] == "CIK0000320193"
    assert "CIK=320193" in enriched["filings_url"]
    assert enriched["facts_api"].endswith("CIK0000320193.json")


async def test_get_company_is_case_insensitive():
    lower = await data.get_company("aapl")
    upper = await data.get_company("AAPL")
    assert lower == upper
    assert upper["title"] == "Apple Inc."


async def test_get_company_unknown_ticker_returns_none():
    assert await data.get_company("ZZZZNOPE") is None


async def test_search_matches_ticker_prefix_and_title_substring():
    by_ticker = await data.search_companies("AAP", limit=10)
    assert any(r["ticker"] == "AAPL" for r in by_ticker)

    by_title = await data.search_companies("coinbase", limit=10)
    assert any(r["ticker"] == "COIN" for r in by_title)


async def test_search_empty_query_returns_nothing():
    assert await data.search_companies("   ", limit=10) == []


async def test_search_respects_limit():
    results = await data.search_companies("a", limit=2)
    assert len(results) <= 2
