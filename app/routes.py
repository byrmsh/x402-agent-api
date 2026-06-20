"""HTTP routes. Free: /health, /v1/catalog, /v1/receipts. Paid (x402-gated): /v1/company, /v1/search.

Paid routes are declared in app.x402_server.build_routes(); the middleware enforces payment, so these
handlers just serve data and assume payment already settled.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .config import configured_chains, settings
from .data import get_company, search_companies
from .receipts import list_settlements

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/catalog")
async def catalog() -> dict:
    """Discovery surface: what data is sold, at what price, on which chains. Free."""
    return {
        "service": "x402 agent-payable company reference API",
        "dataset": "SEC EDGAR company tickers (ticker, CIK, title)",
        "chains": [
            {"network": c.network, "label": c.label, "asset": c.usdc} for c in configured_chains()
        ],
        "endpoints": [
            {"path": "/v1/company/{ticker}", "price": settings.price_lookup, "paid": True},
            {"path": "/v1/search?q=", "price": settings.price_search, "paid": True},
            {"path": "/v1/receipts", "price": "free", "paid": False},
        ],
    }


@router.get("/v1/receipts")
async def receipts() -> dict:
    """Public on-chain audit trail of payments this API has settled. Free."""
    return {"settlements": await list_settlements(limit=20)}


@router.get("/v1/company/{ticker}")
async def company(ticker: str) -> dict:
    record = await get_company(ticker)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No company for ticker {ticker!r}")
    return record


@router.get("/v1/search")
async def search(q: str = Query(..., min_length=1)) -> dict:
    results = await search_companies(q, limit=settings.search_limit)
    return {"query": q, "count": len(results), "results": results}
