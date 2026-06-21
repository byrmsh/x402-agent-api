# Installed truth — x402 2.13.1 (verified against `.venv` site-packages, 2026-06-20)

Every symbol below was read from the installed package, not docs/blogs. Code is written against THIS, not the
research snippets (several of which were stale). Re-verify after any `x402` bump.

## Versions (resolved on Python 3.12, all wheels, no Rust build)
`x402==2.13.1`, `mcp==1.28.0`, `solana==0.37.1`, `solders==0.27.1`, `web3==7.16.0`, `pydantic==2.13.4`,
`starlette==1.3.1`, `uvicorn==0.49.0`, `sqlalchemy==2.0.51`, `asyncpg==0.31.0`.

## Resource server (async) — `x402.server.x402ResourceServer`
- ctor: `x402ResourceServer(facilitator_clients: FacilitatorClient | list[FacilitatorClient] | None)`.
- `.register(network: str, scheme_server) -> Self` — e.g. `ExactEvmServerScheme()`, `ExactSvmServerScheme()`.
- `.initialize()` — fetches `/supported` from each facilitator; **must run before `build_payment_requirements`**.
- `.build_payment_requirements(ResourceConfig(...)) -> list[PaymentRequirements]` (single-element list).
- `.verify_payment(payload, requirements)` / `.settle_payment(payload, requirements)` (async).
- hooks (chainable, async or sync auto-detected): `.on_after_settle(hook)`, `.on_settle_failure`, `.on_after_verify`, ...

## Facilitator
- HTTP client: `from x402.http import FacilitatorConfig, HTTPFacilitatorClient` →
  `HTTPFacilitatorClient(FacilitatorConfig(url="https://x402.org/facilitator"))`. Use the `FacilitatorConfig` form
  (bare-url form in some docs is unverified).
- Self-host: `x402.facilitator.x402Facilitator` (async `.verify`, `.settle`). To self-host we expose our own
  `/verify`/`/settle`/`/supported` endpoints (own signer wallets) and point `HTTPFacilitatorClient` at our URL.
  Default stays the public facilitator; self-host is config-toggled for Solana reliability.

## HTTP middleware (FastAPI)
- `from x402.http.middleware.fastapi import PaymentMiddlewareASGI, payment_middleware`
- `from x402.http.types import RouteConfig` ; `from x402.http import PaymentOption`
- `PaymentOption(scheme="exact", pay_to=<addr>, price="$0.01" | AssetAmount(...), network=<caip2>, max_timeout_seconds?, extra?)`
- `RouteConfig(accepts=PaymentOption | list[PaymentOption], resource?, description?, mime_type?, ...)`
- routes = `dict["<METHOD> <pathglob>", RouteConfig]`; attach `app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)`.
- **REST supports true dual-chain**: a route with `accepts=[PaymentOption(EVM), PaymentOption(SVM)]`; the middleware
  matches the chain the client actually paid on.

## Settlement result — `x402.schemas.responses.SettleResponse`
Fields: `success: bool`, `error_reason: str|None`, `error_message: str|None`, `payer: str|None`,
`transaction: str` (REQUIRED — the on-chain id, 0x hash on EVM / base58 sig on Solana, same field both chains),
`network: str`, `amount: str|None` (atomic units, OPTIONAL). The adversary's "no amount field" was wrong, but
`amount` is optional so source it defensively: `ctx.result.amount or ctx.requirements.amount`.

## Receipts hook — `on_after_settle(hook)` gets `SettleResultContext`
From `x402.schemas.hooks.SettleResultContext`: `.result` (`SettleResponse`), `.requirements` (`PaymentRequirements`),
`.payment_payload`, `.transport_context`. So one hook yields tx, network, payer, amount, and the full requirements.
Settlement fires AFTER the route returns, so receipts MUST be written here, not in the route handler.

## PaymentRequirements — `x402.schemas.payments.PaymentRequirements`
`scheme, network, asset, amount(str, atomic), pay_to, max_timeout_seconds(int), extra(dict)`.

## ResourceConfig (for building MCP/REST requirements) — `x402.schemas.config.ResourceConfig`
`scheme, pay_to, price(Price), network, max_timeout_seconds?, extra?`.

## MCP — bundled `mcp.server.fastmcp.FastMCP` (verified end to end; the docstrings lie, this is the working path)
Server side (`app/mcp_server.py`):
```python
from x402.mcp import create_payment_wrapper          # resolves to mcp/server.py (a decorator factory)
from x402.schemas.config import ResourceConfig
from x402.schemas.payments import ResourceInfo       # the pydantic one; NOT x402.mcp.ResourceInfo

server = build_server(); server.initialize()         # initialize() is sync, required before build
accepts = server.build_payment_requirements(ResourceConfig(scheme="exact", pay_to=..., price="$0.001", network="eip155:84532"))
paid = create_payment_wrapper(server, accepts=accepts, resource=ResourceInfo(url="mcp://tool/get_company", mime_type="application/json"))

@mcp.tool(name="get_company", description="...")     # @mcp.tool OUTER
@paid                                                # @paid INNER (closest to fn)
async def get_company(ticker: str) -> str:           # clean signature; wrapper injects ctx: Context
    return json.dumps(...)
```
- **The `server_async.create_payment_wrapper` / `wrap_fastmcp_tool` / `PaymentWrapperConfig` path is dead on
  import**: `server_async.py` imports `_extract_meta_from_fastmcp_context` and `_mcp_tool_result_to_call_tool_result`
  from `.server`, and neither exists. The live wrapper is `x402.mcp.create_payment_wrapper` → `mcp/server.py`, a
  decorator factory `create_payment_wrapper(server, *, accepts, resource, hooks?, extensions?)`. It does NOT take a
  `PaymentWrapperConfig` and does NOT use `(args, extra)`.
- **`ResourceInfo` must be `x402.schemas.payments.ResourceInfo`** (pydantic). The same-named `x402.mcp.ResourceInfo`
  has no `model_dump` and the wrapper raises `AttributeError` on it.
- **The wrapper verifies+settles against `accepts[0]`** (no `find_matching_requirements`). Multi-chain `accepts`
  registers fine, but list the chain you expect clients to pay first. The REST endpoint carries the true dual-chain
  story; MCP settles the first-listed chain (EVM here).
- **`wrap_fastmcp_tool_sync` does NOT exist** in 2.13.1; its example is broken on a clean install.

Client side (`client/agent_demo.py`):
- Import `from x402.mcp.client_async import create_x402_mcp_client` (signature `(mcp_client, payment_client)`).
  The package-root `x402.mcp.create_x402_mcp_client` is a DIFFERENT, SSE-only helper `(client, url)`.
- `x402MCPClient` calls `mcp_client.call_tool({"name","arguments","_meta"})`; wrap a standard `ClientSession` in a
  thin adapter that unpacks the dict and forwards `_meta -> meta` (ClientSession `meta=` goes into
  `RequestParams.Meta`, which is `extra="allow"`, so the slash-key `x402/payment` survives the wire).
- Result meta gotcha: the SDK `CallToolResult` stores meta under `.meta`; x402's `convert_mcp_result` reads
  `getattr(result, "_meta", {})`. Re-expose `.meta` as `_meta` on the result or the settlement is silently dropped.
- Mounting on FastAPI: `app.mount("/", mcp.streamable_http_app())` and run `mcp.session_manager.run()` inside the
  host lifespan; the MCP endpoint is then exactly `/mcp` (default `streamable_http_path`).
- **Behind a real hostname the mounted MCP app 421s every request unless transport security is set.** `FastMCP`
  defaults its host to `127.0.0.1`, which auto-builds `TransportSecuritySettings(enable_dns_rebinding_protection=True,
  allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"])` (`mcp/server/fastmcp/server.py:178`). Deployed (Cloud Run),
  the Host header is the public domain, absent from that list, so every POST gets `421 Invalid Host header`
  (`mcp/server/transport_security.py:120`) while localhost keeps working. Pass
  `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to `FastMCP(...)`: the guard
  targets browser DNS rebinding against localhost servers, not a public TLS API called by arbitrary agents.
- payment carried in MCP `_meta` keys `x402/payment` (request) / `x402/payment-response` (response).

## Chain constants (re-verify mints before mainnet; testnet only here)
- Base Sepolia: `eip155:84532`, USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`, EIP-712 name `USDC` v`2`, 6 dec.
  EIP-3009 gasless: payer needs USDC only. Request header `PAYMENT-SIGNATURE` (V2), not `X-PAYMENT` (V1).
- Solana devnet: `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`, USDC mint
  `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, 6 dec. SPL TransferChecked. Gasless via facilitator feePayer.
  **Receiver USDC ATA must exist before settlement** (the facilitator pays fees but does not create it; a missing
  receiver ATA = silent settle failure, `success=False`, empty `transaction`). Simplest way to create it without
  needing any SOL: drip Circle devnet USDC to the receiver address at faucet.circle.com, which creates the token
  account as a side effect. (The devnet SOL airdrop RPC and faucet.solana.com were both unreliable/blocked.)
- Explorer: `https://sepolia.basescan.org/tx/<0xhash>` ; `https://explorer.solana.com/tx/<sig>?cluster=devnet`
  (the `?cluster=devnet` is mandatory).

## Mechanism scheme imports
- `from x402.mechanisms.evm.exact import ExactEvmServerScheme, ExactEvmScheme` (Server* for the server side).
- `from x402.mechanisms.svm.exact import ExactSvmServerScheme, ExactSvmScheme`.
- client registration: `from x402.mechanisms.evm.exact.register import register_exact_evm_client`,
  `from x402.mechanisms.svm.exact.register import register_exact_svm_client`,
  signers `x402.mechanisms.evm.EthAccountSigner`, `x402.mechanisms.svm.KeypairSigner` (verify these import paths in P1/P2).
