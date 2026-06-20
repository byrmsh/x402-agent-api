"""x402 resource-server wiring: facilitator, multi-chain schemes, routes, receipts hook.

The resource server only does the 402/verify/settle handshake. The data it gates lives in
app.data; settlement receipts are persisted from the on_after_settle hook (settlement fires
AFTER the route returns, so it cannot be done in the handler).
"""

from __future__ import annotations

import logging

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.schemas.hooks import SettleResultContext
from x402.server import x402ResourceServer

from .config import EVM_NETWORK, SVM_NETWORK, configured_chains, pay_to, settings
from .receipts import record_settlement

logger = logging.getLogger("x402_agent_api")

_SCHEME_FACTORIES = {EVM_NETWORK: ExactEvmServerScheme, SVM_NETWORK: ExactSvmServerScheme}


def _accepts(price: str) -> list[PaymentOption]:
    """One PaymentOption per configured chain. A route with both is genuinely dual-chain: the
    middleware settles on whichever chain the client paid on."""
    options = [
        PaymentOption(scheme="exact", pay_to=pay_to(c), price=price, network=c.network)
        for c in configured_chains()
    ]
    if not options:
        raise RuntimeError("No receiving wallet configured: set EVM_PAY_TO and/or SVM_PAY_TO")
    return options


def build_routes() -> dict[str, RouteConfig]:
    """Paid routes, keyed by '<METHOD> <pathglob>'. Free routes are simply absent."""
    return {
        "GET /v1/company/*": RouteConfig(
            accepts=_accepts(settings.price_lookup),
            mime_type="application/json",
            description="One company reference record (ticker, CIK, title)",
        ),
        "GET /v1/search": RouteConfig(
            accepts=_accepts(settings.price_search),
            mime_type="application/json",
            description="Search the company reference dataset",
        ),
    }


def _resource(ctx: SettleResultContext) -> str | None:
    """The path that was paid for. V2 dropped resource from requirements; it lives on the HTTP
    transport context, which is absent for non-HTTP transports (e.g. MCP)."""
    tctx = getattr(ctx, "transport_context", None)
    request = getattr(tctx, "request", None)
    return getattr(request, "path", None)


async def _on_after_settle(ctx: SettleResultContext) -> None:
    """Persist a settlement receipt after a payment settles on-chain."""
    res = ctx.result
    req = ctx.requirements
    # req.get_amount() (not req.amount) so a V1 requirements object, which stores it under
    # max_amount_required, does not raise.
    amount = res.amount or (req.get_amount() if req else None)
    logger.info(
        "settled %s on %s (payer=%s amount=%s) tx=%s",
        req.pay_to if req else "?",
        res.network,
        res.payer,
        amount,
        res.transaction,
    )
    if not settings.database_url:
        return
    await record_settlement(
        transaction=res.transaction,
        network=res.network,
        payer=res.payer,
        amount=amount,
        pay_to=req.pay_to if req else None,
        resource=_resource(ctx),
    )


def build_server() -> x402ResourceServer:
    """Resource server bound to the facilitator, with a scheme registered per configured chain."""
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=settings.facilitator_url))
    server = x402ResourceServer(facilitator)
    for c in configured_chains():
        server.register(c.network, _SCHEME_FACTORIES[c.network]())
    server.on_after_settle(_on_after_settle)
    return server
