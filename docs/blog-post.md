---
title: 'An agent-payable API with x402: two chains, REST, and MCP'
graphLabel: 'x402 agent-payable API'
description: 'A FastAPI service that sells data to AI agents over x402, settled in testnet USDC on Base and Solana, served as both REST and MCP. The interesting parts are gasless settlement on Solana and wiring MCP payments against an SDK whose docs do not match the installed code.'
pubDate: '20 Jun 2026'
draft: true
tags:
  - x402
  - MCP
  - FastAPI
  - Solana
  - Base
  - USDC
  - Python
---

I built a small API that charges an autonomous agent a fraction of a cent per request, in stablecoins, with no account and no API key. The agent asks for a resource, gets back HTTP 402 with a price and a list of chains it can pay on, signs a payment, and retries. A facilitator verifies the payment, settles it on-chain, and pays the gas, so the agent only ever spends USDC. The same data is sold two ways from one deployment: a REST endpoint and an MCP tool.

This is a testnet-only proof of concept. Every payment below is Base Sepolia or Solana devnet USDC, zero real money, so read it as a design note rather than a production claim. The data it sells is the SEC EDGAR ticker-to-CIK reference set, which is public and key-free; the point is the payment rails, not the dataset.

### The 402 handshake

[x402](https://x402.org) is Coinbase's revival of HTTP 402 Payment Required for machine-to-machine payments. The flow is the protocol:

1. The client GETs a paid resource with no payment header.
2. The server returns 402 with a body listing what it accepts: scheme, price, asset, and CAIP-2 network, one entry per chain.
3. The client picks a chain, signs a stablecoin transfer authorization, and retries with the signed payload in a header.
4. A facilitator verifies the payload, settles it on-chain, and the server returns the data plus a settlement receipt header.

The server never holds a private key and never touches the chain directly. A facilitator does the verify-and-settle and fronts the gas. The public `x402.org/facilitator` is keyless on both testnets, which is what makes a keyless POC possible.

### One service, two surfaces

The REST side is a FastAPI app with the x402 ASGI middleware gating two routes. A 402 from a route that has a wallet configured on both chains lists both options, so a single endpoint is dual-chain and the client decides where to pay.

The MCP side is the same payment rails behind Model Context Protocol tools, so an agent runtime discovers, pays for, and calls them natively. Rather than run a second process, the MCP server mounts onto the same FastAPI app. The one wrinkle is that the streamable-HTTP MCP app owns a session manager that has to run inside the host app's lifespan:

```python
def create_app() -> FastAPI:
    server = build_server()
    server.initialize()           # one facilitator round-trip, shared by both surfaces
    mcp = build_mcp(server)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(settings.database_url)
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await close_db()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(PaymentMiddlewareASGI, routes=build_routes(), server=server)
    app.include_router(router)
    app.mount("/", mcp_app)        # MCP at /mcp; the API's own routes match first
    return app
```

One resource server backs both surfaces. The REST middleware and the MCP tools call the same verify and settle methods, and the same receipts hook fires for both.

### Gasless on Solana, and the token account no faucet gives you

On Base the payer signs an EIP-3009 `transferWithAuthorization`, which is gasless by design: the facilitator submits the transaction and pays the ETH. Solana's exact scheme is gasless too, but for a less obvious reason. The facilitator advertises itself as the transaction fee payer, and the client builds a partially signed transaction with the facilitator at signer index 0 and the payer at index 1:

```
# from the requirements the facilitator returns
extra["feePayer"] = "<facilitator address>"
# client builds: signers = [fee_payer (facilitator), payer (you)]
```

So the agent paying on Solana needs no SOL at all. It signs, the facilitator pays the network fee. That removes the usual "fund the wallet with native token first" step entirely.

There is still one thing that needs to exist on-chain before a USDC transfer can land: the receiver's associated token account. SPL transfers fail if the destination has no token account for that mint, and the facilitator pays fees but does not create accounts. Creating one normally costs a little SOL for rent, which loops back to needing SOL that the gasless design otherwise avoids.

The devnet SOL airdrop did not cooperate. The public RPC `requestAirdrop` was rate-limited to failure, and the web faucet rejected the GitHub account behind it for having too few public repositories. The way out sidesteps SOL completely: drip Circle's devnet USDC to the receiver address. The faucet creates the destination token account as a side effect of sending tokens to it, for free. After that the gasless settlement has somewhere to land, and the payer never needed a single lamport.

A real devnet settlement, fee paid by the facilitator and not the payer:

```
settled on solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1
tx: 3beBZXavcD5Z6zqSiZfxiv3Y5zhaa38i8pLZLj5k1rP8eZ4rX2UNwe4soTD8e5WJisJU2mWzVyrE68opjwCufg5M
```

### MCP payments, where the docstrings lie

The most time went into one thing: getting a paid MCP tool to work against `x402` 2.13.1 with the bundled `mcp` 1.28.0. The package's README, docstrings, and examples describe an API that does not exist on a clean install. The path they point at, `server_async.create_payment_wrapper` plus `wrap_fastmcp_tool`, fails on import, because `server_async.py` imports two helpers from `server.py` that are not defined there. Following the docs gets an ImportError before any payment logic runs.

The working path is a different `create_payment_wrapper`, the one `x402.mcp.create_payment_wrapper` actually resolves to. It is a decorator factory applied directly under `@mcp.tool`, and it injects its own context parameter, so the tool handler keeps a clean signature:

```python
from x402.mcp import create_payment_wrapper
from x402.schemas.config import ResourceConfig
from x402.schemas.payments import ResourceInfo   # the pydantic one, NOT x402.mcp.ResourceInfo

accepts = server.build_payment_requirements(
    ResourceConfig(scheme="exact", pay_to=EVM_PAY_TO, price="$0.001", network="eip155:84532"))

paid = create_payment_wrapper(server, accepts=accepts,
    resource=ResourceInfo(url="mcp://tool/get_company", mime_type="application/json"))

@mcp.tool(name="get_company", description="...")   # outer
@paid                                              # inner, closest to the function
async def get_company(ticker: str) -> str:         # `ticker` is the whole input schema
    return json.dumps(await lookup(ticker))
```

Two traps inside that small block. `ResourceInfo` has to be imported from `x402.schemas.payments`, not from `x402.mcp`; the same-named class at the package root has no `model_dump` and the wrapper throws on it. And the wrapper verifies and settles against `accepts[0]`, not against the chain the client actually chose, so for a multi-chain tool the chain you expect clients to use has to be first in the list.

The client side has its own surprises. The streamable-HTTP factory is `x402.mcp.client_async.create_x402_mcp_client(mcp_client, payment_client)`; the identically named export at the package root is a different, SSE-only helper. And the payment client expects to call `call_tool` with a single dict and to read the settlement back off a `_meta` attribute, while the standard MCP `ClientSession` takes positional arguments and stores response metadata under `.meta`. A thin adapter reconciles both, and the second half matters: the SDK puts the settlement under `.meta`, the x402 client reads `getattr(result, "_meta", {})`, so without re-exposing one as the other the payment silently succeeds on-chain while the client reports no settlement.

```python
class _SessionResult:
    def __init__(self, raw):
        self.content, self.isError = raw.content, raw.isError
        self.structuredContent = raw.structuredContent
        self._meta = raw.meta or {}     # SDK stores meta under .meta; x402 reads ._meta

class _SessionAdapter:
    def __init__(self, session): self._session = session
    async def call_tool(self, params, **_):
        raw = await self._session.call_tool(
            params["name"], params.get("arguments"), meta=params.get("_meta"))
        return _SessionResult(raw)
```

With that in place a paid MCP tool call settles the same way the REST call does, on-chain:

```
tools: get_company, search_companies
payment_made: True
settled on eip155:84532
tx: 0xc62f5961cbc7f3ddba1569db5e55f807fb4a67809d6fba19f1c40cba53678b1b
```

The lesson is the boring one: when an SDK's docs and its installed code disagree, the code wins, and the fastest way to the truth is to read the package in your virtualenv rather than the README on the web.

### Receipts after the fact

Settlement happens after the route handler returns, so the receipt cannot be written in the handler. x402 exposes an `on_after_settle` hook that fires once the payment lands. It records the transaction, chain, payer, amount, and the resource that was paid for, which a free `/v1/receipts` endpoint then serves as an on-chain audit trail. The resource path comes off the HTTP transport context, which is absent for MCP calls, so the hook reads it defensively and leaves it null for tool payments.

The same hook persists both REST and MCP settlements, because both surfaces share the one resource server.

### What it is and is not

It is a working demonstration that an API can charge agents per request across two chains and two protocols, with on-chain settlement and no keys held server-side. It is not a production service: testnet only, a public-domain dataset standing in for whatever a real one would sell, and the public facilitator rather than a self-hosted one. Swapping the dataset is two functions, and pointing at a private facilitator is one setting. The code is on [GitHub](https://github.com/byrmsh/x402-agent-api).
