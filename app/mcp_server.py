"""MCP server exposing the paid data tools, mounted on the FastAPI app at /mcp.

Same x402 rails as the REST API, surfaced as MCP tools so an agent runtime can discover, pay for,
and call them natively. The verified integration path for x402 2.13.1 + bundled mcp 1.28.0:

- `x402.mcp.create_payment_wrapper` is a decorator factory `(server, *, accepts, resource, ...)`.
  Apply it as the INNER decorator (closest to the function); `@mcp.tool` is the outer one. The
  wrapper injects a synthetic `ctx: Context` param, so the handler signature stays clean (just the
  tool's real arguments) and that is what surfaces in the tool inputSchema.
- `ResourceInfo` must come from `x402.schemas.payments` (pydantic); the same-named class re-exported
  from `x402.mcp` has no `model_dump` and the wrapper raises on it.
- The wrapper verifies and settles against `accepts[0]` (it does not match the client's chosen
  chain), so the chain a client pays on must be listed first.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from x402.mcp import create_payment_wrapper
from x402.schemas.config import ResourceConfig
from x402.schemas.payments import ResourceInfo

from .config import EVM_NETWORK, SVM_NETWORK, settings
from .data import get_company, search_companies
from .x402_server import build_server


def _accepts(server, price: str):
    """One PaymentRequirements per configured chain (EVM first, since the wrapper settles accepts[0])."""
    accepts = []
    if settings.evm_pay_to:
        accepts += server.build_payment_requirements(
            ResourceConfig(scheme="exact", pay_to=settings.evm_pay_to, price=price, network=EVM_NETWORK)
        )
    if settings.svm_pay_to:
        accepts += server.build_payment_requirements(
            ResourceConfig(scheme="exact", pay_to=settings.svm_pay_to, price=price, network=SVM_NETWORK)
        )
    if not accepts:
        raise RuntimeError("No receiving wallet configured: set EVM_PAY_TO and/or SVM_PAY_TO")
    return accepts


def build_mcp() -> FastMCP:
    server = build_server()
    server.initialize()  # sync; loads facilitator-supported kinds before building requirements

    mcp = FastMCP("x402-agent-api", stateless_http=True)

    paid_lookup = create_payment_wrapper(
        server,
        accepts=_accepts(server, settings.price_lookup),
        resource=ResourceInfo(
            url="mcp://tool/get_company",
            description="One SEC EDGAR company reference record by ticker",
            mime_type="application/json",
        ),
    )
    paid_search = create_payment_wrapper(
        server,
        accepts=_accepts(server, settings.price_search),
        resource=ResourceInfo(
            url="mcp://tool/search_companies",
            description="Search the SEC EDGAR company reference dataset",
            mime_type="application/json",
        ),
    )

    @mcp.tool(name="get_company", description=f"Look up a company by ticker (paid: {settings.price_lookup}).")
    @paid_lookup
    async def get_company_tool(ticker: str) -> str:
        record = await get_company(ticker)
        if record is None:
            return json.dumps({"error": f"unknown ticker {ticker!r}"})
        return json.dumps(record)

    @mcp.tool(name="search_companies", description=f"Search companies by ticker or name (paid: {settings.price_search}).")
    @paid_search
    async def search_companies_tool(q: str) -> str:
        results = await search_companies(q, limit=settings.search_limit)
        return json.dumps({"query": q, "count": len(results), "results": results})

    return mcp
